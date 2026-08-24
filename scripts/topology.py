from __future__ import annotations

from typing import Any

VALID_GENERATOR_NETWORK_MODES = {
    "auto",
    "shared",
    "dedicated_routed",
    "dedicated_external",
}


def configured_generator_network_mode(cfg: dict[str, Any]) -> str:
    return str((cfg.get("generator_network") or {}).get("mode", "auto"))


def resolved_generator_network_mode(cfg: dict[str, Any]) -> str:
    mode = configured_generator_network_mode(cfg)
    if mode != "auto":
        return mode
    traffic_path = str((cfg.get("benchmark") or {}).get("traffic_path", "tenant_vip"))
    return "dedicated_external" if traffic_path == "floating_ip" else "shared"


def direct_backend_reachable(cfg: dict[str, Any]) -> bool:
    return resolved_generator_network_mode(cfg) != "dedicated_external"
