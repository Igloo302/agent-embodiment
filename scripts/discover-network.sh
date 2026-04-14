#!/bin/bash
# discover-network.sh — 局域网设备发现（轻量版）
# 只测试已知 IP 的连通性，不做全网段扫描

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"

echo "checking known devices..."
echo "---"

# 从 body-schema.json 读取所有已知 IP
if [[ ! -f "$SCHEMA" ]]; then
  echo "no body-schema.json found"
  exit 1
fi

devices=$(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    ip = d.get('ip', '')
    did = d.get('id', 'unknown')
    name = d.get('name', 'unknown')
    if ip:
        print(f'{did}|{name}|{ip}')
" 2>/dev/null)

# 也加入本机 IP
my_ips=$(ifconfig 2>/dev/null | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}')

# 探测端口
check_port() {
  nc -z -w 1 -G 1 "$1" "$2" 2>/dev/null && echo "$2" || true
}

echo "Device               IP               Status    Services"
echo "------               --               ------    --------"

while IFS='|' read -r did name ip; do
  # ping 测试
  if ping -c 1 -t 2 "$ip" >/dev/null 2>&1; then
    status="alive"

    # 端口探测
    services=""
    for port in 22 80 443 3389 8006 9119 11434; do
      result=$(check_port "$ip" "$port")
      [[ -n "$result" ]] && services="${services}${port} "
    done
  else
    status="unreachable"
    services="-"
  fi

  printf "%-20s %-16s %-9s %s\n" "$name" "$ip" "$status" "$services"
done <<< "$devices"

# 也检查本机服务
for ip in $my_ips; do
  services=""
  for port in 9119; do
    result=$(check_port "$ip" "$port")
    [[ -n "$result" ]] && services="${services}${port} "
  done
  if [[ -n "$services" ]]; then
    printf "%-20s %-16s %-9s %s\n" "localhost" "$ip" "alive" "$services"
  fi
done

echo ""
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
