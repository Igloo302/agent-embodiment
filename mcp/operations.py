#!/usr/bin/env python3
"""
operations.py — Contract-first operation definitions for Agent Embodiment MCP.
Single source of truth for all operations exposed via MCP.

Each operation defines:
- name: tool name
- description: what it does
- params: parameter definitions with types and descriptions
- handler: async function that executes the operation
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# --- Constants ---
SKILL_DIR = Path.home() / ".hermes/skills/agent-embodiment"
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
SCRIPTS_DIR = SKILL_DIR / "scripts"
CACHE_DIR = SKILL_DIR / ".cache"

CST = timezone(timedelta(hours=8))


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


# --- Helpers ---
def run_script(name: str, timeout: int = 30) -> str:
    """Run a discover script and cache output."""
    script = SCRIPTS_DIR / name
    if not script.exists():
        raise OperationError("script_not_found", f"Script not found: {name}")
    
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=timeout
        )
        # Cache output
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{name}.stdout"
        with open(cache_file, "w") as f:
            f.write(result.stdout)
        return result.stdout
    except subprocess.TimeoutExpired:
        raise OperationError("timeout", f"Script {name} timed out after {timeout}s")
    except Exception as e:
        raise OperationError("script_error", f"Script {name} failed: {e}")


def read_cached(script_name: str) -> str:
    """Read cached script output."""
    cache_file = CACHE_DIR / f"{script_name}.stdout"
    if cache_file.exists():
        return cache_file.read_text()
    return ""


def load_schema() -> Dict[str, Any]:
    """Load body-schema.json or return empty template."""
    if SCHEMA_PATH.exists():
        try:
            with open(SCHEMA_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            raise OperationError("schema_error", f"Schema corrupted: {e}")
    
    return {
        "self": {},
        "environment": {"timezone": "Asia/Shanghai", "networks": []},
        "devices": [],
        "services": [],
        "discovery_meta": {"schema_version": "1.1"}
    }


def save_schema(schema: Dict[str, Any]) -> None:
    """Save schema to body-schema.json."""
    try:
        with open(SCHEMA_PATH, "w") as f:
            json.dump(schema, f, indent=2, ensure_ascii=False)
    except Exception as e:
        raise OperationError("save_error", f"Failed to save schema: {e}")


def parse_json_output(output: str) -> Dict[str, Any]:
    """Parse JSON from script output, handling both JSON and text."""
    output = output.strip()
    if not output:
        return {}
    
    # Try direct JSON parse
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON from mixed output
    try:
        # Find first { and last }
        start = output.find("{")
        end = output.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(output[start:end])
    except (json.JSONDecodeError, ValueError):
        pass
    
    return {"raw_output": output}


# --- Operations ---

async def discover_self_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Discover local machine information."""
    output = run_script("discover-self.sh")
    data = parse_json_output(output)
    
    return {
        "status": "success",
        "self": data,
        "cached_at": datetime.now(CST).isoformat()
    }


async def discover_network_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Scan network for devices."""
    timeout = params.get("timeout", 60)
    output = run_script("discover-network.sh", timeout=timeout)
    
    return {
        "status": "success",
        "raw_output": output,
        "cached_at": datetime.now(CST).isoformat()
    }


async def discover_inference_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Discover GPU and inference capabilities."""
    output = run_script("discover-inference.sh")
    data = parse_json_output(output)
    
    return {
        "status": "success",
        "inference": data,
        "cached_at": datetime.now(CST).isoformat()
    }


async def discover_hardware_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Discover local hardware devices."""
    output = run_script("discover-hardware.sh")
    data = parse_json_output(output)
    
    return {
        "status": "success",
        "hardware": data,
        "cached_at": datetime.now(CST).isoformat()
    }


async def get_schema_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Read the current body schema."""
    schema = load_schema()
    
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
        "freshness": freshness,
        "device_count": len(schema.get("devices", [])),
        "service_count": len(schema.get("services", []))
    }


async def update_device_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Update a device in the schema."""
    ip = params.get("ip")
    if not ip:
        raise OperationError("invalid_params", "Missing required parameter: ip")
    
    # Build update command
    cmd = ["python3", str(SCRIPTS_DIR / "update-device.py"), ip]
    
    if params.get("type"):
        cmd.extend(["--type", params["type"]])
    if params.get("name"):
        cmd.extend(["--name", params["name"]])
    if params.get("ports"):
        cmd.extend(["--ports", params["ports"]])
    if params.get("status"):
        cmd.extend(["--status", params["status"]])
    if params.get("capabilities"):
        cmd.extend(["--capabilities", params["capabilities"]])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise OperationError("update_failed", f"Update failed: {result.stderr}")
        
        # Reload schema to confirm
        schema = load_schema()
        device = next((d for d in schema.get("devices", []) if d.get("ip") == ip), None)
        
        return {
            "status": "success",
            "device": device,
            "message": f"Device {ip} updated"
        }
    except subprocess.TimeoutExpired:
        raise OperationError("timeout", "Update timed out")
    except Exception as e:
        raise OperationError("update_error", str(e))


async def merge_schema_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Run full discovery and merge into schema."""
    force = params.get("force", False)
    
    # Check if we should skip (schema fresh < 1 hour)
    if not force:
        schema = load_schema()
        last_discovery = schema.get("discovery_meta", {}).get("last_full_discovery")
        if last_discovery:
            try:
                last_dt = datetime.fromisoformat(last_discovery)
                age_hours = (datetime.now(CST) - last_dt).total_seconds() / 3600
                if age_hours < 1:
                    return {
                        "status": "skipped",
                        "message": f"Schema is fresh ({age_hours:.1f}h old). Use force=true to override.",
                        "schema": schema
                    }
            except (ValueError, TypeError):
                pass
    
    # Run merge-schema.py
    try:
        result = subprocess.run(
            ["python3", str(SCRIPTS_DIR / "merge-schema.py")],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            raise OperationError("merge_failed", f"Merge failed: {result.stderr}")
        
        # Reload schema
        schema = load_schema()
        
        return {
            "status": "success",
            "message": "Schema merged successfully",
            "schema": schema,
            "device_count": len(schema.get("devices", [])),
            "service_count": len(schema.get("services", []))
        }
    except subprocess.TimeoutExpired:
        raise OperationError("timeout", "Merge timed out after 120s")
    except Exception as e:
        raise OperationError("merge_error", str(e))


async def verify_action_handler(params: Dict[str, Any]) -> Dict[str, Any]:
    """Verify an action's result."""
    action = params.get("action")
    target = params.get("target")
    
    if not action or not target:
        raise OperationError("invalid_params", "Missing required parameters: action, target")
    
    cmd = ["bash", str(SCRIPTS_DIR / "verify-action.sh"), action, target]
    
    if params.get("expected"):
        cmd.append(params["expected"])
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        data = parse_json_output(result.stdout)
        
        return {
            "status": "success",
            "verification": data,
            "passed": data.get("status") == "pass"
        }
    except subprocess.TimeoutExpired:
        raise OperationError("timeout", "Verification timed out")
    except Exception as e:
        raise OperationError("verify_error", str(e))


# --- Operation Definitions (Contract) ---

operations = [
    {
        "name": "discover_self",
        "description": "Discover local machine information (hostname, OS, CPU, memory, IP). Run discover-self.sh and return structured data.",
        "params": {},
        "handler": discover_self_handler
    },
    {
        "name": "discover_network",
        "description": "Scan network for devices using ping, port scan, and mDNS. Returns list of discovered devices.",
        "params": {
            "timeout": {
                "type": "number",
                "description": "Scan timeout in seconds (default: 60)",
                "required": False
            }
        },
        "handler": discover_network_handler
    },
    {
        "name": "discover_inference",
        "description": "Discover GPU, VRAM, and inference backends (Ollama, vLLM, llama.cpp, LM Studio).",
        "params": {},
        "handler": discover_inference_handler
    },
    {
        "name": "discover_hardware",
        "description": "Discover local hardware devices (audio, bluetooth, display, camera, USB, printer, storage).",
        "params": {},
        "handler": discover_hardware_handler
    },
    {
        "name": "get_schema",
        "description": "Read the current body-schema.json. Returns the full schema with freshness status.",
        "params": {},
        "handler": get_schema_handler
    },
    {
        "name": "update_device",
        "description": "Update a specific device in the schema by IP address.",
        "params": {
            "ip": {
                "type": "string",
                "description": "Device IP address",
                "required": True
            },
            "type": {
                "type": "string",
                "description": "Device type (server, vm, hypervisor, nas, docker_host, inference_server, etc.)",
                "required": False
            },
            "name": {
                "type": "string",
                "description": "Device name/hostname",
                "required": False
            },
            "ports": {
                "type": "string",
                "description": "Comma-separated list of open ports",
                "required": False
            },
            "status": {
                "type": "string",
                "description": "Device status (online, unreachable, auth_required)",
                "required": False
            },
            "capabilities": {
                "type": "string",
                "description": "Comma-separated capabilities (cuda, metal, vram_12gb, etc.)",
                "required": False
            }
        },
        "handler": update_device_handler
    },
    {
        "name": "merge_schema",
        "description": "Run full discovery (all scripts) and merge results into body-schema.json. Updates timestamp.",
        "params": {
            "force": {
                "type": "boolean",
                "description": "Force re-discovery even if schema is fresh (< 1 hour)",
                "required": False
            }
        },
        "handler": merge_schema_handler
    },
    {
        "name": "verify_action",
        "description": "Verify an action's result (e.g., VM running, SSH reachable, service up).",
        "params": {
            "action": {
                "type": "string",
                "description": "Action type: vm-running, ssh-reachable, service-up, ollama-up, process-running, disk-space, network-check",
                "required": True
            },
            "target": {
                "type": "string",
                "description": "Target (IP, URL, or process name)",
                "required": True
            },
            "expected": {
                "type": "string",
                "description": "Expected value (optional)",
                "required": False
            }
        },
        "handler": verify_action_handler
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
