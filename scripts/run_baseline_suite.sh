#!/usr/bin/env bash
set -Eeuo pipefail

# Octavia performance baseline runbook.
#
# Default:
#   - preserve results/
#   - destroy current test infrastructure
#   - clear generated state only
#   - provision and configure a fresh environment
#   - verify connectivity/backend HTTP
#   - run the canonical amphora-default baseline suite
#
# Optional overrides:
#   CONFIG=config/local.yml FLAVOR=amphora-default REPETITIONS=3 ./scripts/run_baseline_suite.sh
#
# To skip teardown/rebuild and only run benchmarks:
#   REBUILD=0 ./scripts/run_baseline_suite.sh

CONFIG="${CONFIG:-config/local.yml}"
FLAVOR="${FLAVOR:-amphora-default}"
REPETITIONS="${REPETITIONS:-3}"
REBUILD="${REBUILD:-1}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-${REPO_ROOT}/.venv/bin/python}"
ANSIBLE="${ANSIBLE:-${REPO_ROOT}/.venv/bin/ansible}"

mkdir -p results
RUNBOOK_TS="$(date -u +%Y%m%dT%H%M%SZ)"
RUNBOOK_LOG="results/baseline-suite-${RUNBOOK_TS}.log"
exec > >(tee -a "${RUNBOOK_LOG}") 2>&1

trap 'rc=$?; echo; echo "ERROR: baseline runbook failed at line ${LINENO} (rc=${rc})"; echo "Log: ${RUNBOOK_LOG}"; exit "${rc}"' ERR

banner() {
  echo
  echo "======================================================================"
  echo "$*"
  echo "======================================================================"
}

require_file() {
  if [[ ! -f "$1" ]]; then
    echo "ERROR: required file not found: $1" >&2
    exit 1
  fi
}

require_executable() {
  if [[ ! -x "$1" ]]; then
    echo "ERROR: required executable not found: $1" >&2
    exit 1
  fi
}

require_file "${CONFIG}"
require_file "scripts/benchmark.py"
require_executable "${PYTHON}"
require_executable "${ANSIBLE}"

banner "Baseline configuration"
echo "repo:        ${REPO_ROOT}"
echo "config:      ${CONFIG}"
echo "flavor:      ${FLAVOR}"
echo "repetitions: ${REPETITIONS}"
echo "rebuild:     ${REBUILD}"
echo "log:         ${RUNBOOK_LOG}"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "git commit:  $(git rev-parse HEAD)"
  if [[ -n "$(git status --short)" ]]; then
    echo
    echo "WARNING: repository has uncommitted changes:"
    git status --short
  fi
fi

if command -v sha256sum >/dev/null 2>&1; then
  echo "config sha:  $(sha256sum "${CONFIG}" | awk '{print $1}')"
fi

banner "Validate canonical baseline settings"

"${PYTHON}" - "${CONFIG}" <<'PY'
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:
    raise SystemExit(f"ERROR: PyYAML is required for baseline validation: {exc}")

path = Path(sys.argv[1])
cfg = yaml.safe_load(path.read_text()) or {}

errors = []

stages = (cfg.get("locust") or {}).get("stages") or []
if not stages:
    errors.append("locust.stages is missing or empty")
else:
    final = stages[-1] or {}
    if final.get("users") != 8000:
        errors.append(f"final locust stage users={final.get('users')!r}; expected 8000")
    if final.get("spawn_rate") != 1000:
        errors.append(
            f"final locust stage spawn_rate={final.get('spawn_rate')!r}; "
            "expected 1000 (restore diagnostic 250/500/750 changes)"
        )

start_users = (cfg.get("max_rps") or {}).get("start_users")
if start_users != 500:
    errors.append(
        f"max_rps.start_users={start_users!r}; expected 500 for the canonical baseline"
    )

if errors:
    print("ERROR: config does not match the canonical baseline:")
    for error in errors:
        print(f"  - {error}")
    raise SystemExit(2)

print("Canonical settings OK:")
print("  final Locust stage: 8000 users @ 1000 users/sec")
print("  max_rps.start_users: 500")
PY

if [[ "${REBUILD}" == "1" ]]; then
  banner "Destroy existing test infrastructure"
  make destroy CONFIG="${CONFIG}"

  banner "Reset generated state (results are preserved)"
  rm -rf state/*
  touch state/.gitkeep

  banner "Provision fresh test infrastructure"
  make provision CONFIG="${CONFIG}"

  banner "Configure fresh test infrastructure"
  make configure CONFIG="${CONFIG}"

  banner "Verify Ansible connectivity"
  "${ANSIBLE}" all -m ping

  banner "Verify backend HTTP service"
  "${ANSIBLE}" backends -b -m shell -a     'curl -sf http://127.0.0.1:80/1024.bin >/dev/null && echo HTTP-OK'
else
  banner "REBUILD=0: skipping destroy/provision/configure"
fi

SCENARIOS=(
  http_1k_keepalive
  http_1k_max_rps
  http_1k_connection_churn
  tls_passthrough_1k_keepalive
  tls_passthrough_1k_connection_churn
  tls_passthrough_1k_max_rps
  tls_termination_1k_keepalive
  tls_termination_1k_connection_churn
  tls_termination_1k_max_rps
)

banner "Start baseline benchmark suite"

completed=0
for scenario in "${SCENARIOS[@]}"; do
  banner "Benchmark $((completed + 1))/${#SCENARIOS[@]}: ${scenario}"

  "${PYTHON}" scripts/benchmark.py     --config "${CONFIG}"     --flavor "${FLAVOR}"     --scenario "${scenario}"     --repetitions "${REPETITIONS}"

  completed=$((completed + 1))
  echo "Completed: ${scenario}"
done

banner "Baseline suite complete"
echo "Completed ${completed}/${#SCENARIOS[@]} scenarios."
echo "Results directory: ${REPO_ROOT}/results"
echo "Runbook log:       ${REPO_ROOT}/${RUNBOOK_LOG}"

echo
echo "Newest result directories:"
find results -maxdepth 1 -mindepth 1 -type d -printf '%T@ %p\n'   | sort -nr   | head -30   | cut -d' ' -f2-
