#!/bin/bash
# discover-pve.sh — PVE 虚拟机探测
# 优先用 PVE API，SSH 作为 fallback

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"

# 从 schema 读取 PVE IP
PVE_IP=$(python3 -c "
import json
try:
    with open('$SCHEMA') as f:
        data = json.load(f)
    for d in data.get('devices', []):
        if d.get('type') == 'hypervisor':
            print(d['ip'])
            break
except: pass
" 2>/dev/null)

if [[ -z "$PVE_IP" ]]; then
  echo '{"error": "PVE not found in schema"}'
  exit 1
fi

echo "pve_ip: $PVE_IP"

# 检查 PVE Web UI 是否可达
if ! nc -z -w 1 -G 1 "$PVE_IP" 8006 2>/dev/null; then
  echo "status: unreachable (port 8006 closed)"
  exit 0
fi
echo "status: reachable (port 8006 open)"

# 尝试 SSH 获取 VM 列表（快速超时）
if command -v sshpass &>/dev/null; then
  # 从 .env 读取密码（环境变量名见 .env 文件）
  ENV_FILE="$HOME/.hermes/.env"
  
  if [[ -f "$ENV_FILE" ]]; then
    # 按行读取 PVE 相关密码变量
    PVE_PASS=$(grep -E '^PVE_PASSWORD=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'" 2>/dev/null || true)
    
    if [[ -n "${PVE_PASS:-}" ]]; then
      echo ""
      echo "vms:"
      sshpass -p "$PVE_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=3 \
        "root@${PVE_IP}" "qm list" 2>/dev/null || echo "  ssh_failed"
    fi
  fi
else
  echo "note: sshpass not available, install for full PVE info"
fi

echo ""
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
