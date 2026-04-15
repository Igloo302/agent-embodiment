#!/bin/bash
# discover-network.sh — 网络发现
# 存活探测 + 端口扫描 + mDNS，一站式完成
# 新用户友好：无 body-schema.json 时也能跑

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"
SCRIPTS="$HOME/.hermes/skills/agent-embodiment/scripts"

echo "=== 网络发现 ==="
echo ""

# ---------------------------------------------------------------
# Step 1: 收集 IP
# ---------------------------------------------------------------
ips=()

# 从 schema 读取已知设备（如果有）
if [[ -f "$SCHEMA" ]]; then
  while IFS= read -r ip; do
    [[ -n "$ip" ]] && ips+=("$ip")
  done < <(python3 -c "
import json
try:
    with open('$SCHEMA') as f:
        data = json.load(f)
    for d in data.get('devices', []):
        ip = d.get('ip', '')
        if ip: print(ip)
except: pass
" 2>/dev/null)
fi

# ARP 表补充
for ip in $(arp -a 2>/dev/null | grep -oE '([0-9]+\.){3}[0-9]+' | sort -u); do
  if [[ ! " ${ips[*]:-} " =~ " $ip " ]]; then
    if ping -c 1 -t 1 "$ip" >/dev/null 2>&1; then
      ips+=("$ip")
    fi
  fi
done

# 本机 IP
my_ips=$(ifconfig 2>/dev/null | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}')
for ip in $my_ips; do
  [[ ! " ${ips[*]:-} " =~ " $ip " ]] && ips+=("$ip")
done

echo "发现 ${#ips[@]} 台设备"
echo ""

# ---------------------------------------------------------------
# Step 2: 端口扫描（通用端口列表）
# ---------------------------------------------------------------
# 基础: SSH, HTTP, HTTPS, DNS
# NAS: SMB, NFS, DSM
# 媒体: Jellyfin, Plex, DLNA
# 推理: Ollama, vLLM, llama.cpp, LM Studio
# 下载: Transmission, qBittorrent
# 管理: PVE, Grafana
PORTS="22 53 80 139 443 445 2049 3000 32400 3306 3389 5000 5001 5432 6379 8000 8006 8080 8085 8096 8200 8443 8888 9091 9119 11434 1234"

port_name() {
  case "$1" in
    22) echo "SSH" ;; 53) echo "DNS" ;; 80) echo "HTTP" ;; 443) echo "HTTPS" ;;
    139) echo "SMB-NetBIOS" ;; 445) echo "SMB" ;; 2049) echo "NFS" ;;
    3000) echo "Grafana" ;; 32400) echo "Plex" ;;
    3306) echo "MySQL" ;; 3389) echo "RDP" ;;
    5000) echo "Synology-DSM" ;; 5001) echo "DSM-TLS" ;;
    5432) echo "PostgreSQL" ;; 6379) echo "Redis" ;;
    8000) echo "vLLM" ;; 8006) echo "PVE" ;;
    8080) echo "HTTP-Alt" ;; 8085) echo "qBittorrent" ;; 8096) echo "Jellyfin" ;;
    8200) echo "DLNA" ;; 8443) echo "HTTPS-Alt" ;; 8888) echo "llama.cpp" ;;
    9091) echo "Transmission" ;; 9119) echo "Hermes-Dashboard" ;;
    11434) echo "Ollama" ;; 1234) echo "LM-Studio" ;;
    *) echo "port-$1" ;;
  esac
}

printf "%-16s %-8s %-18s %s\n" "IP" "Port" "Service" "Status"
printf "%-16s %-8s %-18s %s\n" "----" "----" "-------" "------"

found=0
tmpfile=$(mktemp)
trap "rm -f '$tmpfile'" EXIT

# 并行端口扫描：所有 (ip, port) 组合同步并发
scan_port() {
  local ip="$1" port="$2"
  if nc -z -w 1 -G 1 "$ip" "$port" 2>/dev/null; then
    svc=$(port_name "$port")
    echo "$ip|$port|$svc" >> "$tmpfile"
  fi
}

for ip in "${ips[@]}"; do
  [[ -z "$ip" ]] && continue
  if ! ping -c 1 -t 1 "$ip" >/dev/null 2>&1; then
    continue
  fi
  for port in $PORTS; do
    scan_port "$ip" "$port" &
  done
done
wait

# 按 IP 排序输出
if [[ -s "$tmpfile" ]]; then
  sort -t'|' -k1,1V -k2,2n "$tmpfile" | while IFS='|' read -r ip port svc; do
    printf "%-16s %-8s %-18s %s\n" "$ip" "$port" "$svc" "open"
  done
  found=$(wc -l < "$tmpfile" | tr -d ' ')
fi
echo "  ($found 个服务端口)"
echo ""

# ---------------------------------------------------------------
# Step 3: mDNS 发现（调用 discover-mdns.sh）
# ---------------------------------------------------------------
if [[ -x "$SCRIPTS/discover-mdns.sh" ]]; then
  # macOS 没有 timeout 命令，用后台进程 + sleep + kill
  bash "$SCRIPTS/discover-mdns.sh" 2>&1 | grep -E "^  📡|^---" &
  mdns_pid=$!
  ( sleep 5 && kill "$mdns_pid" 2>/dev/null ) &
  wait "$mdns_pid" 2>/dev/null || true
fi

echo ""
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
