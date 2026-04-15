#!/usr/bin/env python3
"""
merge-schema.py — Phase 3: Schema 自动合并
读取发现脚本的缓存结果，合并入 body-schema.json
通用设计：不绑定特定设备类型（PVE/NAS/Docker/ESP32 都行）

合并规则：
1. 自动发现的设备 → 新增或更新（标记 discovered: true）
2. 手动配置的设备 → 保留不动，只更新 status
3. 缓存中存在但本次未发现 → 标记 status: unreachable，不删除
4. 敏感信息（密码）→ 不写入 schema

输出缓存：发现脚本的 stdout 自动保存到 .cache/ 目录，本脚本优先读缓存。
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
CACHE_DIR = SKILL_DIR / ".cache"

CST = timezone(timedelta(hours=8))


def run_script(name, timeout=30):
    """运行一个 discover 脚本，返回 stdout，同时缓存到 .cache/"""
    script = SCRIPTS_DIR / name
    if not script.exists():
        return ""
    try:
        result = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=timeout
        )
        # 缓存输出
        CACHE_DIR.mkdir(exist_ok=True)
        cache_file = CACHE_DIR / f"{name}.stdout"
        with open(cache_file, "w") as f:
            f.write(result.stdout)
        return result.stdout
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"  ⚠️ {name} 失败: {e}", file=sys.stderr)
        return ""


def read_cached(script_name):
    """读取脚本的缓存输出，无缓存则返回空字符串"""
    cache_file = CACHE_DIR / f"{script_name}.stdout"
    if cache_file.exists():
        return cache_file.read_text()
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
    """读取 discover-self.sh 缓存，解析本机信息"""
    output = read_cached("discover-self.sh")
    if not output:
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


def parse_network_output(output):
    """解析 discover-network.sh 的输出，返回 {ip: {ports, services}}"""
    devices_by_ip = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] == "IP" or parts[0] == "----" or parts[0].startswith("("):
            continue
        ip, port, service = parts[0], parts[1], parts[2]
        if ip not in devices_by_ip:
            devices_by_ip[ip] = {"ports": [], "services": []}
        try:
            devices_by_ip[ip]["ports"].append(int(port))
        except ValueError:
            continue
        devices_by_ip[ip]["services"].append(service)
    return devices_by_ip


def get_local_ips():
    """获取本机所有 IP"""
    my_ips = set()
    try:
        my_ips_raw = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
        for line in my_ips_raw.splitlines():
            if "inet " in line and "127.0.0.1" not in line:
                ip = line.split()[1]
                my_ips.add(ip)
    except Exception:
        pass
    return my_ips


def guess_device_type(ip, info):
    """根据端口猜测设备类型和名称"""
    dtype = "unknown"
    name = f"device-{ip}"
    ports = set(info["ports"])
    svcs = set(info["services"])
    
    if 8006 in ports:
        dtype = "hypervisor"
        name = f"PVE-{ip}"
    elif 5000 in ports or 5001 in ports:
        dtype = "nas"
        name = f"NAS-{ip}"
    elif 11434 in ports:
        dtype = "inference_server"
        name = f"Ollama-{ip}"
    elif "LM-Studio" in svcs:
        dtype = "inference_server"
        name = f"LM-Studio-{ip}"
    elif 8888 in ports:
        dtype = "inference_server"
        name = f"llama-cpp-{ip}"
    elif 8096 in ports or 32400 in ports:
        dtype = "media_server"
        name = f"MediaServer-{ip}"
    elif 9091 in ports or 8085 in ports:
        dtype = "download"
        name = f"Downloader-{ip}"
    elif 3000 in ports:
        dtype = "monitoring"
        name = f"Grafana-{ip}"
    elif 80 in ports or 443 in ports:
        dtype = "server"
        name = f"HTTP-{ip}"
    elif 22 in ports:
        dtype = "server"
        name = f"SSH-{ip}"
    elif 445 in ports or 139 in ports:
        dtype = "file_share"
        name = f"SMB-{ip}"
    elif 53 in ports:
        dtype = "dns"
        name = f"DNS-{ip}"
    
    return dtype, name


def discover_network_devices():
    """
    解析网络发现结果，返回设备列表。
    优先读缓存，缓存不存在则重新运行脚本。
    缓存 + 新结果合并（累积发现，不丢设备）。
    """
    my_ips = get_local_ips()
    all_devices_by_ip = {}
    
    # 1. 读旧缓存
    cached_output = read_cached("discover-network.sh")
    if cached_output:
        all_devices_by_ip.update(parse_network_output(cached_output))
    
    # 2. 运行新扫描（同时更新缓存）
    new_output = run_script("discover-network.sh", timeout=60)
    if new_output:
        new_devices = parse_network_output(new_output)
        # 合并：新增 IP 直接加，已有 IP 合并端口/服务
        for ip, info in new_devices.items():
            if ip in all_devices_by_ip:
                existing_ports = set(all_devices_by_ip[ip]["ports"])
                existing_svcs = set(all_devices_by_ip[ip]["services"])
                for p, s in zip(info["ports"], info["services"]):
                    if p not in existing_ports:
                        all_devices_by_ip[ip]["ports"].append(p)
                        all_devices_by_ip[ip]["services"].append(s)
            else:
                all_devices_by_ip[ip] = info
    
    # 3. 转为设备列表（跳过本机）
    devices = []
    for ip, info in all_devices_by_ip.items():
        if ip in my_ips:
            continue
        dtype, name = guess_device_type(ip, info)
        devices.append({
            "id": ip.replace(".", "-"),
            "type": dtype,
            "name": name,
            "ip": ip,
            "capabilities": info["services"],
            "ports": info["ports"],
            "safety_level": "read_only",
            "status": "reachable",
            "discovered": True,
        })
    
    return devices


def merge_schema(schema, self_info, reachable_status, inference_backends, network_devices=None):
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
    
    # 2. 合并设备：手动配置 + 旧发现 + 新发现
    existing = {d.get("id"): d for d in schema.get("devices", [])}
    merged_devices = []
    seen_ids = set()
    
    # 2a. 更新已有设备状态
    for dev_id, device in existing.items():
        ip = device.get("ip", "")
        device["status"] = reachable_status.get(ip, "unknown")
        merged_devices.append(device)
        seen_ids.add(dev_id)
    
    # 2b. 合并网络发现的新设备
    if network_devices:
        for dev in network_devices:
            dev_id = dev.get("id")
            if dev_id in seen_ids:
                # 已存在，更新 capabilities 和 status
                for existing_dev in merged_devices:
                    if existing_dev.get("id") == dev_id:
                        existing_dev["capabilities"] = dev.get("capabilities", existing_dev.get("capabilities", []))
                        existing_dev["ports"] = dev.get("ports", existing_dev.get("ports", []))
                        existing_dev["status"] = "reachable"
                        # 自动发现的设备可以更新名称/类型，手动配置的只更新状态
                        if existing_dev.get("discovered", True):
                            existing_dev["type"] = dev["type"]
                            existing_dev["name"] = dev["name"]
                        break
            else:
                merged_devices.append(dev)
                seen_ids.add(dev_id)
    
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
    print("1/6 读取 schema...")
    schema = load_schema()
    known_ips = [d.get("ip", "") for d in schema.get("devices", []) if d.get("ip")]
    print(f"   已有 {len(schema.get('devices', []))} 台设备" if known_ips else "   空 schema（首次运行）")
    
    # 2. 探测本机
    print("2/6 探测本机...")
    self_info = discover_self()
    if self_info:
        print(f"   {self_info.get('hostname', '?')} / {self_info.get('os', '?')}")
    
    # 3. 测试连通性
    print("3/6 测试连通性...")
    reachable = test_reachability(known_ips)
    for ip, status in reachable.items():
        icon = "✅" if status == "reachable" else "❌"
        print(f"   {icon} {ip} — {status}")
    
    # 4. 网络发现
    print("4/6 网络发现...")
    network_devices = discover_network_devices()
    print(f"   发现 {len(network_devices)} 台新设备")
    for d in network_devices:
        print(f"   📡 {d['name']} ({d['ip']}) — {d['type']}")
    
    # 5. 检测推理后端
    print("5/6 检测推理后端...")
    backends = detect_inference_backends()
    for b in backends:
        print(f"   {b['type']} ({b['url']}): {b['models_count']} models")
    if not backends:
        print("   无推理后端")
    
    # 6. 合并保存
    print("6/6 合并保存...")
    schema = merge_schema(schema, self_info, reachable, backends, network_devices)
    
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
