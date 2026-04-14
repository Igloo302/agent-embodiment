#!/bin/bash
# discover-pve.sh — PVE 虚拟机探测
# 通过 SSH 获取 PVE 上所有 VM 的状态和配置

set -euo pipefail

# 从 body-schema.json 读取 PVE 信息
SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"

if [[ ! -f "$SCHEMA" ]]; then
  echo '{"error": "body-schema.json not found, run discover-self.sh first"}'
  exit 1
fi

# 尝试读取 PVE IP（优先从 schema，其次从环境变量）
PVE_IP=$(python3 -c "
import json, sys
try:
    with open('$SCHEMA') as f:
        data = json.load(f)
    for d in data.get('devices', []):
        if d.get('type') == 'hypervisor':
            print(d['ip'])
            break
except:
    pass
" 2>/dev/null)

if [[ -z "$PVE_IP" ]]; then
  # fallback: 从常用 IP 扫描 PVE
  for ip in 192.168.x.100 192.168.1.100 10.0.0.100; do
    if nc -z -w 1 "$ip" 8006 2>/dev/null; then
      PVE_IP="$ip"
      break
    fi
  done
fi

if [[ -z "$PVE_IP" ]]; then
  echo '{"error": "PVE not found"}'
  exit 1
fi

echo "pve_ip: $PVE_IP"
echo "---"

# 尝试连接 PVE 获取 VM 列表
if command -v sshpass &>/dev/null && [[ -n "${PVE_PASSWORD:-}" ]]; then
  sshpass -p "$PVE_PASSWORD" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
    "root@${PVE_IP}" "qm list" 2>/dev/null
else
  # 纯 SSH 密钥方式
  ssh -o BatchMode=yes -o ConnectTimeout=5 \
    "root@${PVE_IP}" "qm list" 2>/dev/null || echo '{"error": "SSH connection failed, check credentials"}'
fi
