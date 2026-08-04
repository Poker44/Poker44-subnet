#!/usr/bin/env bash

# Move only the former runner-provided default. An explicit operator value in
# .env, or any custom process value, remains authoritative.
migrate_transition_burn_default() {
  local env_file="${1:-}"
  if [ "${POKER44_BURN_FRACTION:-}" != "0.90" ]; then
    return 0
  fi
  if [ -n "$env_file" ] && [ -f "$env_file" ] && \
    grep -Eq '^[[:space:]]*(export[[:space:]]+)?POKER44_BURN_FRACTION=' "$env_file"; then
    return 0
  fi
  export POKER44_BURN_FRACTION="0.70"
  echo "[INFO] Migrated inherited burn default from 0.90 to 0.70"
}
