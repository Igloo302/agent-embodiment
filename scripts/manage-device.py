#!/usr/bin/env python3
"""
manage-device.py — Manual device management: add, update, delete, export, import devices.

Usage:
  python3 manage-device.py add --name "My Router" --ip 192.168.5.1 --type router
  python3 manage-device.py add --ip 192.168.5.100  # MAC auto-detected via ARP
  python3 manage-device.py update --mac "aa:bb:cc:dd:ee:ff" --name "New Name"
  python3 manage-device.py delete --mac "aa:bb:cc:dd:ee:ff" --confirm
  python3 manage-device.py export --output devices.json --filter type=server
  python3 manage-device.py import --input devices.json --merge

Features:
  - MAC as unique identifier
  - Support for ips array and primary_ip
  - Auto MAC lookup via ARP for new IPs
  - Tags system for device categorization
  - Export/Import devices to/from JSON
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

    # Parse tags
    tags = []
    if args.tags:
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]

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
        "tags": sorted(tags),
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

    # Tags management
    if args.add_tags:
        tags = set(device.get("tags", []))
        new_tags = [t.strip() for t in args.add_tags.split(",") if t.strip()]
        tags.update(new_tags)
        device["tags"] = sorted(tags)
        changes.append(f"added tags: {', '.join(new_tags)}")

    if args.remove_tags:
        tags = set(device.get("tags", []))
        remove_tags = [t.strip() for t in args.remove_tags.split(",") if t.strip()]
        tags.difference_update(remove_tags)
        device["tags"] = sorted(tags)
        changes.append(f"removed tags: {', '.join(remove_tags)}")

    if args.tags:
        old_tags = device.get("tags", [])
        new_tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        device["tags"] = sorted(new_tags)
        changes.append(f"tags: {old_tags} -> {new_tags}")

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

    # Filter by type
    if args.filter_type:
        devices = [d for d in devices if d.get("type") == args.filter_type]

    # Filter by tag
    if args.tag:
        devices = [d for d in devices if args.tag in d.get("tags", [])]

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
        tags = device.get("tags", [])

        print(f"  {name}")
        print(f"    Type: {dtype}")
        print(f"    IP: {primary_ip}")
        print(f"    MAC: {mac}")
        print(f"    Source: {source} ({discovered})")
        if tags:
            print(f"    Tags: {', '.join(tags)}")
        print()

    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export devices to a JSON file."""
    schema = load_schema()
    devices = schema.get("devices", [])

    # Apply filters
    if args.filter:
        filter_parts = args.filter.split("=", 1)
        if len(filter_parts) == 2:
            filter_key, filter_value = filter_parts
            if filter_key == "type":
                devices = [d for d in devices if d.get("type") == filter_value]
            elif filter_key == "tag":
                devices = [d for d in devices if filter_value in d.get("tags", [])]
            else:
                print(f"Warning: Unknown filter key '{filter_key}', ignoring filter", file=sys.stderr)

    if not devices:
        print("No devices to export.")
        return 0

    output_path = Path(args.output)

    # Prepare export data
    export_data = {
        "exported_at": datetime.now(CST).isoformat(),
        "export_version": "1.0",
        "device_count": len(devices),
        "devices": devices
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False)

    logger.info(f"Exported {len(devices)} devices to {output_path}")
    print(f"Success: Exported {len(devices)} devices to '{output_path}'")

    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Import devices from a JSON file."""
    input_path = Path(args.input)

    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        with open(input_path, encoding="utf-8") as f:
            import_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in input file: {e}", file=sys.stderr)
        return 1

    # Extract devices from import data
    if isinstance(import_data, dict) and "devices" in import_data:
        import_devices = import_data["devices"]
    elif isinstance(import_data, list):
        import_devices = import_data
    else:
        print("Error: Invalid import file format. Expected dict with 'devices' key or list.", file=sys.stderr)
        return 1

    if not import_devices:
        print("No devices to import.")
        return 0

    schema = load_schema()
    existing_devices = schema.get("devices", [])

    # Build lookup for existing devices by MAC, name, and primary_ip
    existing_by_mac = {}
    existing_by_name = {}
    existing_by_ip = {}
    for d in existing_devices:
        mac = d.get("mac")
        if mac:
            existing_by_mac[normalize_mac(mac)] = d
        name = d.get("name")
        if name:
            existing_by_name[name.lower()] = d
        # primary_ip
        pip = d.get("primary_ip") or d.get("ip")
        if pip:
            existing_by_ip[pip] = d
        # also check ips array
        for ip in d.get("ips", []):
            existing_by_ip.setdefault(ip, d)

    stats = {"added": 0, "updated": 0, "skipped": 0}

    if args.replace:
        # Replace mode: clear all existing devices
        existing_devices.clear()

    for device in import_devices:
        mac = device.get("mac")
        if mac:
            mac = normalize_mac(mac)

        if args.replace:
            # In replace mode, just add all devices
            device["mac"] = mac
            existing_devices.append(device)
            stats["added"] += 1
        else:
            # Merge mode - check MAC, name, and IP
            existing = None
            if mac and mac in existing_by_mac:
                existing = existing_by_mac[mac]
            if not existing:
                import_name = device.get("name", "")
                if import_name and import_name.lower() in existing_by_name:
                    existing = existing_by_name[import_name.lower()]
            if not existing:
                import_ip = device.get("primary_ip") or device.get("ip")
                if import_ip and import_ip in existing_by_ip:
                    existing = existing_by_ip[import_ip]

            if existing:
                # Device exists - update it
                if args.update_existing:
                    # Update fields from imported device
                    for key, value in device.items():
                        if key != "mac":  # Don't overwrite MAC
                            existing[key] = value
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1
            else:
                # New device
                device["mac"] = mac
                existing_devices.append(device)
                stats["added"] += 1

    save_schema(schema)

    logger.info(f"Imported devices: added={stats['added']}, updated={stats['updated']}, skipped={stats['skipped']}")
    print(f"Success: Imported devices from '{input_path}'")
    print(f"  Added: {stats['added']}")
    print(f"  Updated: {stats['updated']}")
    print(f"  Skipped: {stats['skipped']}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Manual device management: add, update, delete, export, import devices",
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
  python3 manage-device.py update --mac "aa:bb:cc:dd:ee:ff" --add-tags "production,critical"
  python3 manage-device.py update --mac "aa:bb:cc:dd:ee:ff" --notes "Main server"

  # Delete a device
  python3 manage-device.py delete --mac "aa:bb:cc:dd:ee:ff" --confirm
  python3 manage-device.py delete --name "Old Device" --confirm

  # List devices
  python3 manage-device.py list
  python3 manage-device.py list --filter-type server
  python3 manage-device.py list --tag production

  # Export devices
  python3 manage-device.py export --output devices.json
  python3 manage-device.py export --filter type=server --output servers.json

  # Import devices
  python3 manage-device.py import --input devices.json
  python3 manage-device.py import --input devices.json --replace
  python3 manage-device.py import --input devices.json --update-existing
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
    add_parser.add_argument("--tags", help="Comma-separated list of tags")

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
    update_parser.add_argument("--tags", help="Replace tags (comma-separated)")
    update_parser.add_argument("--add-tags", help="Add tags (comma-separated)")
    update_parser.add_argument("--remove-tags", help="Remove tags (comma-separated)")
    update_parser.add_argument("--safety-level", choices=["read_only", "read_write", "full_control"], help="Safety level")
    update_parser.add_argument("--notes", help="Device notes")

    # Delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a device")
    delete_parser.add_argument("--mac", help="Find device by MAC address")
    delete_parser.add_argument("--name", help="Find device by name")
    delete_parser.add_argument("--confirm", action="store_true", help="Confirm deletion")

    # List command
    list_parser = subparsers.add_parser("list", help="List all devices")
    list_parser.add_argument("--filter-type", dest="filter_type", help="Filter by device type")
    list_parser.add_argument("--tag", help="Filter by tag")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export devices to JSON file")
    export_parser.add_argument("--output", default="devices-export.json", help="Output file path (default: devices-export.json)")
    export_parser.add_argument("--filter", help="Filter devices (format: type=server or tag=production)")

    # Import command
    import_parser = subparsers.add_parser("import", help="Import devices from JSON file")
    import_parser.add_argument("--input", required=True, help="Input file path")
    import_parser.add_argument("--merge", action="store_true", default=True, help="Merge with existing devices (default)")
    import_parser.add_argument("--replace", action="store_true", help="Replace all existing devices")
    import_parser.add_argument("--update-existing", action="store_true", help="Update existing devices with same MAC")

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
    elif args.command == "export":
        return cmd_export(args)
    elif args.command == "import":
        return cmd_import(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
