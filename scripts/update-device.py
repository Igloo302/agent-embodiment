#!/usr/bin/env python3
"""
update-device.py — Internal script for single device incremental updates.
NOT an MCP tool - called by SKILL.md logic and other scripts.

v1.0 Changes:
- MAC address as device unique ID
- Support for ips array (multiple IPs per device)
- Automatic MAC lookup for new IPs
- Merge logic: same MAC = same device

Usage:
  python3 update-device.py <ip> [--type TYPE] [--name NAME] [--ports 22,80] [--status reachable]
  python3 update-device.py --ssh-success <ip> [--hostname <hostname>] [--uname "<uname output>"]
  python3 update-device.py --ssh-fail <ip> --reason "Connection refused"
"""

import json
import sys
import argparse
import re
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SKILL_DIR = Path.home() / ".hermes/skills/agent-embodiment"
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
CREDENTIALS_PATH = SKILL_DIR / "credentials.json"
LOG_OPERATION_SCRIPT = SKILL_DIR / "scripts" / "log-operation.py"
CST = timezone(timedelta(hours=8))

# Schema version for v1.0
SCHEMA_VERSION = "1.0"

# Device type cache TTL (hours)
CACHE_TTL_HOURS = {
    "physical_server": 24,
    "nas": 24,
    "hypervisor": 24,
    "router": 24,
    "vm": 4,
    "docker_host": 4,
    "inference_server": 4,
    "phone": 1,
    "laptop": 1,
    "tablet": 1,
    "container": 0.5,  # 30 min
    "default": 4,
}


def log_operation(action: str, target: str, result: str, detail: str = None, reason: str = None):
    """调用 log-operation.py 记录操作历史（使用 subprocess，不 import）"""
    if not LOG_OPERATION_SCRIPT.exists():
        return
    
    try:
        cmd = ["python3", str(LOG_OPERATION_SCRIPT),
               "--action", action,
               "--target", target,
               "--result", result]
        if detail:
            cmd.extend(["--detail", detail])
        if reason:
            cmd.extend(["--reason", reason])
        
        subprocess.run(cmd, capture_output=True, timeout=5)
    except Exception:
        pass  # 日志记录失败不影响主流程


def load_schema() -> Dict[str, Any]:
    """Load body-schema.json or return empty template."""
    if SCHEMA_PATH.exists():
        try:
            with open(SCHEMA_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "self": {},
        "environment": {"timezone": "Asia/Shanghai", "networks": []},
        "devices": [],
        "services": [],
        "discovery_meta": {"schema_version": SCHEMA_VERSION}
    }


def save_schema(schema: Dict[str, Any]) -> None:
    """Save schema to body-schema.json."""
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)


def load_credentials() -> Dict[str, Any]:
    """Load credential pool."""
    if CREDENTIALS_PATH.exists():
        try:
            with open(CREDENTIALS_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def resolve_credential_ref(credential_ref: str) -> dict:
    """Resolve credential_ref to credential info."""
    credentials = load_credentials()
    return credentials.get(credential_ref, {})


def get_mac_for_ip(ip: str) -> Optional[str]:
    """Try to get MAC address for an IP using ARP."""
    try:
        result = subprocess.run(
            ["arp", "-n", ip],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Parse ARP output
            # macOS: "hostname (192.168.5.1) at aa:bb:cc:dd:ee:ff on en0"
            # Linux: "192.168.5.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"
            output = result.stdout
            mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', output)
            if mac_match:
                return mac_match.group(0).lower().replace("-", ":")
    except Exception:
        pass
    return None


def get_device_by_mac(schema: Dict[str, Any], mac: str) -> Optional[Dict[str, Any]]:
    """Find device by MAC address."""
    if not mac:
        return None
    mac_normalized = mac.lower().replace("-", ":")
    for device in schema.get("devices", []):
        device_mac = device.get("mac", "")
        if device_mac and device_mac.lower().replace("-", ":") == mac_normalized:
            return device
    return None


def get_device_by_ip(schema: Dict[str, Any], ip: str) -> Optional[Dict[str, Any]]:
    """Find device by IP address (checks ip, ips, and primary_ip fields)."""
    for device in schema.get("devices", []):
        # Check old format single IP
        if device.get("ip") == ip:
            return device
        # Check new format IPs array
        if ip in device.get("ips", []):
            return device
        # Check primary_ip
        if device.get("primary_ip") == ip:
            return device
    return None


def get_device_by_temp_id(schema: Dict[str, Any], temp_id: str) -> Optional[Dict[str, Any]]:
    """Find device by temporary ID."""
    for device in schema.get("devices", []):
        if device.get("id") == temp_id and device.get("id_type") == "temporary":
            return device
    return None


def get_cache_ttl(dtype: str) -> float:
    """Get cache TTL for device type (hours)."""
    return CACHE_TTL_HOURS.get(dtype, CACHE_TTL_HOURS["default"])


def is_cache_expired(device: dict) -> bool:
    """Check if device cache is expired."""
    last_seen = device.get("last_seen")
    if not last_seen:
        return True

    try:
        last_dt = datetime.fromisoformat(last_seen)
        now = datetime.now(CST)
        dtype = device.get("type", "default")
        ttl_hours = get_cache_ttl(dtype)
        return (now - last_dt) > timedelta(hours=ttl_hours)
    except Exception:
        return True


def infer_device_type_from_ssh(uname_output: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Infer device type and name from SSH uname -a output.

    Returns: (type, name, os_info)
    """
    dtype = "server"
    name = None
    os_info = None

    if not uname_output:
        return dtype, name, os_info

    os_info = uname_output.strip()

    # Detect container
    if "docker" in uname_output.lower() or "container" in uname_output.lower():
        dtype = "container"
    # Detect VM
    elif "microsoft" in uname_output.lower() or "wsl" in uname_output.lower():
        dtype = "vm"
    # Detect NAS
    elif "synology" in uname_output.lower() or "qnap" in uname_output.lower():
        dtype = "nas"

    # Extract hostname
    parts = uname_output.split()
    if len(parts) > 1:
        name = parts[1]

    return dtype, name, os_info


def update_device(
    ip: str,
    mac: Optional[str] = None,
    dtype: Optional[str] = None,
    name: Optional[str] = None,
    ports: Optional[List[int]] = None,
    services: Optional[List[str]] = None,
    status: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    credential_ref: Optional[str] = None,
    os_info: Optional[str] = None,
    discovered: bool = True,
    source: str = "passive_learning"
) -> Tuple[str, Dict[str, Any]]:
    """Update or add a device using MAC-based identity.

    Args:
        ip: Device IP address
        mac: Device MAC address (if known)
        dtype: Device type
        name: Device name
        ports: List of open ports
        services: List of services
        status: Device status
        capabilities: List of capabilities
        credential_ref: Credential reference ID
        os_info: OS information
        discovered: Whether this was auto-discovered
        source: Source of this information

    Returns:
        Tuple of (action, device) where action is "added" or "updated"
    """
    schema = load_schema()
    now = datetime.now(CST).isoformat()

    # Try to get MAC if not provided
    if not mac:
        mac = get_mac_for_ip(ip)

    # Find existing device
    existing = None

    # 1. Try to find by MAC (if available)
    if mac:
        existing = get_device_by_mac(schema, mac)

    # 2. Try to find by IP
    if not existing:
        existing = get_device_by_ip(schema, ip)

    if existing:
        # Update existing device
        if dtype:
            existing["type"] = dtype
        if name:
            existing["name"] = name
        if ports:
            existing_ports = set(existing.get("ports", []))
            existing_ports.update(ports)
            existing["ports"] = sorted(existing_ports)
        if services:
            existing_svcs = set(existing.get("capabilities", []))
            existing_svcs.update(services)
            existing["capabilities"] = sorted(existing_svcs)
        if status:
            existing["status"] = status
        if capabilities:
            existing_caps = set(existing.get("capabilities", []))
            existing_caps.update(capabilities)
            existing["capabilities"] = sorted(existing_caps)
        if credential_ref:
            existing["credential_ref"] = credential_ref
        if os_info:
            existing["os"] = os_info

        # Update IPs array
        ips = set(existing.get("ips", []))
        # Migrate old single IP to array
        if existing.get("ip") and existing["ip"] not in ips:
            ips.add(existing["ip"])
        ips.add(ip)
        existing["ips"] = list(ips)

        # Update primary_ip if not set
        if not existing.get("primary_ip"):
            existing["primary_ip"] = ip

        # Update MAC if newly discovered
        if mac and not existing.get("mac"):
            existing["mac"] = mac
            existing["id"] = mac
            existing.pop("id_type", None)  # Remove temporary marker

        existing["last_seen"] = now
        existing["source"] = source

        if not discovered:
            existing["discovered"] = False

        action = "updated"
        device = existing
    else:
        # Add new device
        # Generate ID: use MAC if available, otherwise temporary ID
        if mac:
            device_id = mac
            id_type = None
        else:
            # Use hostname+IP combo as temporary ID
            device_id = f"temp-{name or 'device'}-{ip.replace('.', '-')}"
            id_type = "temporary"

        new_dev = {
            "id": device_id,
            "mac": mac,
            "type": dtype or "unknown",
            "name": name or f"device-{ip}",
            "ips": [ip],
            "primary_ip": ip,
            "ports": sorted(ports) if ports else [],
            "capabilities": sorted(set((services or []) + (capabilities or []))),
            "safety_level": "read_only",
            "status": status or "unknown",
            "discovered": discovered,
            "source": source,
            "first_seen": now,
            "last_seen": now,
        }

        if id_type:
            new_dev["id_type"] = id_type
        if credential_ref:
            new_dev["credential_ref"] = credential_ref
        if os_info:
            new_dev["os"] = os_info

        schema.setdefault("devices", []).append(new_dev)
        action = "added"
        device = new_dev

    # Update meta
    schema["discovery_meta"]["last_incremental_update"] = now
    if "schema_version" not in schema.get("discovery_meta", {}):
        schema.setdefault("discovery_meta", {})["schema_version"] = SCHEMA_VERSION

    save_schema(schema)
    
    # 记录操作历史
    log_operation(
        action=f"device-{action}",
        target=device.get("primary_ip") or ip,
        result="success",
        detail=f"{device.get('name', 'unknown')} ({device.get('type', 'unknown')}) - {source}"
    )
    
    return action, device


def handle_ssh_success(
    ip: str,
    hostname: Optional[str] = None,
    uname_output: Optional[str] = None,
    ports: Optional[List[int]] = None,
    services: Optional[List[str]] = None
) -> Tuple[str, Dict[str, Any], bool]:
    """Handle SSH success passive learning update.

    Args:
        ip: Target IP
        hostname: Hostname from SSH connection
        uname_output: Output of uname -a
        ports: Additional discovered ports
        services: Additional discovered services

    Returns:
        Tuple of (action, device, is_new_device)
    """
    dtype, inferred_name, os_info = infer_device_type_from_ssh(uname_output or "")
    name = hostname or inferred_name

    # Merge ports (SSH 22 + additional)
    all_ports = [22]
    if ports:
        all_ports.extend(ports)

    action, device = update_device(
        ip=ip,
        dtype=dtype,
        name=name,
        status="reachable",
        os_info=os_info,
        ports=all_ports,
        services=services,
        discovered=False,
        source="passive_learning"
    )

    is_new = action == "added"
    return action, device, is_new


def handle_ssh_failure(ip: str, reason: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Handle SSH failure passive learning update.

    Args:
        ip: Target IP
        reason: Failure reason

    Returns:
        Tuple of (action, device)
    """
    # Determine status from failure reason
    if reason:
        reason_lower = reason.lower()
        if "connection refused" in reason_lower or "no route" in reason_lower:
            status = "offline"
        elif "permission denied" in reason_lower:
            status = "auth_required"
        elif "timeout" in reason_lower:
            status = "timeout"
        else:
            status = "unreachable"
    else:
        status = "unreachable"

    action, device = update_device(ip=ip, status=status)
    
    # 记录 SSH 失败操作
    log_operation(
        action="ssh-connect",
        target=ip,
        result="fail",
        reason=reason or "unknown error"
    )
    
    return action, device


def parse_ssh_output_for_info(ssh_output: str) -> dict:
    """Parse SSH command output to extract device info.

    Supports parsing:
    - uname -a output
    - hostname output
    - docker ps output (detect docker_host)
    - qm list output (detect hypervisor)
    - curl /api/tags output (detect inference_server)

    Args:
        ssh_output: SSH command stdout

    Returns:
        dict with keys: hostname, uname_output, dtype, ports, services, capabilities
    """
    info = {}

    lines = ssh_output.strip().splitlines()

    for line in lines:
        # uname -a format: Linux hostname 5.15.0 ...
        if line.startswith("Linux ") or line.startswith("Darwin ") or "GNU/Linux" in line:
            info["uname_output"] = line
            parts = line.split()
            if len(parts) > 1:
                info["hostname"] = parts[1]

        # hostname output
        elif len(lines) == 1 and not any(c in line for c in [" ", ":"]):
            info["hostname"] = line.strip()

        # Docker container list
        elif "CONTAINER ID" in line or line.startswith("docker"):
            info["dtype"] = "docker_host"
            info["capabilities"] = ["docker"]

        # PVE VM list
        elif "VMID" in line and "NAME" in line and "STATUS" in line:
            info["dtype"] = "hypervisor"
            info["capabilities"] = ["proxmox", "vm-management"]

        # Ollama API response
        elif '"models"' in line:
            try:
                data = json.loads(line)
                if "models" in data:
                    info["dtype"] = "inference_server"
                    info["capabilities"] = ["ollama", "inference"]
                    info["ports"] = [11434]
            except json.JSONDecodeError:
                pass

    return info


def main():
    parser = argparse.ArgumentParser(
        description="Internal script for single device incremental updates (NOT an MCP tool)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic update
  python3 update-device.py 192.168.5.100 --type vm --name "Win-RTX5070" --ports 22,11434,8188

  # Update status
  python3 update-device.py 192.168.5.100 --status unreachable

  # SSH success passive learning
  python3 update-device.py --ssh-success 192.168.5.100 --hostname win-vm --uname "Linux win-vm 5.15.0..."

  # SSH failure
  python3 update-device.py --ssh-fail 192.168.5.100 --reason "Connection refused"

  # Parse SSH output
  python3 update-device.py --parse-output 192.168.5.100 --ssh-output "$(ssh <ip> 'uname -a && docker ps')"
        """
    )

    parser.add_argument("ip", nargs="?", help="Device IP")
    parser.add_argument("--mac", help="Device MAC address")
    parser.add_argument("--type", dest="dtype", help="Device type (vm/hypervisor/inference_server/nas/server/...)")
    parser.add_argument("--name", help="Device name")
    parser.add_argument("--ports", help="Port list, comma separated (22,80,443)")
    parser.add_argument("--services", help="Service list, comma separated (ssh,http)")
    parser.add_argument("--capabilities", help="Capability list, comma separated")
    parser.add_argument("--status", help="Status (reachable/unreachable/auth_required/running/stopped)")
    parser.add_argument("--credential-ref", dest="credential_ref", help="Credential reference ID")
    parser.add_argument("--os-info", dest="os_info", help="OS information")

    # Passive learning modes
    parser.add_argument("--ssh-success", action="store_true", help="SSH connection success mode")
    parser.add_argument("--ssh-fail", action="store_true", help="SSH connection failure mode")
    parser.add_argument("--hostname", help="Hostname from SSH connection")
    parser.add_argument("--uname", dest="uname_output", help="uname -a output")
    parser.add_argument("--reason", help="SSH failure reason")
    parser.add_argument("--parse-output", dest="ssh_output", help="Parse SSH output to auto-extract info")

    args = parser.parse_args()

    # Passive learning: parse SSH output
    if args.ssh_output:
        if not args.ip:
            print("Error: --parse-output requires IP", file=sys.stderr)
            sys.exit(1)
        parsed = parse_ssh_output_for_info(args.ssh_output)
        action, device, is_new = handle_ssh_success(
            ip=args.ip,
            hostname=parsed.get("hostname") or args.hostname,
            uname_output=parsed.get("uname_output") or args.uname_output,
            ports=parsed.get("ports"),
            services=parsed.get("services"),
        )
        # Update inferred device type
        if parsed.get("dtype"):
            action, device = update_device(ip=args.ip, dtype=parsed["dtype"])
        if parsed.get("capabilities"):
            action, device = update_device(ip=args.ip, capabilities=parsed["capabilities"])

        icon = "+" if is_new else "*"
        print(f"{icon} SSH success: {device['name']} ({device['primary_ip']}) [{device['type']}] - {device['status']}")
        if is_new:
            print(f"   New device discovered!")
        return

    # Passive learning: SSH success
    if args.ssh_success:
        if not args.ip:
            print("Error: --ssh-success requires IP", file=sys.stderr)
            sys.exit(1)
        action, device, is_new = handle_ssh_success(
            ip=args.ip,
            hostname=args.hostname,
            uname_output=args.uname_output,
        )
        icon = "+" if is_new else "*"
        print(f"{icon} SSH success: {device['name']} ({device['primary_ip']}) [{device['type']}] - {device['status']}")
        if is_new:
            print(f"   New device discovered!")
        return

    # Passive learning: SSH failure
    if args.ssh_fail:
        if not args.ip:
            print("Error: --ssh-fail requires IP", file=sys.stderr)
            sys.exit(1)
        action, device = handle_ssh_failure(
            ip=args.ip,
            reason=args.reason,
        )
        print(f"x SSH failed: {device['name']} ({device['primary_ip']}) - {device['status']}")
        if args.reason:
            print(f"   Reason: {args.reason}")
        return

    # Regular update mode
    if not args.ip:
        print("Error: IP is required", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    ports = [int(p) for p in args.ports.split(",")] if args.ports else None
    services = args.services.split(",") if args.services else None
    capabilities = args.capabilities.split(",") if args.capabilities else None

    action, dev = update_device(
        ip=args.ip,
        mac=args.mac,
        dtype=args.dtype,
        name=args.name,
        ports=ports,
        services=services,
        status=args.status,
        capabilities=capabilities,
        credential_ref=args.credential_ref,
        os_info=args.os_info,
    )

    icon = "+" if action == "added" else "*"
    print(f"{icon} {action}: {dev['name']} ({dev['primary_ip']}) [{dev['type']}] - {dev['status']}")


if __name__ == "__main__":
    main()
