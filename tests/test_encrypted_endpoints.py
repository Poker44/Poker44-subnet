from types import SimpleNamespace

import pytest
from nacl.public import PrivateKey

from poker44.utils import encrypted_endpoints as endpoints


def _keypair():
    private_key = PrivateKey.generate()
    return bytes(private_key), bytes(private_key.public_key)


def _commitment_row(hotkey, ciphertext, block=1):
    return (
        hotkey,
        {
            "block": block,
            "info": {
                "fields": [
                    {
                        f"Raw{len(ciphertext)}": f"0x{ciphertext.hex()}",
                    }
                ]
            },
        },
    )


class FakeSubtensor:
    def __init__(self, rows):
        self.rows = rows
        self.fail = False

    def query_map(self, **kwargs):
        assert kwargs == {
            "module": "Commitments",
            "name": "CommitmentOf",
            "params": [126],
        }
        if self.fail:
            raise RuntimeError("temporary RPC failure")
        return list(self.rows)


def test_endpoint_round_trip_is_bound_to_hotkey():
    private_key, public_key = _keypair()
    ciphertext = endpoints.encrypt_endpoint(
        "1.1.1.1",
        8091,
        public_key,
        hotkey="miner-hotkey",
    )

    assert endpoints.decrypt_endpoint(
        ciphertext,
        private_key,
        expected_hotkey="miner-hotkey",
    ) == ("1.1.1.1", 8091)

    with pytest.raises(endpoints.EndpointProtectionError, match="hotkey"):
        endpoints.decrypt_endpoint(
            ciphertext,
            private_key,
            expected_hotkey="different-hotkey",
        )


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.1", "192.0.2.1", "not-an-ip"])
def test_endpoint_rejects_non_public_addresses(ip):
    _, public_key = _keypair()
    with pytest.raises(endpoints.EndpointProtectionError):
        endpoints.encrypt_endpoint(ip, 8091, public_key, hotkey="miner-hotkey")


def test_resolver_supports_mixed_public_and_protected_miners():
    private_key, public_key = _keypair()
    ciphertext = endpoints.encrypt_endpoint(
        "8.8.8.8",
        9001,
        public_key,
        hotkey="protected-hotkey",
    )
    subtensor = FakeSubtensor([_commitment_row("protected-hotkey", ciphertext, 42)])
    resolver = endpoints.ValidatorEndpointResolver(
        subtensor=subtensor,
        netuid=126,
        private_key_hex=private_key.hex(),
    )

    assert resolver.refresh(["public-hotkey", "protected-hotkey"], force=True) == 1

    masked_axon = SimpleNamespace(
        ip=endpoints.MASKED_AXON_IP,
        port=endpoints.MASKED_AXON_PORT,
    )
    resolved_axon, resolved = resolver.resolve("protected-hotkey", masked_axon)
    assert resolved is True
    assert (resolved_axon.ip, resolved_axon.port) == ("8.8.8.8", 9001)
    assert (masked_axon.ip, masked_axon.port) == (
        endpoints.MASKED_AXON_IP,
        endpoints.MASKED_AXON_PORT,
    )

    public_axon = SimpleNamespace(ip="9.9.9.9", port=9002)
    unchanged_axon, resolved = resolver.resolve("public-hotkey", public_axon)
    assert resolved is False
    assert unchanged_axon is public_axon


def test_resolver_rejects_commitment_copied_to_another_hotkey():
    private_key, public_key = _keypair()
    ciphertext = endpoints.encrypt_endpoint(
        "8.8.4.4",
        9001,
        public_key,
        hotkey="miner-a",
    )
    subtensor = FakeSubtensor(
        [
            _commitment_row("miner-a", ciphertext),
            _commitment_row("miner-b", ciphertext),
        ]
    )
    resolver = endpoints.ValidatorEndpointResolver(
        subtensor=subtensor,
        netuid=126,
        private_key_hex=private_key.hex(),
    )

    assert resolver.refresh(["miner-a", "miner-b"], force=True) == 1
    assert resolver.protected_hotkeys == frozenset({"miner-a"})


def test_resolver_ignores_stale_commitment_for_public_axon():
    private_key, public_key = _keypair()
    ciphertext = endpoints.encrypt_endpoint(
        "8.8.4.4",
        9001,
        public_key,
        hotkey="miner-a",
    )
    subtensor = FakeSubtensor([_commitment_row("miner-a", ciphertext)])
    resolver = endpoints.ValidatorEndpointResolver(
        subtensor=subtensor,
        netuid=126,
        private_key_hex=private_key.hex(),
    )
    assert resolver.refresh(["miner-a"], force=True) == 1

    public_axon = SimpleNamespace(ip="9.9.9.9", port=9002)
    resolved_axon, resolved = resolver.resolve("miner-a", public_axon)

    assert resolved is False
    assert resolved_axon is public_axon


def test_commitment_account_bytes_are_normalized_to_ss58():
    from bittensor_wallet import Keypair

    raw_hotkey = bytes(range(32))
    expected = Keypair(public_key=raw_hotkey.hex(), ss58_format=42).ss58_address
    assert endpoints._key_to_ss58((tuple(raw_hotkey),)) == expected


def test_resolver_keeps_last_valid_state_during_rpc_failure():
    private_key, public_key = _keypair()
    ciphertext = endpoints.encrypt_endpoint(
        "1.0.0.1",
        9001,
        public_key,
        hotkey="miner-a",
    )
    subtensor = FakeSubtensor([_commitment_row("miner-a", ciphertext)])
    resolver = endpoints.ValidatorEndpointResolver(
        subtensor=subtensor,
        netuid=126,
        private_key_hex=private_key.hex(),
    )
    assert resolver.refresh(["miner-a"], force=True) == 1

    subtensor.fail = True
    assert resolver.refresh(["miner-a"], force=True) == 1
    assert resolver.protected_hotkeys == frozenset({"miner-a"})


def test_miner_masks_only_after_confirmed_publication(monkeypatch):
    private_key, public_key = _keypair()
    _ = private_key
    miner = SimpleNamespace(
        config=SimpleNamespace(netuid=126),
        axon=SimpleNamespace(
            ip="8.8.8.8",
            port=8091,
            external_ip="8.8.8.8",
            external_port=8091,
        ),
        wallet=SimpleNamespace(
            hotkey=SimpleNamespace(ss58_address="miner-hotkey"),
        ),
        subtensor=object(),
    )
    monkeypatch.setenv(endpoints.PROTECTION_ENABLED_ENV, "true")
    monkeypatch.setenv(endpoints.PUBLIC_KEY_ENV, public_key.hex())

    monkeypatch.setattr(endpoints, "publish_endpoint_commitment", lambda **_: False)
    assert endpoints.enable_miner_endpoint_protection(miner) is False
    assert (miner.axon.external_ip, miner.axon.external_port) == ("8.8.8.8", 8091)

    monkeypatch.setattr(endpoints, "publish_endpoint_commitment", lambda **_: True)
    assert endpoints.enable_miner_endpoint_protection(miner) is True
    assert (miner.axon.external_ip, miner.axon.external_port) == (
        endpoints.MASKED_AXON_IP,
        endpoints.MASKED_AXON_PORT,
    )


def test_disabled_miner_does_not_publish(monkeypatch):
    monkeypatch.delenv(endpoints.PROTECTION_ENABLED_ENV, raising=False)
    assert endpoints.enable_miner_endpoint_protection(SimpleNamespace()) is False


def test_publish_uses_extrinsic_success_flag(monkeypatch):
    from bittensor.core.extrinsics import serving

    response = SimpleNamespace(success=False)
    monkeypatch.setattr(
        serving,
        "publish_metadata_extrinsic",
        lambda **_: response,
    )
    assert endpoints.publish_endpoint_commitment(
        subtensor=object(),
        wallet=object(),
        netuid=126,
        ciphertext=b"ciphertext",
    ) is False

    response.success = True
    assert endpoints.publish_endpoint_commitment(
        subtensor=object(),
        wallet=object(),
        netuid=126,
        ciphertext=b"ciphertext",
    ) is True


def test_candidate_selection_uses_resolved_endpoint(monkeypatch):
    from poker44.validator.evaluation.mixin import ValidatorEvaluationMixin

    public_axon = SimpleNamespace(ip="9.9.9.9", port=9002)
    masked_axon = SimpleNamespace(
        ip=endpoints.MASKED_AXON_IP,
        port=endpoints.MASKED_AXON_PORT,
    )

    class FakeResolver:
        def resolve(self, hotkey, axon):
            if hotkey == "protected-hotkey":
                return SimpleNamespace(ip="8.8.8.8", port=9001), True
            return axon, False

    class Validator(ValidatorEvaluationMixin):
        pass

    validator = Validator()
    validator.uid = 0
    validator.wallet = SimpleNamespace(
        hotkey=SimpleNamespace(ss58_address="validator-hotkey")
    )
    validator.metagraph = SimpleNamespace(
            axons=[
                SimpleNamespace(ip="0.0.0.0", port=0),
                masked_axon,
                public_axon,
            ],
            hotkeys=["uid-zero", "protected-hotkey", "public-hotkey"],
            S=[0.0, 0.0, 0.0],
            validator_permit=[False, False, False],
    )
    validator.endpoint_resolver = FakeResolver()
    validator.refresh_encrypted_endpoints = lambda: 1
    monkeypatch.setenv("POKER44_MINERS_PER_ROUND", "32")

    uids, axons = validator._candidate_miners("window-1")

    assert set(uids) == {1, 2}
    resolved = {uid: (axon.ip, axon.port) for uid, axon in zip(uids, axons)}
    assert resolved == {1: ("8.8.8.8", 9001), 2: ("9.9.9.9", 9002)}
