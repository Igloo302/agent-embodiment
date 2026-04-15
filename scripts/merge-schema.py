#!/usr/bin/env python3
"""
merge-schema.py — Phase 3: Schema 自动合并
运行发现脚本，结果合并入 body-schema.json
通用设计：不绑定特定设备类型（PVE/NAS/Docker/ESP32 都行）

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


def run_script(name, timeout=30):
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


def load_schema():
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


def discover_self():
    """运行 discover-self.sh，解析本机信息"""
    output = run_script("discover-self.sh", timeout=10)
    try:
        return json.loads(output.strip())
    except json.JSONDecodeError:
        return {}


def test_reachability(ips):
    """测试 IP 连通性"""
    status = {}
    for ip in ips:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-t", "2", ip],
                capture_output=True, timeout=5
            )
            status[ip] = "reachable" if result.returncode == 0 else "unreachable"
        except Exception:
            status[ip] = "unreachable"
    return status


def detect_inference_backends():
    """
    检测本机推理后端（通用，不绑定特定软件）
    支持：Ollama、vLLM、llama.cpp、LM Studio、任意 OpenAI 兼容 API
    """
    backends = []
    
    # Ollama
    try:
        resp = subprocess.run(
            ["curl", "-s", "--max-time", "3", "http://localhost:11434/api/tags"],
            capture_output=True, text=True, timeout=5
        )
        if resp.returncode == 0 and resp.stdout.strip():
            data = json.loads(resp.stdout)
            models = [m["name"] for m in data.get("models", [])]
            backends.append({
                "type": "ollama",
                "url": "http://localhost:11434",
                "models": models,
                "models_count": len(models)
            })
    except Exception:
        pass
    
    # vLLM / LM Studio / 任意 OpenAI 兼容
    for port in [8000, 1234, 8080]:
        try:
            resp = subprocess.run(
                ["curl", "-s", "--max-time", "2", f"http://localhost:{port}/v1/models"],
                capture_output=True, text=True, timeout=3
            )
            if resp.returncode == 0 and resp.stdout.strip():
                data = json.loads(resp.stdout)
                models = [m["id"] for m in data.get("data", [])]
                if models or "data" in data:
                    backends.append({
                        "type": f"openai-compat",
                        "url": f"http://localhost:{port}",
                        "models": models,
                        "models_count": len(models)
                    })
        except Exception:
            pass
    
    return backends


def merge_schema(schema, self_info, reachable_status, inference_backends):
    """合并所有发现结果到 schema"""
    
    # 1. 合并本机信息
    if self_info:
        schema["self"] = {
            k: self_info[k] for k in [
                "hostname", "os", "arch", "cpu", "memory_gb",
                "hermes_version", "hermes_path", "ip"
            ] if k in self_info
        }
        schema["self"]["discovered_at"] = datetime.now(CST).isoformat()
    
    # 2. 合并设备状态
    existing = {d.get("id"): d for d in schema.get("devices", [])}
    merged_devices = []
    
    for dev_id, device in existing.items():
        ip = device.get("ip", "")
        device["status"] = reachable_status.get(ip, "unknown")
        merged_devices.append(device)
    
    schema["devices"] = merged_devices
    
    # 3. 写入推理后端信息（到 services 或 self）
    if inference_backends:
        # 找本机设备或 self，写入推理能力
        if schema.get("self"):
            schema["self"]["inference_backends"] = inference_backends
    
    # 4. 更新元数据
    schema["discovery_meta"] = {
        "last_full_discovery": datetime.now(CST).isoformat(),
        "schema_version": schema.get("discovery_meta", {}).get("schema_version", "1.1")
    }
    
    return schema


def main():
    print("=== Schema 自动合并 ===")
    print()
    
    # 1. 读取现有 schema
    print("1/5 读取 schema...")
    schema = load_schema()
    known_ips = [d.get("ip", "") for d in schema.get("devices", []) if d.get("ip")]
    print(f"   已有 {len(schema.get('devices', []))} 台设备" if known_ips else "   空 schema（首次运行）")
    
    # 2. 探测本机
    print("2/5 探测本机...")
    self_info = discover_self()
    if self_info:
        print(f"   {self_info.get('hostname', '?')} / {self_info.get('os', '?')}")
    
    # 3. 测试连通性
    print("3/5 测试连通性...")
    reachable = test_reachability(known_ips)
    for ip, status in reachable.items():
        icon = "✅" if status == "reachable" else "❌"
        print(f"   {icon} {ip} — {status}")
    
    # 4. 检测推理后端
    print("4/5 检测推理后端...")
    backends = detect_inference_backends()
    for b in backends:
        print(f"   {b['type']} ({b['url']}): {b['models_count']} models")
    if not backends:
        print("   无推理后端")
    
    # 5. 合并保存
    print("5/5 合并保存...")
    schema = merge_schema(schema, self_info, reachable, backends)
    
    with open(SCHEMA_PATH, "w") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    
    print(f"✅ 已保存: {SCHEMA_PATH}")
    
    # 摘要
    print()
    for d in schema.get("devices", []):
        icon = "🟢" if d.get("status") == "reachable" else "🔴"
        disc = "auto" if d.get("discovered") else "manual"
        print(f"  {icon} {d.get('name', '?')} ({d.get('ip', '?')}) [{disc}]")


if __name__ == "__main__":
    main()
