#!/usr/bin/env python3
"""
merge-schema.py — Phase 3: Schema 自动合并
运行所有发现脚本，结果合并入 body-schema.json

合并规则：
1. 自动发现的设备 → 新增或更新（标记 discovered: true）
2. 手动配置的设备 → 保留不动，只更新 status
3. 缓存中存在但本次未发现 → 标记 status: unreachable，不删除
4. 敏感信息（密码）→ 不写入 schema
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_DIR = Path.home() / ".hermes/skills/agent-embodiment"
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
SCRIPTS_DIR = SKILL_DIR / "scripts"

CST = timezone(timedelta(hours=8))


def run_script(name: str, timeout: int = 30) -> str:
    """运行一个 discover 脚本，返回 stdout"""
    script = SCRIPTS_DIR / name
    if not script.exists():
        return ""
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"  ⚠️ {name} 失败: {e}", file=sys.stderr)
        return ""


def load_schema() -> dict:
    """读取现有 schema，不存在则返回空模板"""
    if SCHEMA_PATH.exists():
        try:
            with open(SCHEMA_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, Exception) as e:
            print(f"  ⚠️ schema 损坏，重建: {e}", file=sys.stderr)
    
    return {
        "self": {},
        "environment": {"timezone": "Asia/Shanghai", "networks": []},
        "devices": [],
        "services": [],
        "discovery_meta": {"schema_version": "1.1"}
    }


def discover_self() -> dict:
    """运行 discover-self.sh，解析本机信息"""
    output = run_script("discover-self.sh", timeout=10)
    try:
        # 输出是 JSON
        return json.loads(output.strip())
    except json.JSONDecodeError:
        return {}


def discover_inference() -> dict:
    """运行 discover-inference.sh，提取推理能力信息"""
    output = run_script("discover-inference.sh", timeout=30)
    info = {
        "gpu": [],
        "backends": [],
        "models": [],
    }
    
    # 从输出中提取关键信息
    in_gpu = False
    in_backend = False
    
    for line in output.split("\n"):
        line = line.strip()
        if line == "--- 本机 GPU ---":
            in_gpu = True
            in_backend = False
            continue
        elif line == "--- 推理后端 ---":
            in_gpu = False
            in_backend = True
            continue
        elif line.startswith("---"):
            in_gpu = False
            in_backend = False
            continue
        
        if in_gpu and line.startswith("backend:"):
            info["gpu"].append({"description": line})
        elif in_backend and "running" in line:
            info["backends"].append(line)
    
    return info


def discover_network_reachable(known_ips: list) -> dict:
    """测试已知 IP 的连通性"""
    status = {}
    for ip in known_ips:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-t", "2", ip],
                capture_output=True, timeout=5
            )
            status[ip] = "reachable" if result.returncode == 0 else "unreachable"
        except Exception:
            status[ip] = "unreachable"
    return status


def merge_self(schema: dict, self_info: dict) -> dict:
    """合并本机信息"""
    if not self_info:
        return schema
    
    schema["self"] = {
        "hostname": self_info.get("hostname", schema.get("self", {}).get("hostname", "")),
        "os": self_info.get("os", ""),
        "arch": self_info.get("arch", ""),
        "cpu": self_info.get("cpu", ""),
        "memory_gb": self_info.get("memory_gb", 0),
        "hermes_version": self_info.get("hermes_version", ""),
        "hermes_path": self_info.get("hermes_path", ""),
        "ip": self_info.get("ip", []),
        "discovered_at": datetime.now(CST).isoformat()
    }
    return schema


def merge_devices(schema: dict, reachable: dict, discovered_devices: list = None) -> dict:
    """
    合并设备状态：
    - discovered=true 的设备：用新数据更新
    - discovered=false 的设备：保留，只更新 status
    - 未发现的设备：标记 unreachable
    - 新设备：新增
    """
    existing_devices = {d.get("id"): d for d in schema.get("devices", [])}
    discovered_map = {}
    if discovered_devices:
        discovered_map = {d.get("id"): d for d in discovered_devices}
    
    merged = []
    
    # 处理已有设备
    for dev_id, device in existing_devices.items():
        ip = device.get("ip", "")
        
        if device.get("discovered", False):
            # 自动发现的设备：用新数据覆盖
            if dev_id in discovered_map:
                new_device = discovered_map[dev_id]
                new_device["status"] = reachable.get(ip, "unknown")
                merged.append(new_device)
            else:
                # 本次未发现 → unreachable
                device["status"] = "unreachable"
                merged.append(device)
        else:
            # 手动配置的设备：保留，只更新 status
            device["status"] = reachable.get(ip, "unknown")
            merged.append(device)
    
    # 新发现的设备
    for dev_id, device in (discovered_map or {}).items():
        if dev_id not in existing_devices:
            device["discovered"] = True
            device["status"] = reachable.get(device.get("ip", ""), "unknown")
            merged.append(device)
    
    schema["devices"] = merged
    return schema


def update_meta(schema: dict) -> dict:
    """更新 discovery_meta"""
    schema["discovery_meta"] = {
        "last_full_discovery": datetime.now(CST).isoformat(),
        "schema_version": schema.get("discovery_meta", {}).get("schema_version", "1.1")
    }
    return schema


def save_schema(schema: dict):
    """写入 body-schema.json"""
    with open(SCHEMA_PATH, "w") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"✅ Schema 已更新: {SCHEMA_PATH}")


def main():
    print("=== Phase 3: Schema 自动合并 ===")
    print()
    
    # 1. 读取现有 schema
    print("1️⃣ 读取现有 schema...")
    schema = load_schema()
    existing_ips = []
    for d in schema.get("devices", []):
        if d.get("ip"):
            existing_ips.append(d["ip"])
    print(f"   已有 {len(schema.get('devices', []))} 台设备")
    
    # 2. 运行 discover-self
    print("2️⃣ 探测本机信息...")
    self_info = discover_self()
    if self_info:
        schema = merge_self(schema, self_info)
        print(f"   hostname: {self_info.get('hostname', '?')}")
    
    # 3. 测试已知设备连通性
    print("3️⃣ 测试设备连通性...")
    reachable = discover_network_reachable(existing_ips)
    for ip, status in reachable.items():
        icon = "✅" if status == "reachable" else "❌"
        print(f"   {icon} {ip} — {status}")
    
    # 4. 探测推理能力（更新到对应设备的 notes）
    print("4️⃣ 探测推理能力...")
    inference = discover_inference()
    if inference.get("backends"):
        print(f"   发现 {len(inference['backends'])} 个推理后端")
    
    # 5. 合并设备状态
    print("5️⃣ 合并设备状态...")
    schema = merge_devices(schema, reachable)
    
    # 6. 更新元数据
    schema = update_meta(schema)
    
    # 7. 保存
    print("6️⃣ 保存...")
    save_schema(schema)
    
    # 输出摘要
    print()
    print("--- 合并摘要 ---")
    print(f"设备总数: {len(schema.get('devices', []))}")
    for d in schema.get("devices", []):
        status_icon = "🟢" if d.get("status") == "reachable" else "🔴" if d.get("status") == "unreachable" else "⚪"
        disc = "auto" if d.get("discovered") else "manual"
        print(f"  {status_icon} {d.get('name', '?')} ({d.get('ip', '?')}) [{disc}] — {d.get('status', '?')}")


if __name__ == "__main__":
    main()
