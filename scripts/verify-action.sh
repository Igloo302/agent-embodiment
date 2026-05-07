#!/bin/bash
# verify-action.sh — 动作验证闭环
# 执行操作后自动验证是否成功，返回明确的 pass/fail + 原因
#
# 用法：
#   verify-action.sh <action> <target> [expected] [timeout]
#
# 示例：
#   verify-action.sh vm-running pve 103
#   verify-action.sh service-up http://<server-ip>:11434/api/tags
#   verify-action.sh ssh-reachable <server-ip>
#   verify-action.sh ollama-model http://<server-ip>:11434 <model-name>
#   verify-action.sh disk-space / 90
#   verify-action.sh process-running ollama

set -euo pipefail

ACTION="${1:-}"
TARGET="${2:-}"
EXPECTED="${3:-}"
TIMEOUT="${4:-30}"

# 动态获取 skill 目录（脚本所在目录的上一级）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"
SCHEMA="$SKILL_DIR/body-schema.json"
SCRIPTS_DIR="$SKILL_DIR/scripts"
CREDENTIALS="$SKILL_DIR/credentials.json"

# 从 credential pool 解析凭证引用
resolve_credential_ref() {
  local ref="$1"
  if [[ -f "$CREDENTIALS" ]]; then
    python3 -c "
import json
try:
    with open('$CREDENTIALS') as f:
        creds = json.load(f)
    ref = '$ref'
    if ref in creds:
        c = creds[ref]
        # 输出格式: user|password|key_path|ssh_command
        user = c.get('user', '')
        password = c.get('password', '')
        key_path = c.get('key_path', '')
        ssh_command = c.get('ssh_command', '')
        print(f'{user}|{password}|{key_path}|{ssh_command}')
except: pass
" 2>/dev/null || echo ""
  fi
}

# 从 schema 读取设备 SSH 别名（支持 credential_ref）
get_ssh_alias() {
  local device_id="$1"
  python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    if d.get('id') == '$device_id':
        access = d.get('access', {})
        if isinstance(access, str):
            print(access)
        elif isinstance(access, dict):
            # 支持 credential_ref
            cred_ref = access.get('credential_ref', '')
            if cred_ref:
                print(f'CRED_REF:{cred_ref}')
            else:
                ssh = access.get('ssh', '')
                if isinstance(ssh, dict):
                    print(ssh.get('command', ''))
                else:
                    print(ssh)
        break
" 2>/dev/null || echo ""
}

# 构建带凭证的 SSH 命令
build_ssh_command() {
  local ip="$1"
  local cred_ref="$2"

  if [[ -n "$cred_ref" ]]; then
    cred=$(resolve_credential_ref "$cred_ref")
    if [[ -n "$cred" ]]; then
      user=$(echo "$cred" | cut -d'|' -f1)
      key_path=$(echo "$cred" | cut -d'|' -f3)
      ssh_cmd=$(echo "$cred" | cut -d'|' -f4)

      if [[ -n "$ssh_cmd" ]]; then
        echo "$ssh_cmd"
      elif [[ -n "$key_path" ]]; then
        echo "ssh -i $key_path $user@$ip"
      elif [[ -n "$user" ]]; then
        echo "ssh $user@$ip"
      else
        echo "ssh $ip"
      fi
    else
      echo "ssh $ip"
    fi
  else
    echo "ssh $ip"
  fi
}

# 从 schema 读取 PVE IP
get_pve_ip() {
  python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    if d.get('type') == 'hypervisor':
        print(d['ip'])
        break
" 2>/dev/null || echo ""
}

verify() {
  local result="$1"  # pass or fail
  local detail="$2"
  local timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

  # 记录操作历史
  local duration_ms="${DURATION_MS:-0}"
  python3 "$SCRIPTS_DIR/log-operation.py" \
    --action "$ACTION" \
    --target "$TARGET" \
    --result "$result" \
    --duration "$duration_ms" \
    --detail "$detail" \
    2>/dev/null || true

  if [[ "$result" == "pass" ]]; then
    echo "{\"status\":\"pass\",\"action\":\"$ACTION\",\"target\":\"$TARGET\",\"detail\":\"$detail\",\"verified_at\":\"$timestamp\"}"
  else
    echo "{\"status\":\"fail\",\"action\":\"$ACTION\",\"target\":\"$TARGET\",\"detail\":\"$detail\",\"verified_at\":\"$timestamp\"}"
  fi
  [[ "$result" == "pass" ]] && exit 0 || exit 1
}

# ============================================================
# 动作验证
# ============================================================

case "$ACTION" in

  # --- VM 状态 ---
  vm-running)
    # TARGET = device_id (如 pve), EXPECTED = vmid (如 103)
    pve_ip=$(get_pve_ip)

    # 检查是否有 credential_ref
    ssh_alias=$(get_ssh_alias "$TARGET")
    if [[ "$ssh_alias" == "CRED_REF:"* ]]; then
      cred_ref="${ssh_alias#CRED_REF:}"
      ssh_cmd=$(build_ssh_command "$pve_ip" "$cred_ref")
    else
      ssh_cmd="ssh root@$pve_ip"
    fi

    if [[ -z "$pve_ip" ]]; then
      verify fail "PVE IP not found in schema"
    fi
    vmid="$EXPECTED"
    status=$($ssh_cmd "qm status $vmid" 2>/dev/null | awk '{print $2}' || echo "error")
    if [[ "$status" == "running" ]]; then
      verify pass "VM $vmid is running"
    else
      verify fail "VM $vmid status: $status"
    fi
    ;;

  vm-stopped)
    pve_ip=$(get_pve_ip)
    vmid="$EXPECTED"

    ssh_alias=$(get_ssh_alias "$TARGET")
    if [[ "$ssh_alias" == "CRED_REF:"* ]]; then
      cred_ref="${ssh_alias#CRED_REF:}"
      ssh_cmd=$(build_ssh_command "$pve_ip" "$cred_ref")
    else
      ssh_cmd="ssh root@$pve_ip"
    fi

    status=$($ssh_cmd "qm status $vmid" 2>/dev/null | awk '{print $2}' || echo "error")
    if [[ "$status" == "stopped" ]]; then
      verify pass "VM $vmid is stopped"
    else
      verify fail "VM $vmid status: $status (expected stopped)"
    fi
    ;;

  # --- 网络连通 ---
  ssh-reachable)
    # TARGET = IP
    if nc -z -w 3 "$TARGET" 22 2>/dev/null; then
      verify pass "SSH port open on $TARGET"
    else
      verify fail "SSH port closed on $TARGET"
    fi
    ;;

  ping-reachable)
    if ping -c 1 -t 3 "$TARGET" >/dev/null 2>&1; then
      verify pass "$TARGET is reachable"
    else
      verify fail "$TARGET is unreachable"
    fi
    ;;

  # --- 服务状态 ---
  service-up)
    # TARGET = URL (如 http://<server-ip>:11434/api/tags)
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$TIMEOUT" "$TARGET" 2>/dev/null || echo "000")
    if [[ "$http_code" =~ ^2[0-9]{2}$ ]]; then
      verify pass "Service responding (HTTP $http_code)"
    else
      verify fail "Service not responding (HTTP $http_code)"
    fi
    ;;

  # --- Ollama ---
  ollama-up)
    # TARGET = base URL (如 http://<server-ip>:11434)
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$TARGET/api/tags" 2>/dev/null || echo "000")
    if [[ "$http_code" == "200" ]]; then
      verify pass "Ollama is running"
    else
      verify fail "Ollama not responding (HTTP $http_code)"
    fi
    ;;

  ollama-model)
    # TARGET = base URL, EXPECTED = model name
    resp=$(curl -s --max-time 5 "$TARGET/api/tags" 2>/dev/null || echo "{}")
    if echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); models=[m['name'] for m in d.get('models',[])]; sys.exit(0 if '$EXPECTED' in models else 1)" 2>/dev/null; then
      verify pass "Model $EXPECTED is available"
    else
      verify fail "Model $EXPECTED not found"
    fi
    ;;

  ollama-model-loaded)
    # TARGET = base URL, EXPECTED = model name
    resp=$(curl -s --max-time 5 "$TARGET/api/ps" 2>/dev/null || echo "{}")
    if echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); models=[m['name'] for m in d.get('models',[])]; sys.exit(0 if '$EXPECTED' in models else 1)" 2>/dev/null; then
      verify pass "Model $EXPECTED is loaded in VRAM"
    else
      verify fail "Model $EXPECTED not loaded"
    fi
    ;;

  # --- 进程 ---
  process-running)
    # TARGET = process name
    if pgrep -x "$TARGET" >/dev/null 2>&1 || pgrep -f "$TARGET" >/dev/null 2>&1; then
      verify pass "Process $TARGET is running"
    else
      verify fail "Process $TARGET not found"
    fi
    ;;

  # --- 磁盘 ---
  disk-space)
    # TARGET = mount point, EXPECTED = max usage % (如 90)
    usage=$(df "$TARGET" 2>/dev/null | awk 'NR==2 {gsub(/%/,""); print $5}')
    if [[ -z "$usage" ]]; then
      verify fail "Cannot read disk usage for $TARGET"
    elif [[ "$usage" -le "$EXPECTED" ]]; then
      verify pass "Disk $TARGET usage: ${usage}% (threshold: ${EXPECTED}%)"
    else
      verify fail "Disk $TARGET usage: ${usage}% exceeds threshold ${EXPECTED}%"
    fi
    ;;

  # --- 端口 ---
  port-open)
    # TARGET = IP, EXPECTED = port
    if nc -z -w 3 "$TARGET" "$EXPECTED" 2>/dev/null; then
      verify pass "Port $EXPECTED open on $TARGET"
    else
      verify fail "Port $EXPECTED closed on $TARGET"
    fi
    ;;

  # --- 网络服务综合检查 ---
  network-check)
    # TARGET = IP, EXPECTED = comma-separated ports (如 "22,8006,11434")
    IFS=',' read -ra ports <<< "$EXPECTED"
    failed=()
    for port in "${ports[@]}"; do
      if ! nc -z -w 2 "$TARGET" "$port" 2>/dev/null; then
        failed+=("$port")
      fi
    done
    if [[ ${#failed[@]} -eq 0 ]]; then
      verify pass "All ports open on $TARGET ($EXPECTED)"
    else
      verify fail "Ports closed on $TARGET: ${failed[*]}"
    fi
    ;;

  *)
    echo "Unknown action: $ACTION"
    echo ""
    echo "Available actions:"
    echo "  vm-running <pve> <vmid>          - Check if VM is running"
    echo "  vm-stopped <pve> <vmid>          - Check if VM is stopped"
    echo "  ssh-reachable <ip>               - Check SSH port"
    echo "  ping-reachable <ip>              - Ping check"
    echo "  service-up <url>                 - HTTP service check"
    echo "  ollama-up <base-url>             - Ollama API check"
    echo "  ollama-model <base-url> <model>  - Model exists"
    echo "  ollama-model-loaded <url> <model>- Model in VRAM"
    echo "  process-running <name>           - Process check"
    echo "  disk-space <mount> <max%>        - Disk usage check"
    echo "  port-open <ip> <port>            - Port check"
    echo "  network-check <ip> <ports>       - Multi-port check"
    exit 1
    ;;
esac
