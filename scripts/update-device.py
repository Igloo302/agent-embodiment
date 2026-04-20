#!/usr/bin/env python3
"""
update-device.py — 轻量级单设备增量更新
用法: python3 update-device.py <ip> [--type TYPE] [--name NAME] [--ports 22,80] [--status reachable]
不需要跑完整发现流程，Agent 在日常操作中顺手调用。

示例:
  python3 update-device.py <vm-ip> --type vm --name "Win-RTX5070" --ports 22,11434,8188
  python3 update-device.py <ip> --status unreachable
"""

import json
import sys
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_DIR = Path.home() / ".hermes/skills/agent-embodiment"
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
CST = timezone(timedelta(hours=8))


def load_schema():
    if SCHEMA_PATH.exists():
        try:
            with open(SCHEMA_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "self": {},
        "environment": {"timezone": "Asia/Shanghai", "networks": []},
        "devices": [],
        "services": [],
        "discovery_meta": {"schema_version": "1.1"}
    }


def save_schema(schema):
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEMA_PATH, "w") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)


def update_device(ip, dtype=None, name=None, ports=None, services=None, status=None, capabilities=None):
    schema = load_schema()
    dev_id = ip.replace(".", "-")
    now = datetime.now(CST).isoformat()

    # 查找已有设备
    existing = None
    for dev in schema.get("devices", []):
        if dev.get("id") == dev_id or dev.get("ip") == ip:
            existing = dev
            break

    if existing:
        # 更新已有设备
        if dtype:
            existing["type"] = dtype
        if name:
            existing["name"] = name
        if ports:
            existing_ports = set(existing.get("ports", []))
            for p in ports:
                existing_ports.add(p)
            existing["ports"] = sorted(existing_ports)
        if services:
            existing_svcs = set(existing.get("capabilities", []))
            for s in services:
                existing_svcs.add(s)
            existing["capabilities"] = sorted(existing_svcs)
        if status:
            existing["status"] = status
        if capabilities:
            existing_caps = set(existing.get("capabilities", []))
            for c in capabilities:
                existing_caps.add(c)
            existing["capabilities"] = sorted(existing_caps)
        existing["last_seen"] = now
        action = "updated"
    else:
        # 新增设备
        new_dev = {
            "id": dev_id,
            "type": dtype or "unknown",
            "name": name or f"device-{ip}",
            "ip": ip,
            "ports": sorted(ports) if ports else [],
            "capabilities": sorted(set((services or []) + (capabilities or []))),
            "safety_level": "read_only",
            "status": status or "reachable",
            "discovered": True,
            "first_seen": now,
            "last_seen": now,
        }
        schema.setdefault("devices", []).append(new_dev)
        existing = new_dev
        action = "added"

    # 更新 meta
    schema["discovery_meta"]["last_incremental_update"] = now

    save_schema(schema)
    return action, existing


def main():
    parser = argparse.ArgumentParser(description="轻量级设备增量更新")
    parser.add_argument("ip", help="设备 IP")
    parser.add_argument("--type", dest="dtype", help="设备类型 (vm/hypervisor/inference_server/nas/server/...)")
    parser.add_argument("--name", help="设备名称")
    parser.add_argument("--ports", help="端口列表，逗号分隔 (22,80,443)")
    parser.add_argument("--services", help="服务列表，逗号分隔 (ssh,http)")
    parser.add_argument("--capabilities", help="能力列表，逗号分隔")
    parser.add_argument("--status", help="状态 (reachable/unreachable/auth_required/running/stopped)")

    args = parser.parse_args()

    ports = [int(p) for p in args.ports.split(",")] if args.ports else None
    services = args.services.split(",") if args.services else None
    capabilities = args.capabilities.split(",") if args.capabilities else None

    action, dev = update_device(
        ip=args.ip,
        dtype=args.dtype,
        name=args.name,
        ports=ports,
        services=services,
        status=args.status,
        capabilities=capabilities,
    )

    icon = "➕" if action == "added" else "🔄"
    print(f"{icon} {action}: {dev['name']} ({dev['ip']}) [{dev['type']}] — {dev['status']}")


if __name__ == "__main__":
    main()
