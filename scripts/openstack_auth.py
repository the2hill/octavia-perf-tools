#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from typing import Any


def decode_cloud(value: Any) -> str | dict[str, Any]:
    """Accept a named cloud, an inline cloud dict, or a JSON-encoded form of either."""
    if isinstance(value, dict):
        return copy.deepcopy(value)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("OpenStack cloud configuration must be a non-empty string or mapping")

    raw = value.strip()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return raw

    if isinstance(decoded, dict):
        return decoded
    if isinstance(decoded, str) and decoded:
        return decoded
    raise ValueError("JSON OpenStack cloud configuration must decode to a string or mapping")


def connection_kwargs(value: Any, region: str | None = None) -> dict[str, Any]:
    cloud = decode_cloud(value)
    if isinstance(cloud, dict):
        kwargs = cloud
    else:
        kwargs = {"cloud": cloud}
    if region and not kwargs.get("region_name"):
        kwargs["region_name"] = region
    return kwargs


def connect(value: Any, region: str | None = None):
    try:
        import openstack
        from openstack import connection
    except ImportError as exc:
        raise RuntimeError("openstacksdk is required; run make bootstrap") from exc

    cloud = decode_cloud(value)
    kwargs = connection_kwargs(cloud, region)
    if isinstance(cloud, dict):
        # Connection() with explicit kwargs does not fall back to clouds.yaml or
        # ambient OS_* variables. That keeps tenant/admin inline identities isolated.
        return connection.Connection(**kwargs)
    return openstack.connect(**kwargs)


def cloud_label(value: Any, inline_label: str) -> str:
    try:
        cloud = decode_cloud(value)
    except ValueError:
        return inline_label
    return cloud if isinstance(cloud, str) else inline_label
