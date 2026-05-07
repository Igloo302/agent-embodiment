#!/usr/bin/env python3
"""
health-check.py — Device health check: ping and port connectivity tests.

Usage:
  python3 health-check.py --quick                    # Quick ping check for all devices
  python3 health-check.py --full                     # Full port scan for all devices
  python3 health-check.py --device "My Router"       # Check specific device by name
  python3 health-check.py --device "aa:bb:cc:dd:ee:ff" --full  # Check by MAC
  python3 health-check.py --quick --output report.json

Features:
  - Quick mode: ICMP ping check only
  - Full mode: Check common ports (22, 80, 443, 5000, 8006, 11434)
  - Update device status in body-schema.json
  - Output JSON report
  - Return statistics: total, reachable, unreachable, duration
"""

import argparse
import json
import logging
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Constants ---
SKILL_DIR = Path(__file__).parent.parent.resolve()
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
LOG_PATH = SKILL_DIR / "operations.log"
CST = timezone(timedelta(hours=8))

# Common ports to check in full mode
DEFAULT_PORTS = [22, 80, 443, 5000, 8006, 11434]
MAX_WORKERS = 20

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("health-check")


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


def ping_device(ip: str, timeout: int = 2) -> bool:
    """Check if device is reachable via ICMP ping."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout * 1000), ip],
            capture_output=True,
            timeout=timeout + 1
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def check_port(ip: str, port: int, timeout: int = 2) -> bool:
    """Check if a specific port is open on the device."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            result = sock.connect_ex((ip, port))
            return result == 0
    except Exception:
        return False


def check_device(device: Dict[str, Any], mode: str, ports: List[int]) -> Dict[str, Any]:
    """Check a single device's health."""
    ip = device.get("primary_ip")
    if not ip:
        ip = device.get("ip")
    if not ip and device.get("ips"):
        ip = device["ips"][0]

    result = {
        "name": device.get("name", "unnamed"),
        "ip": ip,
        "mac": device.get("mac"),
        "type": device.get("type"),
        "status": "unknown",
        "ports": {},
        "error": None
    }

    if not ip:
        result["error"] = "No IP address"
        return result

    # Quick mode: just ping
    if mode == "quick":
        if ping_device(ip):
            result["status"] = "reachable"
        else:
            result["status"] = "unreachable"
        return result

    # Full mode: ping + port check
    reachable = ping_device(ip)
    result["status"] = "reachable" if reachable else "unreachable"

    if reachable:
        for port in ports:
            result["ports"][port] = check_port(ip, port)

    return result


def run_health_check(
    devices: List[Dict[str, Any]],
    mode: str,
    ports: List[int],
    max_workers: int = 10
) -> Tuple[List[Dict[str, Any]], float]:
    """Run health check on multiple devices in parallel."""
    start_time = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_device = {
            executor.submit(check_device, device, mode, ports): device
            for device in devices
        }

        for future in as_completed(future_to_device):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                device = future_to_device[future]
                results.append({
                    "name": device.get("name", "unnamed"),
                    "ip": device.get("primary_ip"),
                    "mac": device.get("mac"),
                    "type": device.get("type"),
                    "status": "unknown",
                    "ports": {},
                    "error": str(e)
                })

    duration = time.time() - start_time
    return results, duration


def update_device_status(schema: Dict[str, Any], results: List[Dict[str, Any]]) -> None:
    """Update device status in schema based on check results."""
    now = datetime.now(CST).isoformat()

    for result in results:
        mac = result.get("mac")
        if not mac:
            continue

        device = get_device_by_mac(schema, mac)
        if device:
            device["status"] = result["status"]
            device["last_seen"] = now

            # Update ports if available
            if result.get("ports"):
                open_ports = [p for p, open in result["ports"].items() if open]
                if open_ports:
                    device["ports"] = sorted(set(device.get("ports", []) + open_ports))


def generate_report(
    results: List[Dict[str, Any]],
    duration: float,
    mode: str,
    ports: List[int]
) -> Dict[str, Any]:
    """Generate a health check report."""
    total = len(results)
    reachable = sum(1 for r in results if r["status"] == "reachable")
    unreachable = sum(1 for r in results if r["status"] == "unreachable")
    unknown = sum(1 for r in results if r["status"] == "unknown")

    report = {
        "check_time": datetime.now(CST).isoformat(),
        "mode": mode,
        "ports_checked": ports if mode == "full" else [],
        "statistics": {
            "total": total,
            "reachable": reachable,
            "unreachable": unreachable,
            "unknown": unknown,
            "duration_seconds": round(duration, 2)
        },
        "devices": results
    }

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Device health check: ping and port connectivity tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick ping check for all devices
  python3 health-check.py --quick

  # Full port scan for all devices
  python3 health-check.py --full

  # Check specific device by name or MAC
  python3 health-check.py --device "My Router" --quick
  python3 health-check.py --device "aa:bb:cc:dd:ee:ff" --full

  # Output report to JSON file
  python3 health-check.py --quick --output report.json
        """
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--quick", action="store_true", help="Quick mode: ICMP ping check only")
    mode_group.add_argument("--full", action="store_true", help="Full mode: ping + port scan")

    parser.add_argument("--device", help="Check specific device by name or MAC address")
    parser.add_argument("--ports", help="Comma-separated list of ports to check (default: 22,80,443,5000,8006,11434)")
    parser.add_argument("--output", help="Output report to JSON file")
    parser.add_argument("--no-update", action="store_true", help="Don't update device status in schema")
    parser.add_argument("--timeout", type=int, default=2, help="Timeout in seconds for each check (default: 2)")

    args = parser.parse_args()

    # Determine mode
    mode = "quick" if args.quick else "full"

    # Parse ports
    ports = DEFAULT_PORTS
    if args.ports:
        try:
            ports = [int(p.strip()) for p in args.ports.split(",") if p.strip()]
        except ValueError:
            print("Error: Invalid port format", file=sys.stderr)
            return 1

    # Load schema
    schema = load_schema()
    devices = schema.get("devices", [])

    if not devices:
        print("No devices found in schema.")
        return 0

    # Filter to specific device if requested
    if args.device:
        device = get_device_by_name(schema, args.device)
        if not device:
            device = get_device_by_mac(schema, args.device)
        if not device:
            print(f"Error: Device not found: {args.device}", file=sys.stderr)
            return 1
        devices = [device]

    print(f"Running {mode} health check on {len(devices)} device(s)...")

    # Deduplicate devices by primary_ip before checking
    seen_ips = set()
    deduped = []
    for d in devices:
        ip = d.get("primary_ip") or d.get("ip")
        if ip and ip not in seen_ips:
            seen_ips.add(ip)
            deduped.append(d)
        elif not ip:
            deduped.append(d)

    if len(deduped) < len(devices):
        print(f"Deduplicated: {len(devices)} -> {len(deduped)} unique devices\n")

    # Run health check
    results, duration = run_health_check(deduped, mode, ports, max_workers=MAX_WORKERS)

    # Update schema
    if not args.no_update:
        update_device_status(schema, results)
        save_schema(schema)

    # Generate report
    report = generate_report(results, duration, mode, ports)

    # Output report
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report saved to: {output_path}")

    # Print summary
    stats = report["statistics"]
    print(f"\n=== Health Check Summary ===")
    print(f"Mode: {mode}")
    print(f"Total devices: {stats['total']}")
    print(f"Reachable: {stats['reachable']}")
    print(f"Unreachable: {stats['unreachable']}")
    print(f"Unknown: {stats['unknown']}")
    print(f"Duration: {stats['duration_seconds']}s")

    # Print device details
    print(f"\n=== Device Status ===")
    for result in sorted(results, key=lambda x: x.get("name", "")):
        status_icon = {
            "reachable": "[OK]",
            "unreachable": "[FAIL]",
            "unknown": "[?]"
        }.get(result["status"], "[?]")
        print(f"  {status_icon} {result['name']} ({result['ip'] or 'no IP'})")

        if mode == "full" and result.get("ports"):
            open_ports = [str(p) for p, open in result["ports"].items() if open]
            if open_ports:
                print(f"       Open ports: {', '.join(open_ports)}")

        if result.get("error"):
            print(f"       Error: {result['error']}")

    logger.info(f"Health check completed: {stats['reachable']}/{stats['total']} reachable in {stats['duration_seconds']}s")

    return 0


if __name__ == "__main__":
    sys.exit(main())
