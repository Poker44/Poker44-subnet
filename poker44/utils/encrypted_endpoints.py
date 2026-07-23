"""Encrypted Axon endpoint commitments for opt-in miner IP protection."""

from __future__ import annotations

import copy
import ipaddress
import os
import time
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, Optional, Tuple


MASKED_AXON_IP = "192.0.2.1"
MASKED_AXON_PORT = 1234
MAX_COMMITMENT_BYTES = 128

PROTECTION_ENABLED_ENV = "POKER44_ENCRYPTED_AXON_ENABLED"
PUBLIC_KEY_ENV = "POKER44_ENDPOINT_PUBLIC_KEY"
PRIVATE_KEY_ENV = "POKER44_ENDPOINT_PRIVATE_KEY"
EXTERNAL_IP_ENV = "POKER44_AXON_EXTERNAL_IP"
EXTERNAL_PORT_ENV = "POKER44_AXON_EXTERNAL_PORT"
REFRESH_SECONDS_ENV = "POKER44_ENDPOINT_REFRESH_SECONDS"

# Miners may override this key for testnet or controlled deployments.
DEFAULT_PUBLIC_KEYS: Dict[int, str] = {
    126: "800b46d59966b347eb5f54346ebfbf3808dbd29717e2be38d716d63a2d629a09",
}


class EndpointProtectionError(RuntimeError):
    """Raised when endpoint protection cannot be configured safely."""


def _env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _decode_key(value: str, label: str) -> bytes:
    try:
        key = bytes.fromhex(value.strip())
    except ValueError as exc:
        raise EndpointProtectionError(f"{label} must be hexadecimal") from exc
    if len(key) != 32:
        raise EndpointProtectionError(f"{label} must contain exactly 32 bytes")
    return key


def _load_nacl():
    try:
        from nacl import exceptions as nacl_exceptions
        from nacl.public import PrivateKey, PublicKey, SealedBox
    except ImportError as exc:
        raise EndpointProtectionError(
            "PyNaCl is required when encrypted Axon endpoints are enabled"
        ) from exc
    return nacl_exceptions, PrivateKey, PublicKey, SealedBox


def _validate_endpoint(ip: str, port: int) -> Tuple[str, int]:
    try:
        parsed = ipaddress.ip_address(str(ip).strip())
    except ValueError as exc:
        raise EndpointProtectionError("Axon endpoint must use a valid IP address") from exc
    if parsed.version != 4 or not parsed.is_global:
        raise EndpointProtectionError(
            "Encrypted Axon endpoints currently require a public IPv4 address"
        )
    if not 1 <= int(port) <= 65535:
        raise EndpointProtectionError("Axon endpoint port must be between 1 and 65535")
    return str(parsed), int(port)


def encrypt_endpoint(
    ip: str,
    port: int,
    public_key: bytes,
    hotkey: str,
) -> bytes:
    """Encrypt a hotkey-bound endpoint using a NaCl sealed box."""
    ip, port = _validate_endpoint(ip, port)
    _, _, PublicKey, SealedBox = _load_nacl()
    plaintext = f"{hotkey}|{ip}:{port}".encode("utf-8")
    ciphertext = SealedBox(PublicKey(public_key)).encrypt(plaintext)
    if len(ciphertext) > MAX_COMMITMENT_BYTES:
        raise EndpointProtectionError(
            f"Encrypted endpoint exceeds the {MAX_COMMITMENT_BYTES}-byte chain limit"
        )
    return ciphertext


def decrypt_endpoint(
    ciphertext: bytes,
    private_key: bytes,
    expected_hotkey: str,
) -> Tuple[str, int]:
    """Decrypt an endpoint and reject commitments copied across hotkeys."""
    _, PrivateKey, _, SealedBox = _load_nacl()
    try:
        plaintext = SealedBox(PrivateKey(private_key)).decrypt(ciphertext).decode("utf-8")
    except Exception as exc:
        raise EndpointProtectionError("Endpoint commitment could not be decrypted") from exc

    if "|" not in plaintext:
        raise EndpointProtectionError("Endpoint commitment has an invalid format")
    committed_hotkey, endpoint = plaintext.split("|", 1)
    if committed_hotkey != expected_hotkey:
        raise EndpointProtectionError("Endpoint commitment hotkey does not match its owner")
    try:
        ip, port_text = endpoint.rsplit(":", 1)
        port = int(port_text)
    except (ValueError, TypeError) as exc:
        raise EndpointProtectionError("Endpoint commitment has an invalid endpoint") from exc
    return _validate_endpoint(ip, port)


def publish_endpoint_commitment(
    subtensor: Any,
    wallet: Any,
    netuid: int,
    ciphertext: bytes,
) -> bool:
    """Publish encrypted endpoint metadata without masking on failure."""
    try:
        try:
            from bittensor.core.extrinsics.serving import (
                publish_metadata_extrinsic as publish_metadata,
            )
        except ImportError:
            from bittensor.core.extrinsics.serving import publish_metadata

        result = publish_metadata(
            subtensor=subtensor,
            wallet=wallet,
            netuid=int(netuid),
            data_type=f"Raw{len(ciphertext)}",
            data=ciphertext,
            wait_for_inclusion=True,
            wait_for_finalization=True,
        )
        if isinstance(result, tuple):
            return bool(result[0])
        if hasattr(result, "success"):
            return bool(result.success)
        return result is not False
    except Exception:
        return False


def _unwrap(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _raw_field_to_bytes(value: Any) -> Optional[bytes]:
    value = _unwrap(value)
    if isinstance(value, str):
        try:
            return bytes.fromhex(value[2:] if value.startswith("0x") else value)
        except ValueError:
            return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, (list, tuple)):
        inner = value
        if len(value) == 1 and isinstance(
            value[0], (list, tuple, bytes, bytearray, str)
        ):
            inner = value[0]
        if isinstance(inner, str):
            try:
                return bytes.fromhex(inner[2:] if inner.startswith("0x") else inner)
            except ValueError:
                return None
        try:
            return bytes(inner)
        except (TypeError, ValueError):
            return None
    return None


def extract_commitment_ciphertext(commitment_data: Any) -> Optional[bytes]:
    """Read RawN metadata across supported substrate decoding shapes."""
    try:
        data = _unwrap(commitment_data)
        entry = data["info"]["fields"][0]
        if isinstance(entry, (list, tuple)):
            entry = entry[0]
        raw_key = next(iter(entry))
        ciphertext = _raw_field_to_bytes(entry[raw_key])
        if ciphertext is None or len(ciphertext) > MAX_COMMITMENT_BYTES:
            return None
        return ciphertext
    except (KeyError, IndexError, TypeError, StopIteration):
        return None


def _commitment_block(commitment_data: Any) -> int:
    data = _unwrap(commitment_data)
    if hasattr(data, "get"):
        try:
            return int(data.get("block", 0) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _key_to_ss58(value: Any) -> str:
    value = _unwrap(value)
    if isinstance(value, str):
        return value

    raw = value
    if (
        isinstance(value, tuple)
        and len(value) == 1
        and isinstance(value[0], (tuple, list, bytes, bytearray))
    ):
        raw = value[0]
    try:
        raw_bytes = bytes(raw)
    except (TypeError, ValueError) as exc:
        raise EndpointProtectionError("Unsupported commitment account key") from exc

    try:
        from bittensor_wallet import Keypair
    except ImportError as exc:
        raise EndpointProtectionError("Bittensor wallet SS58 encoder is unavailable") from exc
    return Keypair(public_key=raw_bytes.hex(), ss58_format=42).ss58_address


@dataclass(frozen=True)
class EndpointRecord:
    block: int
    ip: str
    port: int


class ValidatorEndpointResolver:
    """Resolve opt-in encrypted endpoints while preserving public Axons."""

    def __init__(
        self,
        subtensor: Any,
        netuid: int,
        private_key_hex: str,
        refresh_seconds: float = 300.0,
    ):
        self.subtensor = subtensor
        self.netuid = int(netuid)
        self.private_key = (
            _decode_key(private_key_hex, PRIVATE_KEY_ENV)
            if private_key_hex.strip()
            else None
        )
        self.refresh_seconds = max(30.0, float(refresh_seconds))
        self._records: Dict[str, EndpointRecord] = {}
        self._last_refresh = 0.0

    @classmethod
    def from_env(cls, subtensor: Any, netuid: int) -> "ValidatorEndpointResolver":
        refresh_text = os.getenv(REFRESH_SECONDS_ENV, "300").strip()
        try:
            refresh_seconds = float(refresh_text)
        except ValueError:
            refresh_seconds = 300.0
        return cls(
            subtensor=subtensor,
            netuid=netuid,
            private_key_hex=os.getenv(PRIVATE_KEY_ENV, ""),
            refresh_seconds=refresh_seconds,
        )

    @property
    def enabled(self) -> bool:
        return self.private_key is not None

    @property
    def protected_hotkeys(self) -> frozenset[str]:
        return frozenset(self._records)

    def refresh(self, hotkeys: Iterable[str], force: bool = False) -> int:
        if not self.enabled:
            return 0
        now = time.monotonic()
        if not force and now - self._last_refresh < self.refresh_seconds:
            return len(self._records)
        self._last_refresh = now

        hotkey_set = {str(hotkey) for hotkey in hotkeys}
        try:
            rows = self.subtensor.query_map(
                module="Commitments",
                name="CommitmentOf",
                params=[self.netuid],
            )
        except Exception:
            return len(self._records)

        records: Dict[str, EndpointRecord] = {}
        for account_key, commitment_data in rows:
            try:
                hotkey = _key_to_ss58(account_key)
            except EndpointProtectionError:
                continue
            if hotkey not in hotkey_set:
                continue

            block = _commitment_block(commitment_data)
            cached = self._records.get(hotkey)
            if cached is not None and cached.block == block:
                records[hotkey] = cached
                continue

            ciphertext = extract_commitment_ciphertext(commitment_data)
            if ciphertext is None:
                continue
            try:
                ip, port = decrypt_endpoint(
                    ciphertext,
                    self.private_key,
                    expected_hotkey=hotkey,
                )
            except EndpointProtectionError:
                continue
            records[hotkey] = EndpointRecord(block=block, ip=ip, port=port)

        self._records = records
        return len(records)

    def resolve(self, hotkey: str, axon: Any) -> Tuple[Any, bool]:
        if not is_masked_axon(axon):
            return axon, False
        record = self._records.get(str(hotkey))
        if record is None:
            return axon, False
        try:
            resolved = replace(axon, ip=record.ip, port=record.port)
        except (TypeError, ValueError):
            resolved = copy.copy(axon)
            resolved.ip = record.ip
            resolved.port = record.port
        return resolved, True


def is_masked_axon(axon: Any) -> bool:
    return (
        str(getattr(axon, "ip", "") or "") == MASKED_AXON_IP
        and int(getattr(axon, "port", 0) or 0) == MASKED_AXON_PORT
    )


def _miner_external_endpoint(axon: Any) -> Tuple[str, int]:
    ip = os.getenv(EXTERNAL_IP_ENV, "").strip()
    if not ip:
        ip = str(
            getattr(axon, "external_ip", None)
            or getattr(axon, "ip", "")
            or ""
        ).strip()

    port_text = os.getenv(EXTERNAL_PORT_ENV, "").strip()
    if port_text:
        try:
            port = int(port_text)
        except ValueError as exc:
            raise EndpointProtectionError(
                f"{EXTERNAL_PORT_ENV} must be an integer"
            ) from exc
    else:
        port = int(
            getattr(axon, "external_port", None)
            or getattr(axon, "port", 0)
            or 0
        )
    return _validate_endpoint(ip, port)


def enable_miner_endpoint_protection(miner: Any) -> bool:
    """Publish the real endpoint and mask it only after confirmed publication."""
    if not _env_enabled(PROTECTION_ENABLED_ENV):
        return False

    netuid = int(miner.config.netuid)
    public_key_hex = os.getenv(PUBLIC_KEY_ENV, "").strip()
    if not public_key_hex:
        public_key_hex = DEFAULT_PUBLIC_KEYS.get(netuid, "")
    if not public_key_hex:
        raise EndpointProtectionError(
            f"No encrypted endpoint public key is configured for netuid {netuid}"
        )

    public_key = _decode_key(public_key_hex, PUBLIC_KEY_ENV)
    ip, port = _miner_external_endpoint(miner.axon)
    hotkey = miner.wallet.hotkey.ss58_address
    ciphertext = encrypt_endpoint(ip, port, public_key, hotkey)
    published = publish_endpoint_commitment(
        subtensor=miner.subtensor,
        wallet=miner.wallet,
        netuid=netuid,
        ciphertext=ciphertext,
    )
    if not published:
        return False

    miner.axon.external_ip = MASKED_AXON_IP
    miner.axon.external_port = MASKED_AXON_PORT
    return True
