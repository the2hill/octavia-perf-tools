#!/usr/bin/env bash
set -Eeuo pipefail

# -----------------------------------------------------------------------------
# Rebuild the benchmark fleet and run the normal Octavia regression matrix.
#
# Flavor selection:
#   - FLAVORS unset/empty: use every flavor from octavia.flavors in CONFIG.
#   - FLAVORS set: run only the named flavors. Space- or comma-separated.
#
# Examples:
#   ./rebuild-and-benchmark.sh
#
#   FLAVORS="lb.lite_experimental lb.plus_experimental" \
#     ./rebuild-and-benchmark.sh
#
#   CONFIG=config/local.yml \
#   FLAVORS="lb.lite_experimental,lb.plus_experimental,lb.pro_experimental,lb.elite_experimental" \
#     ./rebuild-and-benchmark.sh
# -----------------------------------------------------------------------------

CONFIG="${CONFIG:-config/local.yml}"
FLAVORS_RAW="${FLAVORS:-}"

PYTHON="${PYTHON:-$PWD/.venv/bin/python}"
ANSIBLE="${ANSIBLE:-$PWD/.venv/bin/ansible}"

LB_CREATE_ATTEMPTS="${LB_CREATE_ATTEMPTS:-3}"
LB_CREATE_RETRY_DELAY_SECONDS="${LB_CREATE_RETRY_DELAY_SECONDS:-30}"

CORE_SCENARIOS=(
  http_1k_keepalive
  tls_passthrough_1k_keepalive
  tls_termination_1k_keepalive
  tls_termination_reencrypt_1k_keepalive
)

DIRECT_SCENARIOS=(
  http_1k_keepalive
  tls_passthrough_1k_keepalive
)

mkdir -p results
RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="results/rebuild-and-benchmark-${RUN_TS}.log"

exec > >(tee -a "$LOG") 2>&1

trap 'rc=$?; echo; echo "ERROR at line $LINENO rc=$rc"; echo "Log: $LOG"; exit $rc' ERR

banner() {
    echo
    echo "======================================================================"
    echo "$*"
    echo "======================================================================"
}

# Resolve the requested flavor list once, validate it against config, and expose
# it as a Bash array for benchmark.py and compare_campaigns.py.
mapfile -t SELECTED_FLAVORS < <(
  "$PYTHON" - "$CONFIG" "$FLAVORS_RAW" <<'PY'
import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1])
raw = sys.argv[2].strip()

cfg = yaml.safe_load(config_path.read_text()) or {}
configured = [str(x) for x in cfg["octavia"]["flavors"]]

if raw:
    requested = [x for x in raw.replace(",", " ").split() if x]
else:
    requested = configured

if not requested:
    raise SystemExit("No Octavia flavors selected or configured.")

unknown = [x for x in requested if x not in configured]
if unknown:
    raise SystemExit(
        "Selected flavor(s) are not present in octavia.flavors: "
        + ", ".join(unknown)
        + "\nConfigured flavors: "
        + ", ".join(configured)
    )

# Preserve caller order while removing accidental duplicates.
seen = set()
for flavor in requested:
    if flavor not in seen:
        print(flavor)
        seen.add(flavor)
PY
)

if [[ ${#SELECTED_FLAVORS[@]} -eq 0 ]]; then
    echo "ERROR: no flavors were selected."
    exit 1
fi

BENCHMARK_FLAVOR_ARGS=()
COMPARE_FLAVOR_ARGS=()
for flavor in "${SELECTED_FLAVORS[@]}"; do
    BENCHMARK_FLAVOR_ARGS+=(--flavor "$flavor")
    COMPARE_FLAVOR_ARGS+=(--flavor "$flavor")
done

SCENARIO_ARGS=()
COMPARE_SCENARIO_ARGS=()
for scenario in "${CORE_SCENARIOS[@]}"; do
    SCENARIO_ARGS+=(--scenario "$scenario")
    COMPARE_SCENARIO_ARGS+=(--scenario "$scenario")
done

DIRECT_SCENARIO_ARGS=()
for scenario in "${DIRECT_SCENARIOS[@]}"; do
    DIRECT_SCENARIO_ARGS+=(--scenario "$scenario")
done

CAMPAIGN_REPETITIONS="$(
  "$PYTHON" - "$CONFIG" <<'PY'
import sys
from pathlib import Path
import yaml

cfg = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}
print(int((cfg.get("campaign") or {}).get("repetitions", 1)))
PY
)"

REFERENCE_FLAVOR="${REFERENCE_FLAVOR:-${SELECTED_FLAVORS[0]}}"

reference_found=false
for flavor in "${SELECTED_FLAVORS[@]}"; do
    if [[ "$flavor" == "$REFERENCE_FLAVOR" ]]; then
        reference_found=true
        break
    fi
done

if [[ "$reference_found" != true ]]; then
    echo "ERROR: REFERENCE_FLAVOR '$REFERENCE_FLAVOR' is not in the selected flavor list."
    exit 1
fi

banner "CONFIGURATION"

echo "Config:            $CONFIG"
echo "Log:               $LOG"
echo "Reference flavor:  $REFERENCE_FLAVOR"
echo
echo "Selected Octavia flavors:"
printf '  %s\n' "${SELECTED_FLAVORS[@]}"

"$PYTHON" - "$CONFIG" <<'PY'
import sys
from pathlib import Path
import yaml

cfg = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}

print()
print("Reusable fleet:")
print(f"  backends:       {cfg['vm']['backend']['count']}")
print(f"  locust workers: {cfg['vm']['locust']['worker_vms']}")
print(f"  processes/vm:   {cfg['vm']['locust']['processes_per_vm']}")
print(f"  repetitions:    {cfg.get('campaign', {}).get('repetitions', 1)}")
PY


banner "CLEAN UP STALE OCTAVIA LOAD BALANCERS"

# state/ may have been deleted, so a previous persistent campaign LB cannot be
# discovered from current_campaign_lbs.yml. Clean all benchmark-owned LBs in
# this project by the configured run_prefix before destroying the fleet.

PYTHONPATH="$PWD/scripts" "$PYTHON" - "$CONFIG" <<'PY'
import sys
import time
from pathlib import Path

import yaml
from openstack_auth import connect

cfg = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}

cloud_cfg = cfg["openstack"]
conn = connect(
    cloud_cfg["cloud"],
    str(cloud_cfg.get("region_name") or "") or None,
)

prefix = str(cfg.get("run_prefix") or "octavia-perf") + "-"

lbs = [
    lb
    for lb in conn.load_balancer.load_balancers()
    if str(lb.name or "").startswith(prefix)
]

if not lbs:
    print("No benchmark-owned load balancers found.")
    raise SystemExit(0)

print(f"Found {len(lbs)} benchmark-owned load balancer(s):")
for lb in lbs:
    print(
        f"  {lb.name} "
        f"id={lb.id} "
        f"provisioning={getattr(lb, 'provisioning_status', None)}"
    )

for lb in lbs:
    print(f"Deleting LB with cascade: {lb.name}")
    try:
        conn.load_balancer.delete_load_balancer(
            lb,
            cascade=True,
            ignore_missing=True,
        )
    except TypeError:
        conn.load_balancer.delete_load_balancer(
            lb,
            ignore_missing=True,
            cascade=True,
        )

deadline = time.monotonic() + 900
while time.monotonic() < deadline:
    remaining = []
    for lb in lbs:
        obj = conn.load_balancer.find_load_balancer(
            lb.id,
            ignore_missing=True,
        )
        if obj is not None:
            remaining.append(obj)

    if not remaining:
        print("All benchmark-owned load balancers deleted.")
        break

    print(
        "Waiting for LB deletion: "
        + ", ".join(str(x.name) for x in remaining)
    )
    time.sleep(10)
else:
    raise SystemExit(
        "ERROR: benchmark load balancers still exist after 900 seconds"
    )
PY


banner "REMOVE ORPHANED CONTROLLER ROUTE TO OLD MASTER FIP"

# controller-fip-route.json may have been deleted, so discover the current
# master FIP before deleting the master and remove only that exact /32 route.

OLD_MASTER_FIP="$(
PYTHONPATH="$PWD/scripts" "$PYTHON" - "$CONFIG" <<'PY'
import sys
from pathlib import Path

import yaml
from openstack_auth import connect

cfg = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}
cloud_cfg = cfg["openstack"]

conn = connect(
    cloud_cfg["cloud"],
    str(cloud_cfg.get("region_name") or "") or None,
)

prefix = str(cfg.get("run_prefix") or "octavia-perf")
name = f"{prefix}-master"

server = conn.compute.find_server(name, ignore_missing=True)
if server is None:
    raise SystemExit(0)

server = conn.compute.get_server(server.id)

for entries in (server.addresses or {}).values():
    for entry in entries:
        if (
            entry.get("OS-EXT-IPS:type") == "floating"
            or entry.get("type") == "floating"
        ):
            print(entry["addr"])
            raise SystemExit(0)

ports = list(conn.network.ports(device_id=server.id))
port_ids = {str(port.id) for port in ports}

for fip in conn.network.ips():
    if str(fip.port_id or "") in port_ids:
        print(fip.floating_ip_address)
        raise SystemExit(0)
PY
)"

if [[ -n "${OLD_MASTER_FIP:-}" ]]; then
    echo "Old master FIP: $OLD_MASTER_FIP"

    OLD_ROUTE="$(
        ip -4 route show table main "${OLD_MASTER_FIP}/32" 2>/dev/null || true
    )"

    if [[ -n "$OLD_ROUTE" ]]; then
        echo "Removing orphaned exact route:"
        echo "  $OLD_ROUTE"
        sudo ip -4 route del "${OLD_MASTER_FIP}/32" || true
    else
        echo "No exact /32 route exists for old master."
    fi
else
    echo "No existing benchmark master/FIP found."
fi


banner "DESTROY EXISTING BENCHMARK INFRASTRUCTURE"

# destroy.yml removes the named workers/backends/master, FIP, server groups,
# security group, benchmark network/router resources and uploaded keypair.

make destroy CONFIG="$CONFIG"


banner "RESET GENERATED STATE"

# Preserve all historical results.
rm -rf state/*
mkdir -p state
touch state/.gitkeep

echo "results/ preserved."
echo "state/ reset."


banner "PROVISION FRESH BENCHMARK FLEET"

make provision CONFIG="$CONFIG"


banner "RECONCILE FRESH CONFIGURATION"

make configure CONFIG="$CONFIG"


banner "VERIFY NEW INVENTORY"

"$ANSIBLE" all --list-hosts
echo
"$ANSIBLE" backends --list-hosts
echo
"$ANSIBLE" locust_workers --list-hosts


banner "VERIFY SSH CONNECTIVITY"

"$ANSIBLE" all -m ping


banner "VERIFY BACKEND HTTP"

"$ANSIBLE" backends \
  -b \
  -m shell \
  -a 'curl -sf http://127.0.0.1:80/1024.bin >/dev/null && echo HTTP-OK'


banner "VERIFY GENERATOR CPU CAPACITY"

"$ANSIBLE" locust_workers \
  -m shell \
  -a 'echo "$(hostname) nproc=$(nproc)"'


banner "VERIFY EXPECTED FLEET SIZE"

"$PYTHON" - "$CONFIG" <<'PY'
import re
import subprocess
import sys
from pathlib import Path

import yaml

cfg = yaml.safe_load(Path(sys.argv[1]).read_text()) or {}
expected_backends = int(cfg["vm"]["backend"]["count"])
expected_workers = int(cfg["vm"]["locust"]["worker_vms"])
expected_masters = 1


def count(group):
    cp = subprocess.run(
        [".venv/bin/ansible", group, "--list-hosts"],
        text=True,
        capture_output=True,
        check=True,
    )

    match = re.search(r"hosts \((\d+)\)", cp.stdout)
    if not match:
        raise SystemExit(
            f"Unable to determine host count for {group}:\n{cp.stdout}"
        )

    return int(match.group(1))


backends = count("backends")
workers = count("locust_workers")
masters = count("master")

print(f"master:          {masters} expected={expected_masters}")
print(f"backends:       {backends} expected={expected_backends}")
print(f"locust workers: {workers} expected={expected_workers}")

if masters != expected_masters:
    raise SystemExit(
        f"Expected {expected_masters} master; found {masters}"
    )

if backends != expected_backends:
    raise SystemExit(
        f"Expected {expected_backends} backends; found {backends}"
    )

if workers != expected_workers:
    raise SystemExit(
        f"Expected {expected_workers} Locust workers; found {workers}"
    )
PY


banner "PHASE 1 - FRESH DIRECT-BACKEND CONTROLS"

# The backend/generator fleet was rebuilt, so collect fresh direct controls
# rather than comparing new Octavia runs against the previous backend fleet.

"$PYTHON" scripts/benchmark.py \
  --config "$CONFIG" \
  "${DIRECT_SCENARIO_ARGS[@]}" \
  --direct-baselines-only \
  --continue-on-error


banner "PHASE 2 - NORMAL CORE SCENARIOS, SELECTED FLAVORS"

# Uses campaign.repetitions from CONFIG.
#
# Core matrix:
#   HTTP
#   TLS passthrough
#   TLS termination
#   TLS termination + backend re-encryption
#
# --skip-baseline is intentional because Phase 1 already captured controls.
# One persistent Amphora is created per selected flavor and reused across its
# scenarios/repetitions.

"$PYTHON" scripts/benchmark.py \
  --config "$CONFIG" \
  "${BENCHMARK_FLAVOR_ARGS[@]}" \
  "${SCENARIO_ARGS[@]}" \
  --skip-baseline \
  --reuse-load-balancer \
  --continue-on-error \
  --lb-create-attempts "$LB_CREATE_ATTEMPTS" \
  --lb-create-retry-delay-seconds "$LB_CREATE_RETRY_DELAY_SECONDS"


banner "REGENERATE COMPARISON OUTPUTS"

# compare_campaigns.py is intentionally scoped to the selected flavors and the
# normal core scenarios. This prevents historical one-off/adaptive diagnostics
# from being pulled into the current regression report.
if [[ -f scripts/compare_campaigns.py ]]; then
    "$PYTHON" scripts/compare_campaigns.py results \
      "${COMPARE_FLAVOR_ARGS[@]}" \
      "${COMPARE_SCENARIO_ARGS[@]}" \
      --latest-per-group "$CAMPAIGN_REPETITIONS" \
      --latest-direct 1 \
      --reference-flavor "$REFERENCE_FLAVOR" \
      --strict-fingerprint \
      || true
else
    echo "WARNING: scripts/compare_campaigns.py not found; skipping campaign report."
fi


banner "COMPLETE"

echo "Fresh benchmark infrastructure created and normal regression matrix executed."
echo
echo "Selected flavors:"
printf '  %s\n' "${SELECTED_FLAVORS[@]}"
echo
echo "Executed:"
echo "  1. fresh direct HTTP/TLS-passthrough controls"
echo "  2. four normal core scenarios across the selected flavors"
echo "  3. scoped cross-flavor campaign comparison"
echo
echo "No Elite-only or other one-off diagnostic run was executed."
echo "Historical results were preserved."
echo "Run log:"
echo "  $LOG"

