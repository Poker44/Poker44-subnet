#!/usr/bin/env bash

# Move known former defaults to the current protocol allocation. The exact
# legacy 0.30 value is migrated even when an earlier release persisted it in
# .env; unrelated custom allocations remain authoritative.
migrate_transition_burn_default() {
  local env_file="${1:-}"
  if [ -n "$env_file" ] && [ -f "$env_file" ] && \
    grep -Eq \
      '^[[:space:]]*(export[[:space:]]+)?POKER44_BURN_FRACTION=[[:space:]]*(0\.30|"0\.30"|'"'"'0\.30'"'"')[[:space:]]*$' \
      "$env_file"; then
    sed -i -E \
      's/^([[:space:]]*(export[[:space:]]+)?POKER44_BURN_FRACTION=)[[:space:]]*(0\.30|"0\.30"|'"'"'0\.30'"'"')[[:space:]]*$/\10.00/' \
      "$env_file"
    chmod 600 "$env_file"
    export POKER44_BURN_FRACTION="0.00"
    echo "[INFO] Migrated persisted legacy burn allocation to 0.00"
    return 0
  fi
  if [ -n "$env_file" ] && [ -f "$env_file" ] && \
    grep -Eq '^[[:space:]]*(export[[:space:]]+)?POKER44_BURN_FRACTION=' "$env_file"; then
    return 0
  fi
  case "${POKER44_BURN_FRACTION:-}" in
    0.90|0.70|0.30)
      export POKER44_BURN_FRACTION="0.00"
      echo "[INFO] Migrated inherited burn default to 0.00"
      ;;
  esac
}
