#!/usr/bin/env python3
"""
operations.py — Contract-first operation definitions for Agent Embodiment MCP v1.0.
Single source of truth for all operations exposed via MCP.

v1.0 Changes:
- Only 2 MCP tools: query_device, learn_device
- MAC address as device unique ID
- Support for ips array (multiple IPs per device)
- Backward compatibility with old IP-based schema format
"""

import json
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --- Constants ---
# 动态获取 skill 目录（本文件在 mcp/ 下，上一级是 skill 根目录）
SKILL_DIR = Path(__file__).parent.parent.resolve()
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
SCRIPTS_DIR = SKILL_DIR / "scripts"
CACHE_DIR = SKILL_DIR / ".cache"
LOG_OPERATION_SCRIPT = SCRIPTS_DIR / "log-operation.py"

CST = timezone(timedelta(hours=8))

# Schema version for v1.0
SCHEMA_VERSION = "1.0"

# --- Types ---
class OperationError(Exception):
    """Structured error for operations."""
    def __init__(self, code: str, message: str, suggestion: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestion = suggestion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.code,
            "message": self.message,
            "suggestion": self.suggestion
        }


# --- Operation Logging ---

def log_operation(action: str, target: str, result: str, detail: str = None, reason: str = None):
    """Call log-operation.py to record operation history."""
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
        pass  # Logging failure should not break main flow


# --- Schema Helpers ---

def load_schema() -> Dict[str, Any]:
    """Load body-schema.json or return empty template."""
    if SCHEMA_PATH.exists():
        try:
            with open(SCHEMA_PATH, encoding="utf-8") as f:
                schema = json.load(f)
                # Migrate old format if needed
                schema = migrate_schema_if_needed(schema)
                return schema
        except (json.JSONDecodeError, Exception) as e:
            raise OperationError("schema_error", f"Schema corrupted: {e}")

    return {
        "self": {},
        "environment": {"timezone": "Asia/Shanghai", "networks": []},
        "devices": [],
        "services": [],
        "discovery_meta": {"schema_version": SCHEMA_VERSION}
    }


def migrate_schema_if_needed(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate old IP-based schema to new MAC-based format."""
    meta = schema.get("discovery_meta", {})
    version = meta.get("schema_version", "0.9")

    # Already on v1.0+
    if version >= "1.0":
        return schema

    # Migrate devices from IP-based ID to MAC-based ID
    migrated_devices = []
    for device in schema.get("devices", []):
        old_id = device.get("id", "")
        ip = device.get("ip", "")

        # Check if already migrated (has mac field)
        if device.get("mac"):
            migrated_devices.append(device)
            continue

        # Old format: id = "192-168-5-100", ip = "192.168.5.100"
        # New format: id = MAC address, mac = MAC, ips = [ip], primary_ip = ip
        if ip and not device.get("ips"):
            device["ips"] = [ip]
            device["primary_ip"] = ip

        # Mark as needing MAC discovery
        if not device.get("mac"):
            device["mac"] = None
            device["id"] = old_id  # Keep old ID temporarily
            device["id_type"] = "temporary"

        migrated_devices.append(device)

    schema["devices"] = migrated_devices
    schema["discovery_meta"]["schema_version"] = SCHEMA_VERSION
    schema["discovery_meta"]["migrated_from"] = version

    # Save migrated schema
    save_schema(schema)
    return schema


def save_schema(schema: Dict[str, Any]) -> None:
    """Save schema to body-schema.json."""
    try:
        SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SCHEMA_PATH, "w", encoding="utf-8") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise OperationError("save_error", f"Failed to save schema: {e}")


def get_device_by_mac(schema: Dict[str, Any], mac: str) -> Optional[Dict[str, Any]]:
    """Find device by MAC address."""
    mac_normalized = mac.lower().replace("-", ":")
    for device in schema.get("devices", []):
        device_mac = device.get("mac", "")
        if device_mac and device_mac.lower().replace("-", ":") == mac_normalized:
            return device
    return None


def get_device_by_ip(schema: Dict[str, Any], ip: str) -> Optional[Dict[str, Any]]:
    """Find device by IP address (checks both ip and ips fields)."""
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


def get_device_by_name(schema: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    """Find device by name (case-insensitive partial match)."""
    name_lower = name.lower()
    for device in schema.get("devices", []):
        device_name = device.get("name", "").lower()
        if name_lower in device_name or device_name in name_lower:
            return device
    return None


def fuzzy_match_devices(devices: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    """Fuzzy match devices by name."""
    query_lower = query.lower()
    matches = []
    for device in devices:
        name = device.get("name", "").lower()
        # Partial match
        if query_lower in name or name in query_lower:
            matches.append(device)
    return matches


# --- query_device Handler ---

async def query_device_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Query devices from the body schema.

    - No params → return full schema
    - With params → return matched devices list
    """
    schema = load_schema()

    # No params = return full schema
    if not params:
        devices = schema.get("devices", [])

        # Calculate summary stats
        reachable_count = sum(1 for d in devices if d.get("status") == "reachable")
        unreachable_count = sum(1 for d in devices if d.get("status") == "unreachable")

        # Check freshness
        last_discovery = schema.get("discovery_meta", {}).get("last_full_discovery")
        freshness = "unknown"
        if last_discovery:
            try:
                last_dt = datetime.fromisoformat(last_discovery)
                age_hours = (datetime.now(CST) - last_dt).total_seconds() / 3600
                if age_hours < 1:
                    freshness = "fresh"
                elif age_hours < 24:
                    freshness = "recent"
                else:
                    freshness = "stale"
            except (ValueError, TypeError):
                pass

        return {
            "status": "success",
            "schema": schema,
            "summary": {
                "device_count": len(devices),
                "reachable": reachable_count,
                "unreachable": unreachable_count,
                "unknown": len(devices) - reachable_count - unreachable_count,
                "freshness": freshness
            }
        }

    # With params = filter devices
    devices = schema.get("devices", [])
    filtered = devices.copy()

    # Filter by name (fuzzy match)
    if params.get("name"):
        filtered = fuzzy_match_devices(filtered, params["name"])

    # Filter by IP (exact match)
    if params.get("ip"):
        ip = params["ip"]
        filtered = [d for d in filtered if (
            d.get("ip") == ip or
            ip in d.get("ips", []) or
            d.get("primary_ip") == ip
        )]

    # Filter by capability
    if params.get("capability"):
        cap = params["capability"].lower()
        filtered = [d for d in filtered if cap in [c.lower() for c in d.get("capabilities", [])]]

    # Filter by type
    if params.get("type"):
        dtype = params["type"].lower()
        filtered = [d for d in filtered if d.get("type", "").lower() == dtype]

    # Filter by status
    if params.get("status"):
        status = params["status"].lower()
        filtered = [d for d in filtered if d.get("status", "").lower() == status]

    return {
        "status": "success",
        "query": params,
        "devices": filtered,
        "count": len(filtered),
        "total": len(devices)
    }


# --- learn_device Handler ---

# IP address regex
IP_PATTERN = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
)

# Device type keywords mapping
DEVICE_TYPE_KEYWORDS: Dict[str, str] = {
    # Network devices
    "路由器": "router", "router": "router",
    "交换机": "switch", "switch": "switch",
    "网关": "gateway", "gateway": "gateway",
    "防火墙": "firewall", "firewall": "firewall",

    # Storage
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

    # Multimedia
    "摄像头": "camera", "相机": "camera", "camera": "camera",
    "打印机": "printer", "printer": "printer",

    # Inference
    "推理服务器": "inference_server",
    "ollama": "inference_server", "Ollama": "inference_server",

    # Mobile
    "手机": "phone", "iphone": "phone", "iPhone": "phone",
    "安卓": "phone", "android": "phone",
    "平板": "tablet", "ipad": "tablet", "iPad": "tablet",

    # Desktop
    "笔记本": "laptop", "macbook": "laptop", "MacBook": "laptop",
    "台式机": "desktop", "电脑": "desktop", "pc": "desktop", "PC": "desktop",
}

# Capability keywords mapping
CAPABILITY_KEYWORDS: Dict[str, str] = {
    "拍照": "camera", "录像": "camera", "摄像头": "camera", "相机": "camera",
    "SSH": "ssh", "ssh": "ssh",
    "HTTP": "http", "http": "http", "网页": "http", "Web": "http", "web": "http",
    "Ollama": "ollama", "ollama": "ollama",
    "推理": "inference", "LLM": "inference", "llm": "inference", "模型": "inference",
    "ComfyUI": "image_gen", "comfyui": "image_gen",
    "生图": "image_gen", "画图": "image_gen", "AI画": "image_gen",
    "Stable Diffusion": "image_gen",
    "虚拟机": "virtualization", "VM": "virtualization",
    "Docker": "docker", "docker": "docker", "容器": "docker",
    "存储": "storage", "NAS": "storage", "nas": "storage", "共享": "smb",
    "GPU": "gpu", "gpu": "gpu", "显卡": "gpu",
    "CUDA": "cuda", "cuda": "cuda", "VRAM": "vram",
    "音频": "audio", "麦克风": "audio", "音响": "audio",
}


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


def get_mac_for_ip(ip: str) -> Optional[str]:
    """Try to get MAC address for an IP using ARP."""
    try:
        # Try ARP table
        result = subprocess.run(
            ["arp", "-n", ip],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Parse ARP output
            # macOS: "hostname (192.168.5.1) at aa:bb:cc:dd:ee:ff on en0"
            # Linux: "192.168.5.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"
            output = result.stdout
            # Look for MAC pattern
            mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', output)
            if mac_match:
                return mac_match.group(0).lower().replace("-", ":")
    except Exception:
        pass
    return None


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
    """
    Update existing device or add new one using MAC-based identity.

    Args:
        schema: The body schema
        ip: Device IP address
        mac: Device MAC address (if known)
        dtype: Device type
        name: Device name
        capabilities: List of capabilities
        discovered: Whether this was auto-discovered
        source: Source of this information

    Returns:
        Tuple of (action, device) where action is "added" or "updated"
    """
    devices = schema.setdefault("devices", [])
    now = datetime.now(CST).isoformat()

    # Try to find existing device
    existing = None

    # 1. Try to find by MAC (if provided)
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


async def learn_device_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Learn device information from conversation text.

    Extracts IP addresses, device types, and capabilities from natural language.
    """
    text = params.get("text")
    if not text:
        raise OperationError("invalid_params", "Missing required parameter: text")

    # Parse text
    context = params.get("context", "")
    combined_text = f"{text} {context}"

    # Extract IPs
    ips = extract_ips(combined_text)
    if params.get("ip"):
        if params["ip"] not in ips:
            ips.insert(0, params["ip"])

    # Extract device types
    device_types = extract_device_types(combined_text)
    if params.get("type"):
        device_types = [params["type"]]

    # Extract capabilities
    capabilities = extract_capabilities(combined_text)
    if params.get("capabilities"):
        capabilities = params["capabilities"].split(",")

    # Infer device name
    device_name = params.get("name") or infer_device_name(combined_text, ips[0] if ips else None)

    # Determine confidence
    confidence = "low"
    if ips and device_types:
        confidence = "high"
    elif ips or device_types:
        confidence = "medium"

    # Dry run = just return parsed info
    if params.get("dry_run"):
        return {
            "status": "success",
            "dry_run": True,
            "parsed": {
                "ips": ips,
                "device_types": device_types,
                "capabilities": capabilities,
                "device_name": device_name,
                "confidence": confidence
            }
        }

    # No IPs found
    if not ips:
        return {
            "status": "success",
            "parsed": {
                "ips": [],
                "device_types": device_types,
                "capabilities": capabilities,
                "device_name": device_name,
                "confidence": confidence
            },
            "message": "No IP addresses found in text"
        }

    # Load schema and process each IP
    schema = load_schema()
    learned_devices = []
    actions = []

    for ip in ips:
        dtype = device_types[0] if device_types else None
        caps = capabilities

        # Try to get MAC address
        mac = get_mac_for_ip(ip)

        action, device = update_or_add_device(
            schema=schema,
            ip=ip,
            mac=mac,
            dtype=dtype,
            name=device_name,
            capabilities=caps,
            discovered=False,
            source="passive_learning"
        )

        learned_devices.append(device)
        actions.append(action)

    # Save schema
    schema["discovery_meta"]["last_passive_learning"] = datetime.now(CST).isoformat()
    save_schema(schema)

    # Log operation for each device
    for action, device in zip(actions, learned_devices):
        log_operation(
            action=f"device-{action}",
            target=device.get("primary_ip") or device.get("ip") or str(device.get("ips", ["?"])[0]),
            result="success",
            detail=f"{device.get('name', '?')} ({device.get('type', '?')}) - passive_learning"
        )

    return {
        "status": "success",
        "learned": {
            "parsed": {
                "ips": ips,
                "device_types": device_types,
                "capabilities": capabilities,
                "device_name": device_name,
                "confidence": confidence
            },
            "devices": learned_devices,
            "actions": actions
        },
        "devices_found": len(learned_devices),
        "confidence": confidence
    }


# --- Operation Definitions (Contract) ---

operations = [
    {
        "name": "query_device",
        "description": "Query devices from body schema. No params returns full schema. With params (name, ip, capability, type, status) returns filtered devices list. Name uses fuzzy match, IP uses exact match.",
        "params": {
            "name": {
                "type": "string",
                "description": "Device name (fuzzy match)",
                "required": False
            },
            "ip": {
                "type": "string",
                "description": "Device IP address (exact match)",
                "required": False
            },
            "capability": {
                "type": "string",
                "description": "Filter by capability (ssh, cuda, inference, etc.)",
                "required": False
            },
            "type": {
                "type": "string",
                "description": "Device type (server, vm, hypervisor, nas, docker_host, inference_server, etc.)",
                "required": False
            },
            "status": {
                "type": "string",
                "description": "Device status (reachable, unreachable, unknown, auth_required)",
                "required": False
            }
        },
        "handler": query_device_handler
    },
    {
        "name": "learn_device",
        "description": "Learn device information from conversation text. Extracts IP addresses, device types, and capabilities from natural language. Automatically updates body-schema.json.",
        "params": {
            "text": {
                "type": "string",
                "description": "User's conversation text to parse for device information",
                "required": True
            },
            "context": {
                "type": "string",
                "description": "Additional context about the conversation",
                "required": False
            },
            "ip": {
                "type": "string",
                "description": "Explicitly specify IP (overrides extraction)",
                "required": False
            },
            "type": {
                "type": "string",
                "description": "Explicitly specify device type (router, server, nas, hypervisor, vm, etc.)",
                "required": False
            },
            "name": {
                "type": "string",
                "description": "Explicitly specify device name",
                "required": False
            },
            "capabilities": {
                "type": "string",
                "description": "Comma-separated capabilities (camera, ssh, http, inference, image_gen, etc.)",
                "required": False
            },
            "dry_run": {
                "type": "boolean",
                "description": "Preview mode: parse without updating schema",
                "required": False
            }
        },
        "handler": learn_device_handler
    }
]


def get_operation(name: str) -> Optional[Dict[str, Any]]:
    """Get operation by name."""
    for op in operations:
        if op["name"] == name:
            return op
    return None


def list_operations() -> List[Dict[str, Any]]:
    """List all operations."""
    return operations
