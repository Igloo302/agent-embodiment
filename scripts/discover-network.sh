#!/bin/bash
# discover-network.sh — 网络发现统一入口
# 编排：存活探测 → mDNS 服务发现 → NAS 端口探测 → 汇总输出
# 不再自己做端口扫描，交给 discover-nas.sh 处理

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"
SCRIPTS="$HOME/.hermes/skills/agent-embodiment/scripts"

echo "=== 网络发现 ==="
echo ""

# ---------------------------------------------------------------
# Step 1: 收集要扫描的 IP（从 schema + ARP）
# ---------------------------------------------------------------
echo "--- Step 1: 存活探测 ---"

ips=()

# 从 schema 读取已知设备
if [[ -f "$SCHEMA" ]]; then
  schema_ips=$(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    ip = d.get('ip', '')
    if ip:
        print(f\"{d.get('id','?')}|{d.get('name','?')}|{ip}\")
" 2>/dev/null)
  echo "已知设备:"
  while IFS='|' read -r did name ip; do
    [[ -z "$did" ]] && continue
    if ping -c 1 -t 2 "$ip" >/dev/null 2>&1; then
      echo "  ✅ $name ($ip) — alive"
    else
      echo "  ❌ $name ($ip) — unreachable"
    fi
    ips+=("$ip")
  done <<< "$schema_ips"
fi

# ARP 表补充（局域网内新设备）
arp_new=0
for ip in $(arp -a 2>/dev/null | grep -oE '([0-9]+\.){3}[0-9]+' | sort -u); do
  if [[ ! " ${ips[*]:-} " =~ " $ip " ]]; then
    if ping -c 1 -t 1 "$ip" >/dev/null 2>&1; then
      ips+=("$ip")
      arp_new=$((arp_new + 1))
    fi
  fi
done
[[ $arp_new -gt 0 ]] && echo "ARP 补充发现 $arp_new 台新设备"

echo "共 ${#ips[@]} 台设备待探测"
echo ""

# ---------------------------------------------------------------
# Step 2: mDNS 服务发现（交给 discover-mdns.sh）
# ---------------------------------------------------------------
echo "--- Step 2: mDNS/Bonjour 服务发现 ---"
if [[ -x "$SCRIPTS/discover-mdns.sh" ]]; then
  bash "$SCRIPTS/discover-mdns.sh" 2>&1 | grep -E "^  |^---" || true
else
  echo "  (discover-mdns.sh 不存在)"
fi
echo ""

# ---------------------------------------------------------------
# Step 3: NAS/常见服务端口探测（交给 discover-nas.sh）
# ---------------------------------------------------------------
echo "--- Step 3: NAS/服务端口探测 ---"
if [[ -x "$SCRIPTS/discover-nas.sh" ]]; then
  bash "$SCRIPTS/discover-nas.sh" 2>&1 | grep -E "^(IP|----|  |发现|未发现)" || true
else
  echo "  (discover-nas.sh 不存在)"
fi
echo ""

echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
