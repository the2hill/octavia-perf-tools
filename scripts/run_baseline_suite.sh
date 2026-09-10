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
#   - collect direct controls once
#   - create one persistent Octavia LB/amphora for the selected flavor
#   - reuse that LB across all Octavia scenarios/repetitions
#   - delete the persistent LB when the Octavia phase completes
#
# Optional overrides:
#   CONFIG=config/local.yml FLAVOR=amphora-default REPETITIONS=3 ./scripts/run_baseline_suite.sh
#
# To skip teardown/rebuild and only run benchmarks:
#   REBUILD=0 ./scripts/run_baseline_suite.sh

CONFIG="${CONFIG:-config/local.yml}"
FLAVOR="${FLAVOR:-}"
REPETITIONS="${REPETITIONS:-3}"
REBUILD="${REBUILD:-1}"
LB_CREATE_ATTEMPTS="${LB_CREATE_ATTEMPTS:-3}"
LB_CREATE_RETRY_DELAY_SECONDS="${LB_CREATE_RETRY_DELAY_SECONDS:-30}"
PAUSE_AFTER_LB_CREATE="${PAUSE_AFTER_LB_CREATE:-0}"

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
require_file "scripts/lb_failure_diagnostics.py"
require_executable "${PYTHON}"
require_executable "${ANSIBLE}"

if [[ -z "${FLAVOR}" ]]; then
  FLAVOR="$(${PYTHON} - "${CONFIG}" <<'PYCFG'
import sys
from pathlib import Path
import yaml

cfg = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}
flavors = [str(x) for x in ((cfg.get("octavia") or {}).get("flavors") or [])]
if not flavors:
    raise SystemExit("ERROR: no Octavia flavor configured; set FLAVOR=... or octavia.flavors")
if len(flavors) > 1:
    raise SystemExit(
        "ERROR: config contains multiple Octavia flavors: " + ", ".join(flavors)
        + "; run one suite at a time with FLAVOR=<name>"
    )
print(flavors[0])
PYCFG
)"
fi

FLAVOR_SLUG="$(printf '%s' "${FLAVOR}" | sed -E 's/[^A-Za-z0-9_.-]+/-/g; s/^-+//; s/-+$//')"
SUITE_ID="${SUITE_ID:-${RUNBOOK_TS}-${FLAVOR_SLUG}-$$}"

banner "Baseline configuration"
echo "repo:        ${REPO_ROOT}"
echo "config:      ${CONFIG}"
echo "flavor:      ${FLAVOR}"
echo "suite id:    ${SUITE_ID}"
echo "repetitions: ${REPETITIONS}"
echo "rebuild:     ${REBUILD}"
echo "lb attempts: ${LB_CREATE_ATTEMPTS}"
echo "lb retry:    ${LB_CREATE_RETRY_DELAY_SECONDS}s"
echo "reuse LB:    yes (one persistent LB/amphora for the Octavia phase)"
echo "pause after: ${PAUSE_AFTER_LB_CREATE}"
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

DIRECT_SCENARIOS=(
  http_1k_keepalive
  http_1k_max_rps
  tls_passthrough_1k_keepalive
  tls_passthrough_1k_max_rps
)

banner "Direct backend control phase (once per suite)"
echo "The reusable generator/backend fleet has not changed, so direct controls"
echo "are collected once here and are skipped during the Octavia scenario phase."

direct_args=(
  --config "${CONFIG}"
  --suite-id "${SUITE_ID}"
  --baseline-for-flavor "${FLAVOR}"
  --direct-baselines-only
  --continue-on-error
)
for scenario in "${DIRECT_SCENARIOS[@]}"; do
  direct_args+=(--scenario "${scenario}")
done

# Invoke benchmark.py once so each direct control is collected exactly once.
"${PYTHON}" scripts/benchmark.py "${direct_args[@]}"

banner "Start Octavia baseline benchmark suite using one persistent load balancer"
echo "The Octavia LB/amphora is created once for flavor ${FLAVOR}."
echo "Each scenario replaces only listener/pool/member/health-monitor resources as needed."
echo "The underlying LB/amphora is retained until the entire Octavia phase completes."

octavia_args=(
  --config "${CONFIG}"
  --suite-id "${SUITE_ID}"
  --flavor "${FLAVOR}"
  --skip-baseline
  --reuse-load-balancer
  --repetitions "${REPETITIONS}"
  --continue-on-error
  --lb-create-attempts "${LB_CREATE_ATTEMPTS}"
  --lb-create-retry-delay-seconds "${LB_CREATE_RETRY_DELAY_SECONDS}"
)
for scenario in "${SCENARIOS[@]}"; do
  octavia_args+=(--scenario "${scenario}")
done

if [[ "${PAUSE_AFTER_LB_CREATE}" == "1" ]]; then
  octavia_args+=(--pause-after-lb-create)
fi

"${PYTHON}" scripts/benchmark.py "${octavia_args[@]}"

banner "Baseline suite complete"
echo "Finished persistent-LB Octavia campaign containing ${#SCENARIOS[@]} scenarios."
echo "Results directory: ${REPO_ROOT}/results"
echo "Runbook log:       ${REPO_ROOT}/${RUNBOOK_LOG}"

echo
echo "Provisioning/run failures are preserved under individual result directories as:"
echo "  RUN_FAILED.yml"
echo "  orchestration/lb-create-attempt-XX.log"
echo "  orchestration/lb-create-attempt-XX-diagnostics.json"
echo "  orchestration/lb-create-attempt-XX-cleanup.log"
echo "  orchestration/lb-create-attempt-XX-post-cleanup.json"
echo "Campaign-level failure summaries are written as results/campaign-failures-*.yml."

echo
echo "Newest result directories:"
find results -maxdepth 1 -mindepth 1 -type d -printf '%T@ %p\n'   | sort -nr   | head -30   | cut -d' ' -f2-

