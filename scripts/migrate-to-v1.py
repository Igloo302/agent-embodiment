#!/usr/bin/env python3
"""
Migrate body-schema.json from v0 (IP-based IDs) to v1 (MAC-based IDs).

Usage:
    python3 migrate-to-v1.py [--dry-run]
"""

import json
import subprocess
import sys
from pathlib import Path

from typing import Optional

SCHEMA_PATH = Path(__file__).parent.parent / "body-schema.json"


def get_mac_for_ip(ip: str) -> Optional[str]:
    """Get MAC address for an IP via ARP table."""
    try:
        # Try arp table first
        result = subprocess.run(
            ["arp", "-n", ip],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            # Parse arp output: "192.168.5.100 ether 00:11:22:33:44:55 ..."
            for line in result.stdout.split('\n'):
                if ip in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        # Look for MAC address pattern (6 hex pairs with colons)
                        if len(part) == 17 and part.count(':') == 5:
                            try:
                                # Validate hex
                                int(part.replace(':', ''), 16)
                                return part.lower()
                            except ValueError:
                                continue
    except Exception:
        pass
    return None


def migrate_device(device: dict) -> dict:
    """Migrate a single device from v0 to v1 format."""
    old_id = device.get("id", "")
    ip = device.get("ip", "")
    
    # Check if already v1 format (has mac field or id is MAC)
    if device.get("mac") or (len(old_id) == 17 and old_id.count(':') == 5):
        return device  # Already migrated
    
    # Try to get MAC address
    mac = get_mac_for_ip(ip)
    
    if mac:
        # Use MAC as new ID
        new_device = device.copy()
        new_device["id"] = mac
        new_device["mac"] = mac
        new_device["ips"] = [ip]
        new_device["primary_ip"] = ip
        # Remove old single ip field
        new_device.pop("ip", None)
        return new_device
    else:
        # MAC not available, use hostname+IP as temporary ID
        name = device.get("name", "unknown")
        temp_id = f"temp-{name}-{ip}"
        new_device = device.copy()
        new_device["id"] = temp_id
        new_device["ips"] = [ip]
        new_device["primary_ip"] = ip
        new_device["id_type"] = "temporary"
        new_device.pop("ip", None)
        return new_device


def migrate_schema(schema: dict) -> dict:
    """Migrate entire schema from v0 to v1."""
    new_schema = schema.copy()
    
    # Migrate devices
    if "devices" in new_schema:
        new_schema["devices"] = [migrate_device(d) for d in new_schema["devices"]]
    
    # Migrate self (if has ip but no mac)
    if "self" in new_schema:
        self_info = new_schema["self"]
        if "ip" in self_info and "mac" not in self_info:
            ips = self_info.get("ip", [])
            if isinstance(ips, list) and ips:
                # Try to get MAC for first IP
                mac = get_mac_for_ip(ips[0])
                if mac:
                    self_info["mac"] = mac
                    self_info["id"] = mac
    
    # Update schema version
    new_schema["schema_version"] = "1.0"
    
    return new_schema


def main():
    dry_run = "--dry-run" in sys.argv
    
    if not SCHEMA_PATH.exists():
        print(f"Error: {SCHEMA_PATH} not found")
        sys.exit(1)
    
    # Load current schema
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)
    
    # Check if already v1
    if schema.get("schema_version") == "1.0":
        print("Schema already at v1.0, no migration needed.")
        return
    
    print(f"Migrating schema from v{schema.get('schema_version', '0')} to v1.0...")
    
    # Migrate
    new_schema = migrate_schema(schema)
    
    # Show changes
    print("\nDevice ID changes:")
    for old, new in zip(schema.get("devices", []), new_schema.get("devices", [])):
        old_id = old.get("id", "?")
        new_id = new.get("id", "?")
        if old_id != new_id:
            print(f"  {old_id} → {new_id}")
    
    if dry_run:
        print("\n[DRY RUN] Would write:")
        print(json.dumps(new_schema, indent=2, ensure_ascii=False)[:500] + "...")
    else:
        # Backup original
        backup_path = SCHEMA_PATH.with_suffix(".json.v0.bak")
        with open(backup_path, 'w') as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
        print(f"\nBackup saved to: {backup_path}")
        
        # Write new schema
        with open(SCHEMA_PATH, 'w') as f:
            json.dump(new_schema, f, indent=2, ensure_ascii=False)
        print(f"Schema migrated to: {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
