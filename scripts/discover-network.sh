#!/bin/bash
# discover-network.sh — 网络发现
# 存活探测 + 端口扫描 + mDNS，一站式完成
# 新用户友好：无 body-schema.json 时也能跑

set -euo pipefail

# 禁用输出缓冲
export PYTHONUNBUFFERED=1

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"
SCRIPTS="$HOME/.hermes/skills/agent-embodiment/scripts"

echo "=== 网络发现 ===" >&2
echo "" >&2

# ---------------------------------------------------------------
# Step 1: 收集 IP 和可达网段
# ---------------------------------------------------------------
ips=()
subnets=()

# 本机 IP（提前获取，用于过滤）
my_ips=$(ifconfig 2>/dev/null | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}')

# 从路由表发现可达网段（提取直连网段 + 路由条目）
while IFS=$'\t ' read -r dest gateway flags _; do
  # 跳过 default、link-local、localhost
  [[ "$dest" =~ ^(default|127\.|169\.254\.|fe80::|::) ]] && continue
  # 只处理 IPv4 私有网段
  if [[ "$dest" =~ ^192\.168\.|^10\.|^172\.(1[6-9]|2[0-9]|3[01])\. ]]; then
    # 提取网段前缀（去掉 CIDR 后缀，或直接取前 3 段）
    if [[ "$dest" =~ / ]]; then
      subnet=$(echo "$dest" | cut -d'/' -f1)
    else
      subnet="$dest"
    fi
    subnet_prefix=$(echo "$subnet" | cut -d'.' -f1-3)
    if [[ ! " ${subnets[*]:-} " =~ " $subnet_prefix " ]]; then
      subnets+=("$subnet_prefix")
    fi
  fi
done < <(netstat -rn 2>/dev/null)

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

# ARP 表收集（只扫 ARP 表，不扫整个网段）
echo "从 ARP 表收集 IP ..."
echo ""
arp_ips=$(arp -a 2>/dev/null | grep -oE '([0-9]+\.){3}[0-9]+' | sort -u)
for ip in $arp_ips; do
  # 跳过本机 IP
  [[ " ${my_ips[*]:-} " =~ " $ip " ]] && continue
  # 跳过已收集的
  if [[ ! " ${ips[*]:-} " =~ " $ip " ]]; then
    ips+=("$ip")
  fi
done
echo "✓ ARP 表收集完成，共 ${#ips[@]} 个 IP"
echo ""

# 添加本机 IP
for ip in $my_ips; do
  [[ ! " ${ips[*]:-} " =~ " $ip " ]] && ips+=("$ip")
done

echo "=========================================="
echo "阶段 1 完成：发现 ${#ips[@]} 台存活设备"
echo "=========================================="
echo ""

# ---------------------------------------------------------------
# Step 2: 端口扫描（通用端口列表）
# ---------------------------------------------------------------
echo "开始端口扫描..."
echo ""
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

# 并行端口扫描（限制并发数，避免资源耗尽）
MAX_PARALLEL=50
scan_port() {
  local ip="$1" port="$2"
  if nc -z -w 1 -G 1 "$ip" "$port" 2>/dev/null; then
    svc=$(port_name "$port")
    echo "$ip|$port|$svc" >> "$tmpfile"
  fi
}

# macOS 不支持 wait -n，用文件描述符控制并发
job_count=0
for ip in "${ips[@]}"; do
  [[ -z "$ip" ]] && continue
  for port in $PORTS; do
    scan_port "$ip" "$port" &
    ((job_count++))
    # 每 MAX_PARALLEL 个进程等待一次
    if [[ $((job_count % MAX_PARALLEL)) -eq 0 ]]; then
      wait
    fi
  done
done
wait

# 按 IP 排序输出，并附带 MAC 地址
if [[ -s "$tmpfile" ]]; then
  # 输出表头
  printf "%-16s %-17s %-8s %-18s %s\n" "IP" "MAC" "Port" "Service" "Status"
  printf "%-16s %-17s %-8s %-18s %s\n" "----" "---" "----" "-------" "------"

  # 获取 MAC 地址（不用关联数组，兼容 bash 3.x）
  get_mac() {
    arp -a 2>/dev/null | grep "$1" | grep -oE '([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}' | head -1
  }

  sort -t'|' -k1,1V -k2,2n "$tmpfile" | while IFS='|' read -r ip port svc; do
    mac=$(get_mac "$ip")
    [[ -z "$mac" ]] && mac="?"
    printf "%-16s %-17s %-8s %-18s %s\n" "$ip" "$mac" "$port" "$svc" "open"
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
