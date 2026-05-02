#!/usr/bin/env python3
"""
discover-network.py — 并行网络发现
使用 concurrent.futures 实现快速 ping 和端口扫描

v1.1 Changes:
- MAC 地址作为设备唯一标识
- 输出格式增加 MAC 地址列
- 支持 ARP 表查询 MAC

扫描网段: 10.6.11, 192.168.5, 192.168.6, 192.168.8, 192.168.193
"""

from __future__ import annotations
import concurrent.futures
import subprocess
import socket
import sys
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple

# 配置
SUBNETS = ["10.6.11", "192.168.5", "192.168.6", "192.168.8", "192.168.193"]
PING_TIMEOUT = 1  # 秒
PORT_TIMEOUT = 1.0  # 秒
MAX_PING_WORKERS = 100
MAX_PORT_WORKERS = 200

# 常用端口映射
PORT_MAP = {
    22: "SSH",
    53: "DNS",
    80: "HTTP",
    139: "SMB-NetBIOS",
    443: "HTTPS",
    445: "SMB",
    2049: "NFS",
    3000: "Grafana",
    32400: "Plex",
    3306: "MySQL",
    3389: "RDP",
    5000: "Synology-DSM",
    5001: "DSM-TLS",
    5432: "PostgreSQL",
    6379: "Redis",
    8000: "vLLM",
    8006: "PVE",
    8080: "HTTP-Alt",
    8085: "qBittorrent",
    8096: "Jellyfin",
    8200: "DLNA",
    8443: "HTTPS-Alt",
    8888: "llama.cpp",
    9091: "Transmission",
    9119: "Hermes-Dashboard",
    11434: "Ollama",
    1234: "LM-Studio",
}

PORTS = list(PORT_MAP.keys())
CST = timezone(timedelta(hours=8))


def get_mac_for_ip(ip: str) -> Optional[str]:
    """Try to get MAC address for an IP using ARP table."""
    try:
        result = subprocess.run(
            ["arp", "-n", ip],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            # Parse ARP output
            # macOS: "hostname (192.168.5.1) at aa:bb:cc:dd:ee:ff on en0"
            # Linux: "192.168.5.1 dev eth0 lladdr aa:bb:cc:dd:ee:ff REACHABLE"
            output = result.stdout
            mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}', output)
            if mac_match:
                return mac_match.group(0).lower().replace("-", ":")
    except Exception:
        pass
    return None


def ping_ip(ip: str) -> Optional[str]:
    """Ping 单个 IP，返回 IP 如果可达"""
    try:
        # macOS 使用 -t, Linux 使用 -W
        result = subprocess.run(
            ["ping", "-c", "1", "-t", str(PING_TIMEOUT), ip],
            capture_output=True,
            timeout=PING_TIMEOUT + 1
        )
        if result.returncode == 0:
            return ip
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def scan_port(ip: str, port: int) -> Optional[Tuple[str, int, str]]:
    """扫描单个端口，返回 (ip, port, service_name) 如果开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(PORT_TIMEOUT)
        result = sock.connect_ex((ip, port))
        sock.close()
        if result == 0:
            service = PORT_MAP.get(port, f"port-{port}")
            return (ip, port, service)
    except Exception:
        pass
    return None


def get_local_ips() -> set:
    """获取本机 IP 地址"""
    ips = set()
    try:
        # 获取所有网络接口
        result = subprocess.run(["ifconfig"], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            if "inet " in line and "127.0.0.1" not in line:
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[1]
                    if ip.count(".") == 3:  # IPv4
                        ips.add(ip)
    except Exception:
        pass
    return ips


def discover_hosts() -> list:
    """并行 ping 扫描所有网段"""
    print("=== 网络发现 ===", file=sys.stderr)
    print(file=sys.stderr)
    print(f"扫描 {len(SUBNETS)} 个网段...", file=sys.stderr)
    
    local_ips = get_local_ips()
    all_ips = []
    
    # 生成所有 IP
    for subnet in SUBNETS:
        for i in range(1, 255):
            ip = f"{subnet}.{i}"
            if ip not in local_ips:
                all_ips.append(ip)
    
    print(f"共 {len(all_ips)} 个 IP 待扫描", file=sys.stderr)
    
    alive_ips = []
    
    # 并行 ping
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PING_WORKERS) as executor:
        futures = {executor.submit(ping_ip, ip): ip for ip in all_ips}
        completed = 0
        
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if completed % 50 == 0:
                print(f"  进度: {completed}/{len(all_ips)} ({completed*100//len(all_ips)}%)", file=sys.stderr)
            
            result = future.result()
            if result:
                alive_ips.append(result)
    
    print(f"✓ 发现 {len(alive_ips)} 台存活设备", file=sys.stderr)
    print(file=sys.stderr)
    return sorted(alive_ips)


def scan_ports(ip: str) -> list:
    """扫描单个 IP 的所有端口"""
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(PORTS)) as executor:
        futures = {executor.submit(scan_port, ip, port): port for port in PORTS}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    return results


def scan_all_ports(alive_ips: list) -> dict:
    """并行扫描所有存活设备的端口，同时获取 MAC 地址"""
    print("=== 端口扫描 ===", file=sys.stderr)
    print(file=sys.stderr)
    
    devices = {}
    total = len(alive_ips) * len(PORTS)
    completed = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PORT_WORKERS) as executor:
        futures = {}
        
        for ip in alive_ips:
            for port in PORTS:
                future = executor.submit(scan_port, ip, port)
                futures[future] = (ip, port)
        
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if completed % 100 == 0:
                print(f"  进度: {completed}/{total} ({completed*100//total}%)", file=sys.stderr)
            
            result = future.result()
            if result:
                ip, port, service = result
                if ip not in devices:
                    devices[ip] = {"ports": [], "services": [], "mac": None}
                devices[ip]["ports"].append(port)
                devices[ip]["services"].append(service)
    
    # 获取 MAC 地址（并行）
    print("=== MAC 地址查询 ===", file=sys.stderr)
    mac_futures = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        for ip in devices.keys():
            mac_futures[executor.submit(get_mac_for_ip, ip)] = ip
    
        for future in concurrent.futures.as_completed(mac_futures):
            ip = mac_futures[future]
            mac = future.result()
            if mac:
                devices[ip]["mac"] = mac
    
    mac_count = sum(1 for d in devices.values() if d["mac"])
    print(f"✓ 获取 {mac_count} 个 MAC 地址", file=sys.stderr)
    
    print(f"✓ 发现 {len(devices)} 台有开放端口的设备", file=sys.stderr)
    print(file=sys.stderr)
    return devices


def main():
    start_time = datetime.now()
    
    # 1. Ping 扫描
    alive_ips = discover_hosts()
    
    # 2. 端口扫描 + MAC 查询
    devices = scan_all_ports(alive_ips)
    
    # 3. 输出结果 (stdout，供 merge-schema.py 解析)
    # 新格式: IP MAC Port Service Status
    print("%-16s %-18s %-8s %-18s %s" % ("IP", "MAC", "Port", "Service", "Status"))
    print("%-16s %-18s %-8s %-18s %s" % ("----", "---", "----", "-------", "------"))
    
    for ip in sorted(devices.keys()):
        info = devices[ip]
        mac = info.get("mac", "") or ""
        for port, service in sorted(zip(info["ports"], info["services"])):
            print("%-16s %-18s %-8s %-18s %s" % (ip, mac, port, service, "open"))
    
    # 4. 摘要
    elapsed = (datetime.now() - start_time).total_seconds()
    print(file=sys.stderr)
    print(f"scan complete: {datetime.now(CST).isoformat()}", file=sys.stderr)
    print(f"耗时: {elapsed:.1f} 秒", file=sys.stderr)


if __name__ == "__main__":
    main()