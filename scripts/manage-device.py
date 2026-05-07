#!/usr/bin/env python3
"""
manage-device.py — Manual device management: add, update, delete devices.

Usage:
  python3 manage-device.py add --name "My Router" --ip 192.168.5.1 --type router
  python3 manage-device.py add --ip 192.168.5.100  # MAC auto-detected via ARP
  python3 manage-device.py update --mac "aa:bb:cc:dd:ee:ff" --name "New Name"
  python3 manage-device.py delete --mac "aa:bb:cc:dd:ee:ff" --confirm

Features:
  - MAC as unique identifier
  - Support for ips array and primary_ip
  - Auto MAC lookup via ARP for new IPs
  - Friendly error messages and success confirmations
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- Constants ---
SKILL_DIR = Path(__file__).parent.parent.resolve()
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
LOG_PATH = SKILL_DIR / "operations.log"
CST = timezone(timedelta(hours=8))

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("manage-device")


# --- Helper Functions ---

def load_schema() -> Dict[str, Any]:
    """Load body-schema.json or return empty template."""
    if SCHEMA_PATH.exists():
        try:
            with open(SCHEMA_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Schema corrupted, creating new: {e}")

    return {
        "self": {},
        "environment": {"timezone": "Asia/Shanghai", "networks": []},
        "devices": [],
        "services": [],
        "discovery_meta": {"schema_version": "1.0"}
    }


def save_schema(schema: Dict[str, Any]) -> None:
    """Save schema to body-schema.json."""
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)


def get_mac_for_ip(ip: str) -> Optional[str]:
    """Try to get MAC address for an IP using ARP."""
    try:
        result = subprocess.run(
            ["arp", "-n", ip],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            output = result.stdout
            mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', output)
            if mac_match:
                return mac_match.group(0).lower().replace("-", ":")
    except Exception:
        pass
    return None


def normalize_mac(mac: str) -> str:
    """Normalize MAC address format to lowercase with colons."""
    return mac.lower().replace("-", ":")


def get_device_by_mac(schema: Dict[str, Any], mac: str) -> Optional[Dict[str, Any]]:
    """Find device by MAC address."""
    if not mac:
        return None
    mac_normalized = normalize_mac(mac)
    for device in schema.get("devices", []):
        device_mac = device.get("mac", "")
        if device_mac and normalize_mac(device_mac) == mac_normalized:
            return device
    return None


def get_device_by_name(schema: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Find device by name (exact match, case-insensitive)."""
    if not name:
        return None
    name_lower = name.lower()
    for device in schema.get("devices", []):
        device_name = device.get("name", "")
        if device_name and device_name.lower() == name_lower:
            return device
    return None


def get_device_by_ip(schema: Dict[str, Any], ip: str) -> Optional[Dict[str, Any]]:
    """Find device by IP address (checks ip, ips, and primary_ip fields)."""
    for device in schema.get("devices", []):
        if device.get("ip") == ip:
            return device
        if ip in device.get("ips", []):
            return device
        if device.get("primary_ip") == ip:
            return device
    return None


def validate_ip(ip: str) -> bool:
    """Validate IP address format."""
    pattern = re.compile(
        r'^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
        r'(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
    )
    return bool(pattern.match(ip))


def validate_mac(mac: str) -> bool:
    """Validate MAC address format."""
    pattern = re.compile(
        r'^([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}$'
    )
    return bool(pattern.match(mac))


# --- Command Handlers ---

def cmd_add(args: argparse.Namespace) -> int:
    """Add a new device to the schema."""
    # Validate required fields
    if not args.name and not args.ip:
        print("Error: Must provide --name or --ip", file=sys.stderr)
        return 1

    # Validate IP if provided
    if args.ip and not validate_ip(args.ip):
        print(f"Error: Invalid IP address format: {args.ip}", file=sys.stderr)
        return 1

    # Validate MAC if provided
    if args.mac and not validate_mac(args.mac):
        print(f"Error: Invalid MAC address format: {args.mac}", file=sys.stderr)
        return 1

    schema = load_schema()
    devices = schema.setdefault("devices", [])
    now = datetime.now(CST).isoformat()

    # Determine MAC
    mac = None
    if args.mac:
        mac = normalize_mac(args.mac)
    elif args.ip:
        mac = get_mac_for_ip(args.ip)
        if mac:
            print(f"Info: Auto-detected MAC: {mac}")

    # Check for existing device by MAC
    if mac:
        existing = get_device_by_mac(schema, mac)
        if existing:
            print(f"Error: Device with MAC {mac} already exists: {existing.get('name')}", file=sys.stderr)
            return 1

    # Check for existing device by IP
    if args.ip:
        existing = get_device_by_ip(schema, args.ip)
        if existing:
            print(f"Error: Device with IP {args.ip} already exists: {existing.get('name')}", file=sys.stderr)
            return 1

    # Parse capabilities
    capabilities = []
    if args.capabilities:
        capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]

    # Determine device name
    name = args.name or f"device-{args.ip}"

    # Generate device ID
    if mac:
        device_id = mac
    else:
        device_id = f"temp-{name.replace(' ', '-').lower()}-{args.ip.replace('.', '-') if args.ip else 'no-ip'}"

    # Create new device
    new_device = {
        "id": device_id,
        "mac": mac,
        "type": args.type or "unknown",
        "name": name,
        "ips": [args.ip] if args.ip else [],
        "primary_ip": args.ip,
        "ports": [],
        "capabilities": sorted(capabilities),
        "safety_level": "read_only",
        "status": "unknown",
        "discovered": False,
        "source": "manual",
        "first_seen": now,
        "last_seen": now,
    }

    devices.append(new_device)
    save_schema(schema)

    logger.info(f"Added device: {name} ({args.ip or 'no IP'}) [{args.type or 'unknown'}]")
    print(f"Success: Added device '{name}'")
    if args.ip:
        print(f"  IP: {args.ip}")
    if mac:
        print(f"  MAC: {mac}")
    print(f"  Type: {args.type or 'unknown'}")
    if capabilities:
        print(f"  Capabilities: {', '.join(capabilities)}")

    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update an existing device."""
    if not args.mac and not args.name:
        print("Error: Must provide --mac or --name to identify device", file=sys.stderr)
        return 1

    # Validate MAC if provided for lookup
    if args.mac and not validate_mac(args.mac):
        print(f"Error: Invalid MAC address format: {args.mac}", file=sys.stderr)
        return 1

    # Validate new MAC if provided
    if args.new_mac and not validate_mac(args.new_mac):
        print(f"Error: Invalid MAC address format: {args.new_mac}", file=sys.stderr)
        return 1

    # Validate IP if provided
    if args.ip and not validate_ip(args.ip):
        print(f"Error: Invalid IP address format: {args.ip}", file=sys.stderr)
        return 1

    schema = load_schema()

    # Find device
    device = None
    if args.mac:
        device = get_device_by_mac(schema, args.mac)
    if not device and args.name:
        device = get_device_by_name(schema, args.name)

    if not device:
        identifier = args.mac or args.name
        print(f"Error: Device not found: {identifier}", file=sys.stderr)
        return 1

    # Check if new MAC conflicts with another device
    if args.new_mac:
        existing = get_device_by_mac(schema, args.new_mac)
        if existing and existing is not device:
            print(f"Error: Another device already has MAC {args.new_mac}: {existing.get('name')}", file=sys.stderr)
            return 1

    # Check if new IP conflicts with another device
    if args.ip:
        existing = get_device_by_ip(schema, args.ip)
        if existing and existing is not device:
            print(f"Error: Another device already has IP {args.ip}: {existing.get('name')}", file=sys.stderr)
            return 1

    # Track changes
    changes = []

    # Update fields
    if args.new_mac:
        old_mac = device.get("mac")
        device["mac"] = normalize_mac(args.new_mac)
        device["id"] = device["mac"]
        device.pop("id_type", None)
        changes.append(f"MAC: {old_mac} -> {device['mac']}")

    if args.name:
        old_name = device.get("name")
        device["name"] = args.name
        changes.append(f"name: {old_name} -> {args.name}")

    if args.type:
        old_type = device.get("type")
        device["type"] = args.type
        changes.append(f"type: {old_type} -> {args.type}")

    if args.ip:
        ips = set(device.get("ips", []))
        old_primary = device.get("primary_ip")
        ips.add(args.ip)
        device["ips"] = list(ips)
        device["primary_ip"] = args.ip
        changes.append(f"primary IP: {old_primary} -> {args.ip}")

    if args.add_ip:
        ips = set(device.get("ips", []))
        for ip in args.add_ip:
            if validate_ip(ip):
                ips.add(ip)
            else:
                print(f"Warning: Invalid IP skipped: {ip}", file=sys.stderr)
        device["ips"] = list(ips)
        changes.append(f"added IPs: {', '.join(args.add_ip)}")

    if args.remove_ip:
        ips = set(device.get("ips", []))
        for ip in args.remove_ip:
            ips.discard(ip)
        device["ips"] = list(ips)
        if device.get("primary_ip") in args.remove_ip:
            device["primary_ip"] = device["ips"][0] if device["ips"] else None
        changes.append(f"removed IPs: {', '.join(args.remove_ip)}")

    if args.capabilities:
        capabilities = [c.strip() for c in args.capabilities.split(",") if c.strip()]
        old_caps = device.get("capabilities", [])
        device["capabilities"] = sorted(capabilities)
        changes.append(f"capabilities: {old_caps} -> {capabilities}")

    if args.add_capabilities:
        existing_caps = set(device.get("capabilities", []))
        new_caps = [c.strip() for c in args.add_capabilities.split(",") if c.strip()]
        existing_caps.update(new_caps)
        device["capabilities"] = sorted(existing_caps)
        changes.append(f"added capabilities: {', '.join(new_caps)}")

    if args.remove_capabilities:
        existing_caps = set(device.get("capabilities", []))
        remove_caps = [c.strip() for c in args.remove_capabilities.split(",") if c.strip()]
        existing_caps.difference_update(remove_caps)
        device["capabilities"] = sorted(existing_caps)
        changes.append(f"removed capabilities: {', '.join(remove_caps)}")

    if args.safety_level:
        old_level = device.get("safety_level")
        device["safety_level"] = args.safety_level
        changes.append(f"safety_level: {old_level} -> {args.safety_level}")

    if args.notes:
        old_notes = device.get("notes", "")
        device["notes"] = args.notes
        changes.append(f"notes updated")

    if not changes:
        print("Warning: No changes specified", file=sys.stderr)
        return 1

    device["last_seen"] = datetime.now(CST).isoformat()
    save_schema(schema)

    logger.info(f"Updated device: {device.get('name')} - {', '.join(changes)}")
    print(f"Success: Updated device '{device.get('name')}'")
    for change in changes:
        print(f"  {change}")

    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete a device from the schema."""
    if not args.mac and not args.name:
        print("Error: Must provide --mac or --name to identify device", file=sys.stderr)
        return 1

    if not args.confirm:
        print("Error: Must use --confirm to delete a device", file=sys.stderr)
        return 1

    # Validate MAC if provided
    if args.mac and not validate_mac(args.mac):
        print(f"Error: Invalid MAC address format: {args.mac}", file=sys.stderr)
        return 1

    schema = load_schema()
    devices = schema.get("devices", [])

    # Find device
    device = None
    device_index = -1
    if args.mac:
        mac_normalized = normalize_mac(args.mac)
        for i, d in enumerate(devices):
            d_mac = d.get("mac", "")
            if d_mac and normalize_mac(d_mac) == mac_normalized:
                device = d
                device_index = i
                break

    if not device and args.name:
        name_lower = args.name.lower()
        for i, d in enumerate(devices):
            d_name = d.get("name", "")
            if d_name and d_name.lower() == name_lower:
                device = d
                device_index = i
                break

    if not device:
        identifier = args.mac or args.name
        print(f"Error: Device not found: {identifier}", file=sys.stderr)
        return 1

    # Remove device
    deleted_name = device.get("name")
    deleted_ip = device.get("primary_ip")
    deleted_mac = device.get("mac")

    devices.pop(device_index)
    save_schema(schema)

    logger.info(f"Deleted device: {deleted_name} ({deleted_ip}) MAC:{deleted_mac}")
    print(f"Success: Deleted device '{deleted_name}'")
    if deleted_ip:
        print(f"  IP: {deleted_ip}")
    if deleted_mac:
        print(f"  MAC: {deleted_mac}")

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List all devices."""
    schema = load_schema()
    devices = schema.get("devices", [])

    if not devices:
        print("No devices found.")
        return 0

    print(f"Total devices: {len(devices)}\n")

    for device in devices:
        name = device.get("name", "unnamed")
        dtype = device.get("type", "unknown")
        primary_ip = device.get("primary_ip", "N/A")
        mac = device.get("mac", "N/A")
        discovered = "auto" if device.get("discovered") else "manual"
        source = device.get("source", "unknown")

        print(f"  {name}")
        print(f"    Type: {dtype}")
        print(f"    IP: {primary_ip}")
        print(f"    MAC: {mac}")
        print(f"    Source: {source} ({discovered})")
        print()

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Manual device management: add, update, delete devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Add a new device
  python3 manage-device.py add --name "My Router" --ip 192.168.5.1 --type router
  python3 manage-device.py add --ip 192.168.5.100 --mac "aa:bb:cc:dd:ee:ff"
  python3 manage-device.py add --name "Ollama Server" --ip 192.168.5.50 --type inference_server --capabilities "inference,gpu"

  # Update a device
  python3 manage-device.py update --mac "aa:bb:cc:dd:ee:ff" --name "New Name"
  python3 manage-device.py update --name "Old Name" --type server --ip 192.168.5.200
  python3 manage-device.py update --mac "aa:bb:cc:dd:ee:ff" --add-capabilities "ssh,http"
  python3 manage-device.py update --mac "aa:bb:cc:dd:ee:ff" --notes "Main server"

  # Delete a device
  python3 manage-device.py delete --mac "aa:bb:cc:dd:ee:ff" --confirm
  python3 manage-device.py delete --name "Old Device" --confirm

  # List all devices
  python3 manage-device.py list
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Add command
    add_parser = subparsers.add_parser("add", help="Add a new device")
    add_parser.add_argument("--name", help="Device name")
    add_parser.add_argument("--ip", help="Device IP address")
    add_parser.add_argument("--mac", help="Device MAC address (auto-detected if not provided)")
    add_parser.add_argument("--type", help="Device type (e.g., router, server, nas)")
    add_parser.add_argument("--capabilities", help="Comma-separated list of capabilities")

    # Update command
    update_parser = subparsers.add_parser("update", help="Update an existing device")
    update_parser.add_argument("--mac", help="Find device by MAC address")
    update_parser.add_argument("--name", help="Find device by name (or set new name if used alone)")
    update_parser.add_argument("--new-mac", dest="new_mac", help="New MAC address")
    update_parser.add_argument("--ip", help="Set primary IP address")
    update_parser.add_argument("--add-ip", action="append", help="Add an IP address (can be used multiple times)")
    update_parser.add_argument("--remove-ip", action="append", help="Remove an IP address (can be used multiple times)")
    update_parser.add_argument("--type", help="Device type")
    update_parser.add_argument("--capabilities", help="Replace capabilities (comma-separated)")
    update_parser.add_argument("--add-capabilities", help="Add capabilities (comma-separated)")
    update_parser.add_argument("--remove-capabilities", help="Remove capabilities (comma-separated)")
    update_parser.add_argument("--safety-level", choices=["read_only", "read_write", "full_control"], help="Safety level")
    update_parser.add_argument("--notes", help="Device notes")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a device")
    delete_parser.add_argument("--mac", help="Find device by MAC address")
    delete_parser.add_argument("--name", help="Find device by name")
    delete_parser.add_argument("--confirm", action="store_true", help="Confirm deletion")

    # List command
    list_parser = subparsers.add_parser("list", help="List all devices")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "add":
        return cmd_add(args)
    elif args.command == "update":
        return cmd_update(args)
    elif args.command == "delete":
        return cmd_delete(args)
    elif args.command == "list":
        return cmd_list(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
