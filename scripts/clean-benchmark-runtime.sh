#!/usr/bin/env bash
set -u -o pipefail

CONFIG="config/local.yml"
LOCAL_ONLY=0
DESTROY_CAMPAIGN_LBS=0
REMOTE_TIMEOUT=90

usage() {
    cat <<'EOF'
Usage:
  cleanup-benchmark-runtime.sh [options]

Options:
  --config FILE              Config file (default: config/local.yml)
  --local-only               Only clean controller-side processes
  --destroy-campaign-lbs     Also delete persistent campaign load balancers
  --remote-timeout SECONDS   Timeout for remote cleanup commands (default: 90)
  -h, --help                 Show this help

Default behavior:
  - Stop local benchmark.py and harness ansible-playbook processes
  - Stop benchmark-related outbound SSH / Ansible mux processes
  - Kill remote connection_capacity.py, Locust and metrics samplers
  - Clean the currently configured Octavia scenario
  - Preserve persistent campaign LBs
  - Preserve benchmark VM/network infrastructure
  - Preserve results
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --local-only)
            LOCAL_ONLY=1
            shift
            ;;
        --destroy-campaign-lbs)
            DESTROY_CAMPAIGN_LBS=1
            shift
            ;;
        --remote-timeout)
            REMOTE_TIMEOUT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "$ROOT"

PY="$ROOT/.venv/bin/python"
ANSIBLE="$ROOT/.venv/bin/ansible"
ANSIBLE_PLAYBOOK="$ROOT/.venv/bin/ansible-playbook"
INVENTORY="$ROOT/state/inventory.ini"
CURRENT_TARGET="$ROOT/state/current_target.yml"
CONTROL_DIR="${HOME}/.ansible/cp"

if [[ ! -f "$CONFIG" ]]; then
    echo "ERROR: config not found: $CONFIG" >&2
    exit 1
fi

echo "============================================================"
echo " Octavia performance runtime cleanup"
echo "============================================================"
echo "repo:               $ROOT"
echo "config:             $CONFIG"
echo "local only:         $LOCAL_ONLY"
echo "destroy campaign:   $DESTROY_CAMPAIGN_LBS"
echo

stop_pattern() {
    local pattern="$1"
    local label="$2"
    local first_signal="${3:-TERM}"
    local grace="${4:-3}"

    mapfile -t pids < <(
        pgrep -u "$(id -u)" -f "$pattern" 2>/dev/null || true
    )

    if [[ ${#pids[@]} -eq 0 ]]; then
        echo "No local ${label} processes found."
        return 0
    fi

    echo "Stopping local ${label}: ${pids[*]}"
    kill -s "$first_signal" "${pids[@]}" 2>/dev/null || true

    sleep "$grace"

    local remaining=()
    local pid
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            remaining+=("$pid")
        fi
    done

    if [[ ${#remaining[@]} -gt 0 ]]; then
        echo "Sending TERM to remaining ${label}: ${remaining[*]}"
        kill -TERM "${remaining[@]}" 2>/dev/null || true
        sleep 2
    fi

    remaining=()
    for pid in "${pids[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            remaining+=("$pid")
        fi
    done

    if [[ ${#remaining[@]} -gt 0 ]]; then
        echo "Sending KILL to remaining ${label}: ${remaining[*]}"
        kill -KILL "${remaining[@]}" 2>/dev/null || true
    fi
}

echo
echo "---- Local process cleanup ----"

# Give benchmark.py a chance to execute its Python cleanup/finally paths.
stop_pattern 'scripts/benchmark[.]py' \
    "benchmark.py" INT 5

# Catch run_test.yml or other harness playbooks left behind by benchmark.py.
stop_pattern "${ROOT}/.venv/bin/ansible-playbook" \
    "Ansible playbook" TERM 3

# Outbound benchmark SSH sessions using the harness key.
stop_pattern 'ssh .*octavia-perf-ed25519' \
    "benchmark SSH" TERM 2

# Ansible ControlMaster processes.
stop_pattern 'ssh: .*/\.ansible/cp/.*\[mux\]' \
    "Ansible SSH mux" TERM 2

if [[ -d "$CONTROL_DIR" ]]; then
    echo "Removing Ansible control sockets from $CONTROL_DIR"
    rm -f "$CONTROL_DIR"/* 2>/dev/null || true
fi

if (( LOCAL_ONLY )); then
    echo
    echo "Local cleanup complete."
    echo "Remote benchmark processes/resources were left untouched."
    exit 0
fi

if [[ ! -x "$ANSIBLE" ]]; then
    echo "WARNING: Ansible binary not found: $ANSIBLE"
    echo "Skipping remote process cleanup."
else
    echo
    echo "---- Remote benchmark process cleanup ----"

    remote_cleanup() {
        local group="$1"
        local command="$2"
        local label="$3"

        echo "Cleaning ${label} on ${group}..."

        if ! timeout "${REMOTE_TIMEOUT}s" \
            "$ANSIBLE" "$group" \
            -i "$INVENTORY" \
            -b \
            -m shell \
            -a "$command"
        then
            echo "WARNING: ${label} cleanup failed/timed out on ${group}."
        fi
    }

    if [[ -f "$INVENTORY" ]]; then
        remote_cleanup \
            "locust_workers" \
            "pkill -TERM -f '[c]onnection_capacity.py' || true; pkill -TERM -f '[l]ocust.*--worker' || true" \
            "capacity/Locust workers"

        remote_cleanup \
            "master" \
            "pkill -TERM -f '[l]ocust.*--master' || true" \
            "Locust master"

        remote_cleanup \
            "benchmark_nodes" \
            "pkill -TERM -f '[m]etrics_sampler.py' || true" \
            "metrics samplers"
    else
        echo "WARNING: inventory missing: $INVENTORY"
        echo "Cannot clean remote benchmark processes."
    fi
fi

yaml_value() {
    local file="$1"
    local key="$2"

    "$PY" - "$file" "$key" <<'PY'
import pathlib
import sys
import yaml

path = pathlib.Path(sys.argv[1])
key = sys.argv[2]

if not path.exists():
    raise SystemExit(0)

data = yaml.safe_load(path.read_text()) or {}
value = data.get(key)

if value is None:
    print("")
elif isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

echo
echo "---- Current scenario cleanup ----"

if [[ -f "$CURRENT_TARGET" ]]; then
    FLAVOR="$(yaml_value "$CURRENT_TARGET" octavia_flavor)"
    SCENARIO="$(yaml_value "$CURRENT_TARGET" scenario_name)"
    CAMPAIGN_ID="$(yaml_value "$CURRENT_TARGET" campaign_id)"
    PERSISTENT="$(yaml_value "$CURRENT_TARGET" persistent_load_balancer)"

    echo "current flavor:   ${FLAVOR:-<none>}"
    echo "current scenario: ${SCENARIO:-<none>}"
    echo "campaign:         ${CAMPAIGN_ID:-<none>}"

    if [[ "$PERSISTENT" == "true" \
       && -n "$FLAVOR" \
       && -n "$SCENARIO" \
       && -n "$CAMPAIGN_ID" ]]; then

        echo "Removing current scenario child resources..."

        if ! timeout 300s \
            "$ANSIBLE_PLAYBOOK" \
            playbooks/destroy_campaign_lb_scenario.yml \
            -e "@$CONFIG" \
            -e "octavia_flavor=$FLAVOR" \
            -e "scenario_name=$SCENARIO" \
            -e "campaign_id=$CAMPAIGN_ID"
        then
            echo "WARNING: scenario cleanup failed or timed out."
            echo "You can rerun this script once connectivity is healthy."
        fi
    else
        echo "Current target is not a persistent Octavia scenario; skipping."
    fi
else
    echo "No state/current_target.yml found."
fi

if (( DESTROY_CAMPAIGN_LBS )); then
    echo
    echo "---- Persistent campaign LB cleanup ----"

    shopt -s nullglob
    campaign_files=(state/campaign_lb-*.yml)

    if [[ ${#campaign_files[@]} -eq 0 ]]; then
        echo "No persistent campaign LB state files found."
    fi

    for state_file in "${campaign_files[@]}"; do
        FLAVOR="$(yaml_value "$state_file" octavia_flavor)"
        CAMPAIGN_ID="$(yaml_value "$state_file" campaign_id)"

        if [[ -z "$FLAVOR" || -z "$CAMPAIGN_ID" ]]; then
            echo "WARNING: cannot identify campaign from $state_file"
            continue
        fi

        echo "Deleting campaign LB: flavor=$FLAVOR campaign=$CAMPAIGN_ID"

        if ! timeout 960s \
            "$ANSIBLE_PLAYBOOK" \
            playbooks/destroy_campaign_lb.yml \
            -e "@$CONFIG" \
            -e "octavia_flavor=$FLAVOR" \
            -e "campaign_id=$CAMPAIGN_ID"
        then
            echo "WARNING: failed to delete campaign LB for $FLAVOR"
            continue
        fi

        if [[ -x "$PY" && -f scripts/amphora_inventory.py ]]; then
            "$PY" scripts/amphora_inventory.py remove \
                --registry-file state/current_campaign_lbs.yml \
                --campaign-id "$CAMPAIGN_ID" \
                --octavia-flavor "$FLAVOR" \
                || true
        fi
    done
fi

echo
echo "---- Remaining local harness processes ----"

pgrep -af 'scripts/benchmark[.]py|ansible-playbook|octavia-perf-ed25519' \
    || echo "None."

echo
echo "Cleanup complete."
echo "Historical/partial results were preserved."
echo "Benchmark VM/network infrastructure was preserved."
