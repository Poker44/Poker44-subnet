#!/usr/bin/env bash
set -euo pipefail

NETUID="${NETUID:-126}"
NETWORK="${NETWORK:-finney}"
WALLET_NAME="${WALLET_NAME:-poker44-validator}"
HOTKEY="${HOTKEY:-validator}"
WALLET_PATH="${WALLET_PATH:-}"
PM2_NAME="${PM2_NAME:-poker44-validator}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VALIDATOR_SCRIPT="${VALIDATOR_SCRIPT:-./neurons/validator.py}"
NEURON_TIMEOUT="${NEURON_TIMEOUT:-180}"
VALIDATOR_EXTRA_ARGS="${VALIDATOR_EXTRA_ARGS:-}"

: "${POKER44_SUBNET_DATA_URL:=https://api.poker44.net}"
: "${POKER44_DASHBOARD_REPORT_URL:=https://api.poker44.net/api/v1/validator-events}"
: "${POKER44_VALIDATOR_SESSIONS_PER_ROUND:=64}"
: "${POKER44_POLL_INTERVAL_SECONDS:=300}"
: "${POKER44_MINERS_PER_ROUND:=32}"
: "${POKER44_ENDPOINT_PRIVATE_KEY:=}"
: "${POKER44_ENDPOINT_PRIVATE_KEY_FILE:=}"
: "${POKER44_ENDPOINT_REFRESH_SECONDS:=300}"
: "${POKER44_ENDPOINT_AUTO_PROVISION:=true}"
: "${POKER44_ENDPOINT_PROVISIONING_URL:=https://api.poker44.net/internal/validators/runtime/endpoint-key}"
: "${POKER44_ENDPOINT_CACHE_FILE:=}"
export POKER44_SUBNET_DATA_URL POKER44_DASHBOARD_REPORT_URL
export POKER44_VALIDATOR_SESSIONS_PER_ROUND POKER44_POLL_INTERVAL_SECONDS
export POKER44_MINERS_PER_ROUND
export POKER44_ENDPOINT_PRIVATE_KEY POKER44_ENDPOINT_PRIVATE_KEY_FILE
export POKER44_ENDPOINT_REFRESH_SECONDS POKER44_ENDPOINT_AUTO_PROVISION
export POKER44_ENDPOINT_PROVISIONING_URL POKER44_ENDPOINT_CACHE_FILE

command -v pm2 >/dev/null || { echo "pm2 is required" >&2; exit 1; }
test -f "$VALIDATOR_SCRIPT" || { echo "Missing $VALIDATOR_SCRIPT" >&2; exit 1; }
"$PYTHON_BIN" -c 'import bittensor, dotenv, nacl, numpy, sklearn, poker44' || {
  echo "Install the Poker44 runtime dependencies first" >&2; exit 1;
}

args=(
  "$VALIDATOR_SCRIPT"
  --netuid "$NETUID"
  --subtensor.network "$NETWORK"
  --wallet.name "$WALLET_NAME"
  --wallet.hotkey "$HOTKEY"
  --neuron.timeout "$NEURON_TIMEOUT"
  --neuron.num_concurrent_forwards 1
  --logging.info
)
if [[ -n "$WALLET_PATH" ]]; then args+=(--wallet.path "$WALLET_PATH"); fi
if [[ -n "$VALIDATOR_EXTRA_ARGS" ]]; then
  read -r -a extra <<< "$VALIDATOR_EXTRA_ARGS"
  args+=("${extra[@]}")
fi

pm2 delete "$PM2_NAME" >/dev/null 2>&1 || true
pm2 start "$PYTHON_BIN" --name "$PM2_NAME" -- "${args[@]}"
pm2 save
echo "Started $PM2_NAME on netuid=$NETUID with $WALLET_NAME/$HOTKEY"
if [[ -n "$POKER44_ENDPOINT_PRIVATE_KEY" || -n "$POKER44_ENDPOINT_PRIVATE_KEY_FILE" ]]; then
  echo "Encrypted Axon endpoint resolver: enabled"
elif [[ "$POKER44_ENDPOINT_AUTO_PROVISION" == "true" ]]; then
  echo "Encrypted Axon endpoint resolver: automatic signed provisioning enabled"
else
  echo "Encrypted Axon endpoint resolver: disabled"
fi
