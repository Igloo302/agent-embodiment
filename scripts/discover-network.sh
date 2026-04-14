#!/bin/bash
# discover-network.sh — 局域网设备发现
# 扫描本机所在子网，发现存活主机和常见服务端口

set -euo pipefail

# 获取本机 IP 和子网
get_subnet() {
  if [[ "$OSTYPE" == "darwin"* ]]; then
    local_ip=$(ifconfig | grep "inet " | grep -v "127.0.0.1" | head -1 | awk '{print $2}')
    # 假设 /24 子网
    subnet=$(echo "$local_ip" | sed 's/\.[0-9]*$/.0\/24/')
    echo "$subnet"
  else
    local_ip=$(ip route get 1 2>/dev/null | awk '{print $7}' | head -1 || hostname -I | awk '{print $1}')
    subnet=$(echo "$local_ip" | sed 's/\.[0-9]*$/.0\/24/')
    echo "$subnet"
  fi
}

subnet=$(get_subnet)
base=$(echo "$subnet" | sed 's/\.0\/24//')

echo "scanning: $subnet"
echo "---"

# 并行 ping 扫描（30 秒内完成 /24 网段）
scan_alive() {
  for i in $(seq 1 254); do
    ip="${base}.${i}"
    ping -c 1 -t 1 "$ip" >/dev/null 2>&1 &
  done
  wait
}

# 用 arp 表获取结果（macOS）
get_alive_hosts() {
  arp -a 2>/dev/null | grep -E "192\.168\." | while read line; do
    host=$(echo "$line" | awk '{print $2}' | tr -d '()')
    mac=$(echo "$line" | awk '{print $4}')
    echo "$host $mac"
  done
}

# 端口探测
probe_port() {
  local ip=$1
  local port=$2
  local timeout=1
  (echo >/dev/tcp/$ip/$port) 2>/dev/null && echo "$port" || true
}

probe_services() {
  local ip=$1
  local ports=""

  # SSH
  result=$(nc -z -w 1 "$ip" 22 2>/dev/null && echo "22" || true)
  [[ -n "$result" ]] && ports="${ports}22,"

  # HTTP
  result=$(nc -z -w 1 "$ip" 80 2>/dev/null && echo "80" || true)
  [[ -n "$result" ]] && ports="${ports}80,"

  # HTTPS
  result=$(nc -z -w 1 "$ip" 443 2>/dev/null && echo "443" || true)
  [[ -n "$result" ]] && ports="${ports}443,"

  # PVE Web UI
  result=$(nc -z -w 1 "$ip" 8006 2>/dev/null && echo "8006" || true)
  [[ -n "$result" ]] && ports="${ports}8006,"

  # Ollama
  result=$(nc -z -w 1 "$ip" 11434 2>/dev/null && echo "11434" || true)
  [[ -n "$result" ]] && ports="${ports}11434,"

  # RDP
  result=$(nc -z -w 1 "$ip" 3389 2>/dev/null && echo "3389" || true)
  [[ -n "$result" ]] && ports="${ports}3389,"

  # Hermes Dashboard
  result=$(nc -z -w 1 "$ip" 9119 2>/dev/null && echo "9119" || true)
  [[ -n "$result" ]] && ports="${ports}9119,"

  # 去掉末尾逗号
  ports=$(echo "$ports" | sed 's/,$//')
  echo "$ports"
}

infer_type() {
  local ports=$1
  case "$ports" in
    *8006*) echo "pve" ;;
    *11434*) echo "ollama_host" ;;
    *3389*) echo "windows" ;;
    *9119*) echo "hermes_host" ;;
    *80,*|*443,*|*80,443*) echo "router" ;;
    *22*) echo "linux_server" ;;
    *) echo "unknown" ;;
  esac
}

# 执行扫描
echo "pinging all hosts..."
scan_alive 2>/dev/null

echo "probing services..."
echo ""

get_alive_hosts | while read host mac; do
  ports=$(probe_services "$host")
  if [[ -n "$ports" ]]; then
    device_type=$(infer_type "$ports")
    echo "${host}  ports=${ports}  type=${device_type}  mac=${mac}"
  fi
done

echo ""
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
