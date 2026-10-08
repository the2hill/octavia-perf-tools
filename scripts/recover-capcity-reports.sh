#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-$ROOT/.venv/bin/python}"
REPORT="$ROOT/scripts/report.py"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: Python not found: $PY" >&2
  exit 1
fi
if [[ ! -f "$REPORT" ]]; then
  echo "ERROR: report.py not found: $REPORT" >&2
  exit 1
fi

found=0
recovered=0
failed=0

for dir in "$ROOT"/results/*_max_connections_active-*-octavia-r*; do
  [[ -d "$dir" ]] || continue
  [[ -d "$dir/raw" ]] || continue
  compgen -G "$dir/raw/*/connection-capacity-*.csv" >/dev/null || continue

  found=$((found + 1))
  echo
  echo "==> $(basename "$dir")"

  if "$PY" "$REPORT" "$dir"; then
    recovered=$((recovered + 1))
    if [[ -f "$dir/RUN_FAILED.yml" ]] && grep -q '^stage: report$' "$dir/RUN_FAILED.yml"; then
      mv -f "$dir/RUN_FAILED.yml" "$dir/REPORT_FAILED.recovered.yml"
    fi
    rm -f "$dir/REPORT_FAILED.yml"
    printf 'recovered_at_utc: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      > "$dir/REPORT_RECOVERED.yml"
  else
    failed=$((failed + 1))
    echo "WARNING: report regeneration still failed for $(basename "$dir")" >&2
  fi
done

echo
echo "Capacity result directories found: $found"
echo "Reports recovered:               $recovered"
echo "Still failing:                   $failed"

if (( recovered > 0 )); then
  echo
  echo "Rebuild the connection comparison with:"
  cat <<'CMD'
.venv/bin/python scripts/compare_campaigns.py results \
  --latest-per-group 1 \
  --scenario http_max_connections_active \
  --scenario tls_passthrough_max_connections_active \
  --scenario tls_termination_max_connections_active \
  --scenario tls_termination_reencrypt_max_connections_active
CMD
fi

(( failed == 0 ))
