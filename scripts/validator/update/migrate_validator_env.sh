#!/usr/bin/env bash

# Move only known former runner-provided defaults. An explicit operator value
# in .env remains authoritative.
migrate_transition_burn_default() {
  local env_file="${1:-}"
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
