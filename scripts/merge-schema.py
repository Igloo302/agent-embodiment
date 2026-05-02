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

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

SKILL_DIR = Path.home() / ".hermes/skills/agent-embodiment"
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
SCRIPTS_DIR = SKILL_DIR / "scripts"
CACHE_DIR = SKILL_DIR / ".cache"
LOG_OPERATION_SCRIPT = SCRIPTS_DIR / "log-operation.py"

CST = timezone(timedelta(hours=8))


def log_operation(action: str, target: str, result: str, detail: str = None, reason: str = None):
    """调用 log-operation.py 记录操作历史（使用 subprocess，不 import）"""
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
        pass  # 日志记录失败不影响主流程


def run_script(name, timeout=30):
    """运行一个 discover 脚本，返回 stdout，同时缓存到 .cache/"""
    script = SCRIPTS_DIR / name
    
    # 优先使用 Python 版本的网络扫描
    if name == "discover-network.sh":
        py_script = SCRIPTS_DIR / "discover-network.py"
        if py_script.exists():
            script = py_script
            timeout = max(timeout, 120)  # 网络扫描需要更长超时
    
    if not script.exists():
        return ""
    try:
        # Python 脚本用 python3，shell 脚本用 bash
        if script.suffix == ".py":
            result = subprocess.run(
                ["python3", str(script)],
                capture_output=True, text=True, timeout=timeout
            )
        else:
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


def get_device_by_ip(schema, ip):
    """根据 IP 查找设备，返回设备对象或 None"""
    for device in schema.get("devices", []):
        if device.get("ip") == ip:
            return device
        # 也检查 ips 数组（多 IP 设备）
        if ip in device.get("ips", []):
            return device
    return None


def supplement_from_memory(schema, memory_devices=None):
    """
    从 Agent 传入的记忆设备列表补充到 schema。
    
    Agent 会在调用 merge-schema.py 之前，先从自己的记忆中提取设备信息，
    然后通过 --memory-devices 参数传给本脚本。
    
    这样做的好处：
    - Agent 可以灵活决定从哪里读取记忆（MEMORY.md / Hindsight / 其他）
    - 脚本不依赖特定的记忆存储格式
    - 保持职责分离
    
    Args:
        schema: body schema
        memory_devices: Agent 传入的设备列表，格式：
            [
                {"ip": "192.168.5.100", "type": "hypervisor", "name": "PVE", "capabilities": ["ssh"]},
                ...
            ]
    """
    if not memory_devices:
        return schema
    
    supplemented = []
    for device in memory_devices:
        ip = device.get("ip")
        if not ip:
            continue
        
        # 过滤无效 IP
        last_octet = int(ip.split('.')[-1])
        if last_octet == 0 or last_octet == 255:
            continue
        
        # 检查是否已存在
        if get_device_by_ip(schema, ip):
            continue
        
        # 创建设备记录
        new_device = {
            "id": ip.replace(".", "-"),
            "type": device.get("type", "unknown"),
            "name": device.get("name", f"memory-{ip}"),
            "ip": ip,
            "capabilities": device.get("capabilities", []),
            "safety_level": "read_only",
            "status": "unknown",
            "discovered": False,
            "source": "memory_supplement"
        }
        
        schema["devices"].append(new_device)
        supplemented.append(new_device)
    
    if supplemented:
        print(f"   从 Memory 补充 {len(supplemented)} 台设备")
        for d in supplemented:
            print(f"   📝 {d['name']} ({d['ip']}) — {d['type']}")
    
    return schema


def parse_network_output(output):
    """解析 discover-network.sh 的输出，返回 {mac: {ips, ports, services}} 或 {ip: {mac, ports, services}}"""
    # 新格式: IP MAC Port Service Status
    # 支持两种格式：
    # 1. 新格式（带 MAC）: IP MAC Port Service Status
    # 2. 旧格式（无 MAC）: IP Port Service Status
    
    devices_by_mac = {}  # MAC -> {ips: set, ports: list, services: list}
    devices_by_ip = {}   # IP -> {mac, ports, services} (fallback for no MAC)
    
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4 or parts[0] == "IP" or parts[0] == "----" or parts[0].startswith("("):
            continue
        
        # 检测格式：新格式有 5 列，旧格式有 4 列
        if len(parts) >= 5:
            # 新格式: IP MAC Port Service Status
            ip, mac, port, service = parts[0], parts[1], parts[2], parts[3]
            # 检查第二列是否是 MAC 地址
            if ":" in mac and len(mac) == 17:
                # 是 MAC 地址
                pass
            else:
                # 可能是旧格式，重新解析
                ip, port, service = parts[0], parts[1], parts[2]
                mac = None
        else:
            # 旧格式: IP Port Service Status
            ip, port, service = parts[0], parts[1], parts[2]
            mac = None
        
        try:
            port_int = int(port)
        except ValueError:
            continue
        
        # 如果有 MAC，按 MAC 分组
        if mac and mac != "":
            if mac not in devices_by_mac:
                devices_by_mac[mac] = {"ips": set(), "ports": [], "services": []}
            devices_by_mac[mac]["ips"].add(ip)
            devices_by_mac[mac]["ports"].append(port_int)
            devices_by_mac[mac]["services"].append(service)
        else:
            # 无 MAC，按 IP 分组
            if ip not in devices_by_ip:
                devices_by_ip[ip] = {"mac": None, "ports": [], "services": []}
            devices_by_ip[ip]["ports"].append(port_int)
            devices_by_ip[ip]["services"].append(service)
    
    # 合并结果：优先使用 MAC 分组
    result = {}
    for mac, info in devices_by_mac.items():
        result[mac] = {
            "mac": mac,
            "ips": list(info["ips"]),
            "primary_ip": min(info["ips"]) if info["ips"] else None,  # 最小 IP 作为主 IP
            "ports": info["ports"],
            "services": info["services"]
        }
    
    # 无 MAC 的设备按 IP
    for ip, info in devices_by_ip.items():
        result[ip] = {
            "mac": None,
            "ips": [ip],
            "primary_ip": ip,
            "ports": info["ports"],
            "services": info["services"]
        }
    
    return result


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
    """根据端口猜测设备类型、名称、操作系统和硬件能力
    
    Returns:
        Tuple of (dtype, name, os, capabilities)
    """
    dtype = "unknown"
    name = f"device-{ip}"
    os_type = None
    capabilities = set()
    ports = set(info["ports"])
    svcs = set(info["services"])
    
    # === 操作系统推断 ===
    # Windows: RDP(3389), SMB(445/139), WinRM(5985/5986)
    if 3389 in ports or 5985 in ports or 5986 in ports:
        os_type = "windows"
    # NAS (Synology/QNAP): DSM(5000/5001), NFS(2049)
    elif 5000 in ports or 5001 in ports:
        os_type = "dsm"  # Synology DiskStation Manager
    # Hypervisor: PVE(8006), ESXi(443/902)
    elif 8006 in ports:
        os_type = "proxmox"
    # Linux: SSH(22), HTTP(80/443) - 默认假设
    elif 22 in ports:
        os_type = "linux"
    
    # === 设备类型和硬件能力推断 ===
    if 8006 in ports:
        dtype = "hypervisor"
        name = f"PVE-{ip}"
        capabilities.update(["vm_host", "proxmox", "ssh"])
    elif 5000 in ports or 5001 in ports:
        dtype = "nas"
        name = f"NAS-{ip}"
        capabilities.update(["storage", "file_share", "nfs" if 2049 in ports else None])
        capabilities.discard(None)
    elif 11434 in ports:
        dtype = "inference_server"
        name = f"Ollama-{ip}"
        capabilities.update(["cuda", "inference", "ollama", "ssh"])
    elif "LM-Studio" in svcs or 1234 in ports:
        dtype = "inference_server"
        name = f"LM-Studio-{ip}"
        capabilities.update(["cuda", "inference", "lm-studio"])
    elif 8888 in ports:
        dtype = "inference_server"
        name = f"llama-cpp-{ip}"
        capabilities.update(["inference", "llama-cpp"])
    elif "vLLM" in svcs or 8000 in ports:
        # vLLM 通常在端口 8000 提供 OpenAI 兼容 API
        dtype = "inference_server"
        name = f"vLLM-{ip}"
        capabilities.update(["inference", "vllm"])
    elif 8096 in ports:
        dtype = "media_server"
        name = f"Jellyfin-{ip}"
        capabilities.update(["media", "jellyfin"])
    elif 32400 in ports:
        dtype = "media_server"
        name = f"Plex-{ip}"
        capabilities.update(["media", "plex"])
    elif 9091 in ports or 8085 in ports:
        dtype = "download"
        name = f"Downloader-{ip}"
    elif 3000 in ports:
        dtype = "monitoring"
        name = f"Grafana-{ip}"
        capabilities.update(["monitoring", "grafana"])
    elif 80 in ports or 443 in ports:
        dtype = "server"
        name = f"HTTP-{ip}"
        capabilities.update(["http", "ssh"] if 22 in ports else ["http"])
    elif 22 in ports:
        dtype = "server"
        name = f"SSH-{ip}"
        capabilities.add("ssh")
    elif 445 in ports or 139 in ports:
        dtype = "file_share"
        name = f"SMB-{ip}"
        capabilities.update(["file_share", "smb"])
        if os_type is None:
            os_type = "windows"  # SMB 通常是 Windows
    elif 53 in ports:
        dtype = "dns"
        name = f"DNS-{ip}"
        capabilities.add("dns")
    
    # === 补充能力推断 ===
    # 如果有 SSH 端口，添加 ssh 能力
    if 22 in ports:
        capabilities.add("ssh")
    
    # NFS 端口
    if 2049 in ports:
        capabilities.update(["storage", "nfs"])
    
    # Docker 端口
    if 2375 in ports or 2376 in ports:
        capabilities.add("docker")
    
    return dtype, name, os_type, sorted(capabilities)


def discover_network_devices():
    """
    解析网络发现结果，返回设备列表。
    优先读缓存，缓存不存在则重新运行脚本。
    缓存 + 新结果合并（累积发现，不丢设备）。
    
    v1.1: 使用 MAC 地址作为设备唯一标识
    """
    my_ips = get_local_ips()
    all_devices_by_key = {}  # key 可以是 MAC 或 IP（无 MAC 时）
    
    # 1. 读旧缓存
    cached_output = read_cached("discover-network.sh")
    if cached_output:
        all_devices_by_key.update(parse_network_output(cached_output))
    
    # 2. 运行新扫描（同时更新缓存）
    # 网络扫描可能需要 4-5 分钟（393 IP × 27 端口）
    new_output = run_script("discover-network.sh", timeout=360)
    if new_output:
        new_devices = parse_network_output(new_output)
        # 合并：按 key（MAC 或 IP）合并
        for key, info in new_devices.items():
            if key in all_devices_by_key:
                # 已存在，合并端口/服务/IP
                existing = all_devices_by_key[key]
                existing_ports = set(existing["ports"])
                existing_svcs = set(existing["services"])
                existing_ips = set(existing.get("ips", []))
                
                for p, s in zip(info["ports"], info["services"]):
                    if p not in existing_ports:
                        existing["ports"].append(p)
                        existing["services"].append(s)
                
                # 合并 IP 地址
                for ip in info.get("ips", []):
                    if ip not in existing_ips:
                        existing_ips.add(ip)
                        existing["ips"].append(ip)
            else:
                all_devices_by_key[key] = info
    
    # 3. 转为设备列表（跳过本机）
    devices = []
    now = datetime.now(CST).isoformat()
    
    for key, info in all_devices_by_key.items():
        # 获取主 IP
        primary_ip = info.get("primary_ip")
        ips = info.get("ips", [])
        mac = info.get("mac")
        
        # 跳过本机 IP
        if all(ip in my_ips for ip in ips):
            continue
        
        # 选择一个 IP 用于显示
        display_ip = primary_ip or (ips[0] if ips else key)
        
        # 推断设备类型、名称、操作系统和硬件能力
        dtype, name, os_type, inferred_caps = guess_device_type(display_ip, info)
        
        # 合并推断的能力和发现的服务
        all_caps = set(inferred_caps) | set(info.get("services", []))
        
        # 生成设备 ID：优先使用 MAC
        if mac:
            device_id = mac
        else:
            device_id = key.replace(".", "-") if "." in key else key
        
        device = {
            "id": device_id,
            "mac": mac,
            "type": dtype,
            "name": name,
            "ip": primary_ip or (ips[0] if ips else display_ip),
            "ips": ips,
            "primary_ip": primary_ip,
            "capabilities": sorted(all_caps),
            "ports": info["ports"],
            "safety_level": "read_only",
            "status": "reachable",
            "discovered": True,
            "source": "network_scan",
            "last_seen": now,
        }
        
        # 添加 OS 字段（如果推断出）
        if os_type:
            device["os"] = os_type
        
        devices.append(device)
    
    return devices


def _merge_device_fields(existing, new):
    """将新设备数据合并到已有设备，保留旧数据不丢"""
    existing["capabilities"] = new.get("capabilities", existing.get("capabilities", []))
    existing["ports"] = new.get("ports", existing.get("ports", []))
    existing["status"] = "reachable"
    existing["last_seen"] = new.get("last_seen", existing.get("last_seen"))
    existing["source"] = new.get("source", existing.get("source"))
    
    # 更新 MAC 和 IP 信息
    if new.get("mac"):
        existing["mac"] = new["mac"]
    if new.get("ips"):
        existing["ips"] = new["ips"]
    if new.get("primary_ip"):
        existing["primary_ip"] = new["primary_ip"]
    
    # 更新 OS 信息（如果新数据有）
    if new.get("os"):
        existing["os"] = new["os"]
    
    # 自动发现的设备可以更新名称/类型，手动配置的只更新状态
    if existing.get("discovered", True):
        existing["type"] = new.get("type", existing.get("type"))
        existing["name"] = new.get("name", existing.get("name"))


def merge_schema(schema, self_info, reachable_status, inference_backends, network_devices=None,
                 inference_caps=None, hardware_caps=None):
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
    
    # 2a. 预清理：移除已被 MAC-based 设备替代的旧 IP-based 设备
    # 建立 MAC -> device 索引
    mac_to_dev = {}
    for dev_id, device in existing.items():
        if device.get("mac"):
            mac_to_dev[device["mac"]] = device
    
    # 找到旧 IP-based 设备（无 MAC）中，有同名 MAC-based 设备的，移除旧的
    cleanup_ids = set()
    for dev_id, device in existing.items():
        # 过滤网段地址和广播地址
        old_ip = device.get("ip") or ""
        if old_ip:
            try:
                last_octet = int(old_ip.split('.')[-1])
                if last_octet == 0 or last_octet == 255:
                    cleanup_ids.add(dev_id)
                    continue
            except (ValueError, IndexError):
                pass
        
        if not device.get("mac"):
            old_name = device.get("name")
            if old_name and any(
                d.get("name") == old_name
                for d in mac_to_dev.values()
            ):
                cleanup_ids.add(dev_id)
                continue
            # 检查是否有 IP 匹配的 MAC-based 设备
            if old_ip and any(
                old_ip in d.get("ips", [])
                for d in mac_to_dev.values()
            ):
                cleanup_ids.add(dev_id)
    
    if cleanup_ids:
        print(f"   清理 {len(cleanup_ids)} 个已被 MAC 替代的旧设备")
        for cid in cleanup_ids:
            existing.pop(cid, None)
    
    # 2b. 更新已有设备状态
    for dev_id, device in existing.items():
        ip = device.get("ip", "")
        device["status"] = reachable_status.get(ip, "unknown")
        merged_devices.append(device)
        seen_ids.add(dev_id)
    
    # 2b. 合并网络发现的新设备
    if network_devices:
        # 先建立 IP -> existing device 的索引（用于 ID 迁移）
        ip_to_existing = {}
        for existing_dev in merged_devices:
            old_ip = existing_dev.get("ip") or existing_dev.get("primary_ip")
            if old_ip:
                ip_to_existing[old_ip] = existing_dev
            # 也检查 ips 数组
            for old_ip in existing_dev.get("ips", []):
                ip_to_existing[old_ip] = existing_dev
        
        for dev in network_devices:
            dev_id = dev.get("id")
            if dev_id in seen_ids:
                # 已存在（MAC 匹配），更新所有新字段
                for existing_dev in merged_devices:
                    if existing_dev.get("id") == dev_id:
                        _merge_device_fields(existing_dev, dev)
                        break
            else:
                # MAC 不匹配，尝试 IP 匹配（ID 迁移）
                matched = False
                for new_ip in dev.get("ips", []):
                    if new_ip in ip_to_existing:
                        old_dev = ip_to_existing[new_ip]
                        old_id = old_dev.get("id")
                        # 迁移：更新旧设备所有字段，更新 ID 为 MAC
                        if dev.get("mac"):
                            old_dev["id"] = dev["mac"]
                            seen_ids.discard(old_id)
                            seen_ids.add(old_dev["id"])
                        _merge_device_fields(old_dev, dev)
                        matched = True
                        break
                
                if not matched:
                    merged_devices.append(dev)
                    seen_ids.add(dev_id)
    
    schema["devices"] = merged_devices
    
    # 3. 写入推理后端信息（到 services 或 self）
    if inference_backends:
        if schema.get("self"):
            schema["self"]["inference_backends"] = inference_backends

    # 3b. 合并 GPU 推理能力（从 discover-inference.sh）
    if inference_caps and schema.get("self"):
        gpu = inference_caps.get("gpu", {})
        if gpu.get("backend") != "none":
            schema["self"]["gpu"] = gpu
            print(f"   GPU: {gpu['name']} ({gpu['backend']}, {gpu['memory_total_mb']}MB)")

        # 合并远程推理后端（如果 detect_inference_backends 没扫到本机以外的）
        remote_backends = inference_caps.get("backends", [])
        if remote_backends:
            existing_urls = {b.get("url") for b in schema.get("self", {}).get("inference_backends", [])}
            for rb in remote_backends:
                if rb.get("url") not in existing_urls:
                    schema["self"].setdefault("inference_backends", []).append(rb)
                    print(f"   ➕ 远程推理: {rb['type']} ({rb['url']})")

    # 3c. 合并本机硬件信息（从 discover-hardware.sh）
    if hardware_caps and schema.get("self"):
        hw = {}
        if hardware_caps["cameras"]:
            hw["cameras"] = hardware_caps["cameras"]
        if hardware_caps["audio"]:
            hw["audio"] = hardware_caps["audio"]
        if hardware_caps["displays"]:
            hw["displays"] = hardware_caps["displays"]
        if hardware_caps["bluetooth"]["devices"] or hardware_caps["bluetooth"]["state"] != "unknown":
            hw["bluetooth"] = hardware_caps["bluetooth"]
        if hardware_caps["usb"]:
            hw["usb"] = hardware_caps["usb"]
        if hardware_caps["storage"]:
            hw["storage"] = hardware_caps["storage"]
        if hw:
            schema["self"]["hardware"] = hw
            print(f"   硬件: {', '.join(k for k in hw.keys())}")

    # 4. 更新元数据
    schema["discovery_meta"] = {
        "last_full_discovery": datetime.now(CST).isoformat(),
        "schema_version": schema.get("discovery_meta", {}).get("schema_version", "1.1")
    }
    
    return schema


def parse_inference_output(text):
    """解析 discover-inference.sh 的输出文本，返回结构化数据"""
    result = {
        "gpu": {"backend": "none", "name": "none", "memory_total_mb": 0, "memory_free_mb": 0},
        "backends": []
    }
    if not text:
        return result

    # GPU 信息
    gpu_match = re.search(r'--- GPU ---\n\s+([^\n]+)', text)
    if gpu_match:
        line = gpu_match.group(1).strip()
        # Apple M1 (metal, unified 16GB)
        metal_match = re.search(r'(.+?)\s*\((metal),', line)
        if metal_match:
            result["gpu"]["backend"] = "metal"
            result["gpu"]["name"] = metal_match.group(1).strip()
            mem_match = re.search(r'unified\s+(\d+)GB', line)
            if mem_match:
                result["gpu"]["memory_total_mb"] = int(mem_match.group(1)) * 1024
        # NVIDIA GeForce RTX 5070 (cuda)
        cuda_match = re.search(r'(.+?)\s*\((cuda)\)', line)
        if cuda_match:
            result["gpu"]["backend"] = "cuda"
            result["gpu"]["name"] = cuda_match.group(1).strip()
            # VRAM: 12288MB total, 8192MB free
            vram_match = re.search(r'VRAM:\s*(\d+)MB\s*total,\s*(\d+)MB\s*free', text)
            if vram_match:
                result["gpu"]["memory_total_mb"] = int(vram_match.group(1))
                result["gpu"]["memory_free_mb"] = int(vram_match.group(2))
        # 无独立 GPU（CPU-only）
        if "CPU-only" in line or "无独立 GPU" in line or "无 GPU" in line:
            result["gpu"]["backend"] = "cpu"

    # 推理后端
    backend_section = re.search(r'--- 推理后端 ---\n(.*?)(?:\n---|\nscan complete|\Z)', text, re.DOTALL)
    if backend_section:
        backend_text = backend_section.group(1)
        # 每行: 🔮 Ollama: http://localhost:11434 (N models)
        for line in backend_text.split('\n'):
            line = line.strip()
            backend_match = re.search(r'🔮\s+(.+?):\s+(https?://\S+)\s+\((\d+)\s*models?\)', line)
            if backend_match:
                backend_type = backend_match.group(1).lower()
                url = backend_match.group(2)
                models_count = int(backend_match.group(3))
                # 收集模型名（下一行开始的 - xxx 行）
                models = []

            model_match = re.search(r'-\s+(.+)', line)
            if model_match and result["backends"]:
                models.append(model_match.group(1).strip())

        # 重新扫描整理 backends
        result["backends"] = []
        current_backend = None
        for line in backend_text.split('\n'):
            line_stripped = line.strip()
            backend_match = re.search(r'🔮\s+(.+?):\s+(https?://\S+)\s+\((\d+)\s*models?\)', line_stripped)
            if backend_match:
                if current_backend:
                    result["backends"].append(current_backend)
                current_backend = {
                    "type": backend_match.group(1).lower(),
                    "url": backend_match.group(2),
                    "models": [],
                    "models_count": int(backend_match.group(3))
                }
            elif current_backend:
                model_match = re.search(r'-\s+(.+)', line_stripped)
                if model_match:
                    current_backend["models"].append(model_match.group(1).strip())
        if current_backend:
            result["backends"].append(current_backend)

    return result


def parse_hardware_output(text):
    """解析 discover-hardware.sh 的输出文本，返回结构化硬件数据"""
    result = {
        "audio": [],
        "bluetooth": {"state": "unknown", "devices": []},
        "displays": [],
        "cameras": [],
        "usb": [],
        "storage": []
    }
    if not text:
        return result

    # 音频设备
    audio_section = re.search(r'--- 🔊 音频设备 ---\n(.*?)(?:\n---|\nscan complete|\Z)', text, re.DOTALL)
    if audio_section:
        for line in audio_section.group(1).split('\n'):
            m = re.search(r'🎵\s+(.+)', line.strip())
            if m:
                result["audio"].append({"name": m.group(1).strip()})

    # 蓝牙设备
    bt_section = re.search(r'--- 📱 蓝牙设备 ---\n(.*?)(?:\n---|\nscan complete|\Z)', text, re.DOTALL)
    if bt_section:
        for line in bt_section.group(1).split('\n'):
            line_stripped = line.strip()
            state_match = re.search(r'状态:\s*(.+)', line_stripped)
            if state_match:
                result["bluetooth"]["state"] = state_match.group(1).strip()
            dev_match = re.search(r'🟢|⚪\s+(.+?)\s*\((.+?)\)', line_stripped)
            if dev_match:
                result["bluetooth"]["devices"].append({
                    "name": dev_match.group(1).strip(),
                    "status": dev_match.group(2).strip()
                })

    # 显示器
    disp_section = re.search(r'--- 🖥️ 显示器 ---\n(.*?)(?:\n---|\nscan complete|\Z)', text, re.DOTALL)
    if disp_section:
        for line in disp_section.group(1).split('\n'):
            m = re.search(r'🖥️\s+(.+)', line.strip())
            if m:
                result["displays"].append({"name": m.group(1).strip()})

    # 摄像头
    cam_section = re.search(r'--- 📷 摄像头 ---\n(.*?)(?:\n---|\nscan complete|\Z)', text, re.DOTALL)
    if cam_section:
        for line in cam_section.group(1).split('\n'):
            m = re.search(r'📷\s+(.+)', line.strip())
            if m:
                result["cameras"].append({"name": m.group(1).strip()})

    # USB 设备
    usb_section = re.search(r'--- ⌨️ USB 设备 ---\n(.*?)(?:\n---|\nscan complete|\Z)', text, re.DOTALL)
    if usb_section:
        for line in usb_section.group(1).split('\n'):
            m = re.search(r'🔌\s+(.+)', line.strip())
            if m:
                result["usb"].append({"name": m.group(1).strip()})

    # 挂载存储
    storage_section = re.search(r'--- 💾 挂载存储 ---\n(.*?)(?:\n---|\nscan complete|\Z)', text, re.DOTALL)
    if storage_section:
        for line in storage_section.group(1).split('\n'):
            m = re.search(r'💽\s+(\S+)\s+(\S+)\s*/\s*(\S+)\s*→\s*(.+)', line.strip())
            if m:
                result["storage"].append({
                    "filesystem": m.group(1),
                    "used": m.group(2),
                    "total": m.group(3),
                    "mount": m.group(4).strip()
                })

    return result


def main():
    parser = argparse.ArgumentParser(description="合并设备 schema")
    parser.add_argument(
        "--memory-devices",
        type=str,
        default=None,
        help="Agent 从记忆读取的设备列表 JSON（通过 stdin 或参数传入）"
    )
    args, _ = parser.parse_known_args()
    
    # 解析 --memory-devices 参数
    memory_devices = None
    if args.memory_devices:
        try:
            memory_devices = json.loads(args.memory_devices)
            print(f"   收到 Agent 传入的 {len(memory_devices)} 条记忆设备")
        except (json.JSONDecodeError, TypeError) as e:
            print(f"   ⚠️ 解析 --memory-devices 失败: {e}", file=sys.stderr)
    
    print("=== Schema 自动合并 ===")
    print()

    # 1. 读取现有 schema
    print("1/9 读取 schema...")
    schema = load_schema()
    known_ips = [d.get("ip", "") for d in schema.get("devices", []) if d.get("ip")]
    print(f"   已有 {len(schema.get('devices', []))} 台设备" if known_ips else "   空 schema（首次运行）")

    # 2. 探测本机
    print("2/9 探测本机...")
    self_info = discover_self()
    if self_info:
        print(f"   {self_info.get('hostname', '?')} / {self_info.get('os', '?')}")

    # 3. 测试连通性
    print("3/9 测试连通性...")
    reachable = test_reachability(known_ips)
    for ip, status in reachable.items():
        icon = "✅" if status == "reachable" else "❌"
        print(f"   {icon} {ip} — {status}")

    # 4. 网络发现
    print("4/9 网络发现...")
    network_devices = discover_network_devices()
    print(f"   发现 {len(network_devices)} 台新设备")
    for d in network_devices:
        # 新格式用 ips/primary_ip，旧格式用 ip
        ip_display = d.get('primary_ip') or d.get('ip') or (d.get('ips', ['?'])[0] if d.get('ips') else '?')
        print(f"   📡 {d.get('name', '?')} ({ip_display}) — {d.get('type', '?')}")

    # 5. 从 Memory 补充设备
    print("5/9 从 Memory 补充设备...")
    schema = supplement_from_memory(schema, memory_devices)

    # 6a. 检测推理后端（本地端口扫描）
    print("6a/9 检测推理后端...")
    backends = detect_inference_backends()
    for b in backends:
        print(f"   {b['type']} ({b['url']}): {b['models_count']} models")
    if not backends:
        print("   无推理后端")

    # 6b. GPU & 远程推理探测
    print("6b/9 GPU & 远程推理探测...")
    # 推理扫描可能需要 8-9 分钟（ARP 全扫）
    inference_output = run_script("discover-inference.sh", timeout=600)
    inference_caps = parse_inference_output(inference_output)
    if inference_caps["gpu"]["backend"] != "none":
        print(f"   GPU: {inference_caps['gpu']['name']} ({inference_caps['gpu']['backend']})")
    if inference_caps["backends"]:
        for b in inference_caps["backends"]:
            print(f"   🔮 {b['type']}: {b['url']} ({b['models_count']} models)")
    else:
        print("   无远程推理后端")

    # 6c. 本机硬件探测
    print("6c/9 本机硬件探测...")
    hardware_output = run_script("discover-hardware.sh", timeout=30)
    hardware_caps = parse_hardware_output(hardware_output)
    if hardware_caps["cameras"]:
        print(f"   摄像头: {len(hardware_caps['cameras'])} 个")
    if hardware_caps["audio"]:
        print(f"   音频: {len(hardware_caps['audio'])} 个")
    if hardware_caps["displays"]:
        print(f"   显示器: {len(hardware_caps['displays'])} 个")
    if hardware_caps["storage"]:
        print(f"   存储: {len(hardware_caps['storage'])} 项")

    # 7. 合并保存
    print("7/9 合并保存...")
    old_device_count = len(schema.get("devices", []))
    schema = merge_schema(schema, self_info, reachable, backends, network_devices,
                          inference_caps=inference_caps, hardware_caps=hardware_caps)
    new_device_count = len(schema.get("devices", []))
    
    with open(SCHEMA_PATH, "w") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    
    # 记录操作历史
    added_count = new_device_count - old_device_count
    if added_count > 0 or network_devices:
        log_operation(
            action="schema-merge",
            target="body-schema",
            result="success",
            detail=f"发现 {len(network_devices)} 台设备，新增 {added_count} 台，总计 {new_device_count} 台"
        )
    
    print(f"✅ 已保存: {SCHEMA_PATH}")
    
    # 摘要
    print()
    for d in schema.get("devices", []):
        icon = "🟢" if d.get("status") == "reachable" else "🔴"
        disc = "auto" if d.get("discovered") else "manual"
        print(f"  {icon} {d.get('name', '?')} ({d.get('ip', '?')}) [{disc}]")


if __name__ == "__main__":
    main()
