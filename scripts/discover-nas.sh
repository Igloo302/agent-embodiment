#!/bin/bash
# discover-nas.sh — NAS 及家庭服务探测
# 扫描 SMB、NFS、DLNA、媒体服务、NAS 管理面板等

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"

# 端口 → 服务名映射（用函数代替关联数组，兼容 bash 3.2）
port_name() {
  case "$1" in
    # 文件共享
    139) echo "SMB-netbios" ;; 445) echo "SMB" ;; 2049) echo "NFS" ;; 548) echo "AFP" ;;
    5005) echo "WebDAV" ;; 5006) echo "WebDAV-TLS" ;;
    # NAS 管理
    5000) echo "Synology-DSM" ;; 5001) echo "Synology-DSM-TLS" ;;
    8080) echo "QNAP-Alt" ;; 8443) echo "HTTPS-Alt" ;;
    # 媒体服务
    8096) echo "Jellyfin" ;; 8920) echo "Jellyfin-TLS" ;;
    32400) echo "Plex" ;; 8200) echo "DLNA-MiniDLNA" ;;
    # 下载
    9091) echo "Transmission" ;; 6789) echo "NZBGet" ;;
    8085) echo "qBittorrent" ;; 8112) echo "Deluge" ;; 5050) echo "SABnzbd" ;;
    # 监控
    3000) echo "Grafana" ;; 9090) echo "Prometheus" ;; 8180) echo "Tautulli" ;;
    # 数据库
    3306) echo "MySQL-MariaDB" ;; 5432) echo "PostgreSQL" ;;
    6379) echo "Redis" ;; 27017) echo "MongoDB" ;;
    # 网络
    53) echo "DNS" ;;
    *) echo "port-$1" ;;
  esac
}

# 收集要扫描的 IP
ips=()

# 从 schema 读取
if [[ -f "$SCHEMA" ]]; then
  schema_ips=$(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    ip = d.get('ip', '')
    if ip:
        print(ip)
" 2>/dev/null)
  while IFS= read -r ip; do
    [[ -n "$ip" ]] && ips+=("$ip")
  done <<< "$schema_ips"
fi

# 也扫描 ARP 表里的存活主机
for ip in $(arp -a 2>/dev/null | grep -oE '([0-9]+\.){3}[0-9]+' | sort -u); do
  if [[ ! " ${ips[*]:-} " =~ " $ip " ]]; then
    if ping -c 1 -t 1 "$ip" >/dev/null 2>&1; then
      ips+=("$ip")
    fi
  fi
done

# 本机
my_ips=$(ifconfig 2>/dev/null | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}')
for ip in $my_ips; do
  if [[ ! " ${ips[*]:-} " =~ " $ip " ]]; then
    ips+=("$ip")
  fi
done

echo "扫描 ${#ips[@]} 台设备的 NAS/家庭服务..."
echo ""

# 要扫描的端口
NAS_PORTS="139 445 2049 548 5005 5006"
NAS_MGMT_PORTS="5000 5001 8080 8443"
MEDIA_PORTS="8096 8920 32400 8200"
DOWNLOAD_PORTS="9091 6789 8085 8112 5050"
DB_PORTS="3306 5432 6379 27017"
ALL_PORTS="$NAS_PORTS $NAS_MGMT_PORTS $MEDIA_PORTS $DOWNLOAD_PORTS $DB_PORTS"

printf "%-16s %-6s %-20s %s\n" "IP" "Port" "Service" "Status"
printf "%-16s %-6s %-20s %s\n" "----" "----" "-------" "------"

found=0

for ip in "${ips[@]}"; do
  if ! ping -c 1 -t 1 "$ip" >/dev/null 2>&1; then
    continue
  fi
  
  for port in $ALL_PORTS; do
    if nc -z -w 1 -G 1 "$ip" "$port" 2>/dev/null; then
      svc=$(port_name "$port")
      printf "%-16s %-6s %-20s %s\n" "$ip" "$port" "$svc" "open"
      found=$((found + 1))
    fi
  done
done

echo ""
if [[ $found -eq 0 ]]; then
  echo "未发现 NAS/家庭服务"
else
  echo "发现 $found 个服务端口"
fi
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
