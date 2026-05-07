#!/usr/bin/env python3
"""
learn-device.py — Passive learning: auto-learn device info from user conversation.

v1.0 Changes:
- MAC address as device unique ID
- Support for ips array (multiple IPs per device)
- Automatic MAC lookup for new IPs
- Merge logic: same MAC = same device

Usage:
  python3 learn-device.py --text "打开 192.168.5.1 的路由器的某某功能"
  python3 learn-device.py --text "拍一张照片" --context "用户请求拍照"
  python3 learn-device.py --text "连上 PVE 看看" --ip 192.168.5.100

Features:
  - Extract device info from text (IP, device type, capabilities)
  - Update schema (add or update devices)
  - Mark manually added devices as discovered: false
"""

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Constants ---
# 动态获取 skill 目录（脚本所在目录的上一级）
SKILL_DIR = Path(__file__).parent.parent.resolve()
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
LOG_PATH = SKILL_DIR / "operations.log"
CST = timezone(timedelta(hours=8))

SCHEMA_VERSION = "1.0"

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("learn-device")


# --- Extraction Rules ---

# Device type keywords mapping
DEVICE_TYPE_KEYWORDS: Dict[str, str] = {
    # Network devices
    "路由器": "router", "router": "router",
    "交换机": "switch", "switch": "switch",
    "网关": "gateway", "gateway": "gateway",
    "防火墙": "firewall", "firewall": "firewall",

    # Storage devices
    "nas": "nas", "NAS": "nas",
    "群晖": "nas", "synology": "nas",
    "威联通": "nas", "qnap": "nas",

    # Servers
    "服务器": "server", "server": "server",

    # Virtualization
    "pve": "hypervisor", "PVE": "hypervisor",
    "proxmox": "hypervisor", "Proxmox": "hypervisor",
    "esxi": "hypervisor", "ESXi": "hypervisor",
    "vmware": "hypervisor", "VMware": "hypervisor",
    "虚拟机": "vm", "vm": "vm", "VM": "vm",

    # Containers
    "docker": "docker_host", "Docker": "docker_host",
    "容器": "container", "container": "container",

    # Multimedia devices
    "摄像头": "camera", "相机": "camera", "camera": "camera",
    "打印机": "printer", "printer": "printer",

    # Inference servers
    "推理服务器": "inference_server",
    "ollama": "inference_server", "Ollama": "inference_server",

    # Mobile devices
    "手机": "phone", "iphone": "phone", "iPhone": "phone",
    "安卓": "phone", "android": "phone",
    "平板": "tablet", "ipad": "tablet", "iPad": "tablet",

    # Desktop devices
    "笔记本": "laptop", "macbook": "laptop", "MacBook": "laptop",
    "台式机": "desktop", "电脑": "desktop", "pc": "desktop", "PC": "desktop",
}

# Capability keywords mapping
CAPABILITY_KEYWORDS: Dict[str, str] = {
    # Camera related
    "拍照": "camera", "录像": "camera", "摄像头": "camera", "相机": "camera",

    # SSH related
    "SSH": "ssh", "ssh": "ssh",

    # HTTP/Web related
    "HTTP": "http", "http": "http", "网页": "http", "Web": "http", "web": "http",

    # Inference related
    "Ollama": "ollama", "ollama": "ollama",
    "推理": "inference", "LLM": "inference", "llm": "inference", "模型": "inference",

    # Image generation
    "ComfyUI": "image_gen", "comfyui": "image_gen",
    "生图": "image_gen", "画图": "image_gen", "AI画": "image_gen",
    "Stable Diffusion": "image_gen",

    # Virtualization
    "虚拟机": "virtualization", "VM": "virtualization",

    # Containers
    "Docker": "docker", "docker": "docker", "容器": "docker",

    # Storage
    "存储": "storage", "NAS": "storage", "nas": "storage", "共享": "smb",

    # GPU
    "GPU": "gpu", "gpu": "gpu", "显卡": "gpu",
    "CUDA": "cuda", "cuda": "cuda", "VRAM": "vram",

    # Audio
    "音频": "audio", "麦克风": "audio", "音响": "audio",
}

# IP address regex
IP_PATTERN = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
)


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
        "discovery_meta": {"schema_version": SCHEMA_VERSION}
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
        if device.get("ip") == ip:
            return device
        if ip in device.get("ips", []):
            return device
        if device.get("primary_ip") == ip:
            return device
    return None


def extract_ips(text: str) -> List[str]:
    """Extract IP addresses from text."""
    return IP_PATTERN.findall(text)


def extract_device_types(text: str) -> List[str]:
    """Extract device types from text based on keywords."""
    found_types = set()
    text_lower = text.lower()

    for keyword, dtype in DEVICE_TYPE_KEYWORDS.items():
        if keyword in text or keyword.lower() in text_lower:
            found_types.add(dtype)

    return list(found_types)


def extract_capabilities(text: str) -> List[str]:
    """Extract capabilities from text based on keywords."""
    found_caps = set()

    for keyword, cap in CAPABILITY_KEYWORDS.items():
        if keyword in text:
            found_caps.add(cap)

    return list(found_caps)


def infer_device_name(text: str, ip: Optional[str] = None) -> Optional[str]:
    """Infer device name from text context."""
    for keyword in ["PVE", "NAS", "Ollama", "ComfyUI"]:
        if keyword in text:
            return keyword.lower()

    for cn_name in ["路由器", "交换机", "服务器", "摄像头", "打印机"]:
        if cn_name in text:
            return cn_name

    if ip:
        return f"device-{ip}"

    return None


def parse_text(text: str, context: Optional[str] = None, explicit_ip: Optional[str] = None) -> Dict[str, Any]:
    """Parse text and extract device information.

    Args:
        text: User's message text
        context: Optional context about the conversation
        explicit_ip: Explicitly provided IP (overrides extraction)

    Returns:
        Dict with extracted information:
        - ips: List of IP addresses found
        - device_types: List of device types inferred
        - capabilities: List of capabilities inferred
        - device_name: Inferred device name
        - confidence: Confidence level (high/medium/low)
    """
    combined_text = f"{text} {context or ''}"

    # Extract IPs
    ips = extract_ips(combined_text)
    if explicit_ip:
        if explicit_ip not in ips:
            ips.insert(0, explicit_ip)

    # Extract device types
    device_types = extract_device_types(combined_text)

    # Extract capabilities
    capabilities = extract_capabilities(combined_text)

    # Infer device name
    device_name = infer_device_name(combined_text, ips[0] if ips else None)

    # Determine confidence
    confidence = "low"
    if ips and device_types:
        confidence = "high"
    elif ips or device_types:
        confidence = "medium"

    return {
        "ips": ips,
        "device_types": device_types,
        "capabilities": capabilities,
        "device_name": device_name,
        "confidence": confidence,
    }


def update_or_add_device(
    schema: Dict[str, Any],
    ip: str,
    mac: Optional[str] = None,
    dtype: Optional[str] = None,
    name: Optional[str] = None,
    capabilities: Optional[List[str]] = None,
    discovered: bool = False,
    source: str = "passive_learning"
) -> Tuple[str, Dict[str, Any]]:
    """Update existing device or add new one using MAC-based identity.

    Args:
        schema: The body schema
        ip: Device IP address
        mac: Device MAC address (if known)
        dtype: Device type
        name: Device name
        capabilities: List of capabilities
        discovered: Whether this was auto-discovered (False for manual/passive)
        source: Source of this information

    Returns:
        Tuple of (action, device) where action is "added" or "updated"
    """
    devices = schema.setdefault("devices", [])
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
        if capabilities:
            existing_caps = set(existing.get("capabilities", []))
            existing_caps.update(capabilities)
            existing["capabilities"] = sorted(existing_caps)

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

        return "updated", existing
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
            "ports": [],
            "capabilities": sorted(capabilities) if capabilities else [],
            "safety_level": "read_only",
            "status": "unknown",
            "discovered": discovered,
            "source": source,
            "first_seen": now,
            "last_seen": now,
        }

        if id_type:
            new_dev["id_type"] = id_type

        devices.append(new_dev)
        return "added", new_dev


def learn_from_text(
    text: str,
    context: Optional[str] = None,
    explicit_ip: Optional[str] = None,
    explicit_type: Optional[str] = None,
    explicit_name: Optional[str] = None,
    explicit_capabilities: Optional[str] = None,
    dry_run: bool = False
) -> Dict[str, Any]:
    """Main function to learn device info from text.

    Args:
        text: User's message text
        context: Optional context
        explicit_ip: Override extracted IP
        explicit_type: Override extracted type
        explicit_name: Override extracted name
        explicit_capabilities: Override extracted capabilities (comma-separated)
        dry_run: If True, don't actually update schema

    Returns:
        Result dict with learned devices and actions taken
    """
    # Parse text
    parsed = parse_text(text, context, explicit_ip)

    # Override with explicit values
    if explicit_ip:
        parsed["ips"] = [explicit_ip]
    if explicit_type:
        parsed["device_types"] = [explicit_type]
    if explicit_name:
        parsed["device_name"] = explicit_name
    if explicit_capabilities:
        parsed["capabilities"] = explicit_capabilities.split(",")

    result = {
        "parsed": parsed,
        "devices": [],
        "actions": [],
        "dry_run": dry_run
    }

    if not parsed["ips"]:
        logger.info(f"No IP found in text: {text[:50]}...")
        return result

    if dry_run:
        # Just return what would be done
        for ip in parsed["ips"]:
            mac = get_mac_for_ip(ip)
            result["devices"].append({
                "ip": ip,
                "mac": mac,
                "type": parsed["device_types"][0] if parsed["device_types"] else "unknown",
                "name": parsed["device_name"] or f"device-{ip}",
                "capabilities": parsed["capabilities"],
                "action": "would_add_or_update"
            })
        return result

    # Load schema
    schema = load_schema()

    # Process each IP
    for ip in parsed["ips"]:
        dtype = parsed["device_types"][0] if parsed["device_types"] else None
        name = parsed["device_name"]
        caps = parsed["capabilities"]

        # Try to get MAC address
        mac = get_mac_for_ip(ip)

        action, device = update_or_add_device(
            schema=schema,
            ip=ip,
            mac=mac,
            dtype=dtype,
            name=name,
            capabilities=caps,
            discovered=False,  # Passive learning = not auto-discovered
            source="passive_learning"
        )

        result["devices"].append(device)
        result["actions"].append(action)

        logger.info(f"{action}: {device['name']} ({ip}) [{device['type']}]")

    # Save schema
    schema["discovery_meta"]["last_passive_learning"] = datetime.now(CST).isoformat()
    save_schema(schema)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Passive learning: auto-learn device info from user conversation (v1.0 MAC-based)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract device info from text
  python3 learn-device.py --text "打开 192.168.5.1 的路由器设置"

  # Preview mode (don't actually update)
  python3 learn-device.py --text "连上 PVE 看看" --dry-run

  # Explicitly specify info
  python3 learn-device.py --text "连上那个服务器" --ip 192.168.5.100 --type server --name "主服务器"

  # Specify capabilities
  python3 learn-device.py --text "用 Ollama 推理" --ip 192.168.5.50 --capabilities "inference,gpu"
        """
    )

    parser.add_argument("--text", required=True, help="User conversation text")
    parser.add_argument("--context", help="Conversation context")
    parser.add_argument("--ip", help="Explicitly specify IP (overrides extraction)")
    parser.add_argument("--type", dest="device_type", help="Explicitly specify device type")
    parser.add_argument("--name", dest="device_name", help="Explicitly specify device name")
    parser.add_argument("--capabilities", help="Explicitly specify capabilities (comma separated)")
    parser.add_argument("--dry-run", action="store_true", help="Preview mode, don't update schema")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    args = parser.parse_args()

    result = learn_from_text(
        text=args.text,
        context=args.context,
        explicit_ip=args.ip,
        explicit_type=args.device_type,
        explicit_name=args.device_name,
        explicit_capabilities=args.capabilities,
        dry_run=args.dry_run
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        # Human-readable output
        if not result["parsed"]["ips"]:
            print("No device IP found in text")
            return

        print(f"Parsed result (confidence: {result['parsed']['confidence']})")
        print(f"   IP: {', '.join(result['parsed']['ips'])}")
        if result['parsed']['device_types']:
            print(f"   Type: {', '.join(result['parsed']['device_types'])}")
        if result['parsed']['capabilities']:
            print(f"   Capabilities: {', '.join(result['parsed']['capabilities'])}")
        if result['parsed']['device_name']:
            print(f"   Name: {result['parsed']['device_name']}")

        if args.dry_run:
            print("\nPreview mode (schema not updated)")
        else:
            print(f"\nUpdated {len(result['devices'])} devices:")
            for i, dev in enumerate(result['devices']):
                action = result['actions'][i]
                icon = "+" if action == "added" else "*"
                mac_str = f" MAC:{dev['mac']}" if dev.get('mac') else ""
                print(f"   {icon} {dev['name']} ({dev['primary_ip']}) [{dev['type']}]{mac_str}")


if __name__ == "__main__":
    main()