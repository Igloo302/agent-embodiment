#!/bin/bash
# discover-nas.sh — NAS 及家庭服务端口探测
# 由 discover-network.sh 编排调用，或独立使用
# 如果没有传入 IP，从 body-schema.json 读取

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"

port_name() {
  case "$1" in
    139) echo "SMB-netbios" ;; 445) echo "SMB" ;; 2049) echo "NFS" ;; 548) echo "AFP" ;;
    5005) echo "WebDAV" ;; 5006) echo "WebDAV-TLS" ;;
    5000) echo "Synology-DSM" ;; 5001) echo "Synology-DSM-TLS" ;;
    8080) echo "HTTP-Alt" ;; 8443) echo "HTTPS-Alt" ;;
    8096) echo "Jellyfin" ;; 8920) echo "Jellyfin-TLS" ;;
    32400) echo "Plex" ;; 8200) echo "DLNA" ;;
    9091) echo "Transmission" ;; 6789) echo "NZBGet" ;;
    8085) echo "qBittorrent" ;; 8112) echo "Deluge" ;; 5050) echo "SABnzbd" ;;
    3000) echo "Grafana" ;; 9090) echo "Prometheus" ;;
    3306) echo "MySQL" ;; 5432) echo "PostgreSQL" ;;
    6379) echo "Redis" ;; 27017) echo "MongoDB" ;;
    53) echo "DNS" ;;
    *) echo "port-$1" ;;
  esac
}

# 收集 IP
ips=("$@")

# 如果没传参，从 schema 读取
if [[ ${#ips[@]} -eq 0 ]] && [[ -f "$SCHEMA" ]]; then
  while IFS= read -r ip; do
    [[ -n "$ip" ]] && ips+=("$ip")
  done < <(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    ip = d.get('ip', '')
    if ip: print(ip)
" 2>/dev/null)
fi

# 端口列表
PORTS="139 445 2049 548 5000 5001 5005 5006 8080 8085 8096 8112 8200 8443 9091 32400 3306 5432 6379 27017"

printf "%-16s %-6s %-20s %s\n" "IP" "Port" "Service" "Status"
printf "%-16s %-6s %-20s %s\n" "----" "----" "-------" "------"

found=0
for ip in "${ips[@]}"; do
  [[ -z "$ip" ]] && continue
  if ! ping -c 1 -t 1 "$ip" >/dev/null 2>&1; then
    continue
  fi
  for port in $PORTS; do
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
