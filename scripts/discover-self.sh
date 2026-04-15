#!/bin/bash
# discover-self.sh — 本机环境探测
# 输出 Agent 所在系统的基本信息（JSON 格式）

set -euo pipefail

echo "{"

# Hostname
echo "  \"hostname\": \"$(hostname -s 2>/dev/null || echo unknown)\","

# OS
if [[ "$OSTYPE" == "darwin"* ]]; then
  os_name=$(sw_vers -productName 2>/dev/null)
  os_version=$(sw_vers -productVersion 2>/dev/null)
  echo "  \"os\": \"${os_name} ${os_version}\","
  echo "  \"platform\": \"macos\","
elif [[ -f /etc/os-release ]]; then
  . /etc/os-release
  echo "  \"os\": \"${PRETTY_NAME}\","
  echo "  \"platform\": \"linux\","
else
  echo "  \"os\": \"$(uname -s)\","
  echo "  \"platform\": \"unknown\","
fi

# Architecture
echo "  \"arch\": \"$(uname -m)\","

# CPU
if [[ "$OSTYPE" == "darwin"* ]]; then
  echo "  \"cpu\": \"$(sysctl -n machdep.cpu.brand_string 2>/dev/null || echo unknown)\","
  echo "  \"cpu_cores\": $(sysctl -n hw.ncpu 2>/dev/null || echo 0),"
else
  echo "  \"cpu\": \"$(grep 'model name' /proc/cpuinfo 2>/dev/null | head -1 | cut -d: -f2 | xargs || echo unknown)\","
  echo "  \"cpu_cores\": $(nproc 2>/dev/null || echo 0),"
fi

# Memory (GB)
if [[ "$OSTYPE" == "darwin"* ]]; then
  mem_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
  mem_gb=$((mem_bytes / 1024 / 1024 / 1024))
else
  mem_kb=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo 0)
  mem_gb=$((mem_kb / 1024 / 1024))
fi
echo "  \"memory_gb\": ${mem_gb},"

# GPU
if [[ "$OSTYPE" == "darwin"* ]]; then
  gpu=$(system_profiler SPDisplaysDataType 2>/dev/null | grep "Chipset" | head -1 | cut -d: -f2 | xargs || echo "unknown")
  echo "  \"gpu\": \"${gpu}\","
else
  gpu=$(lspci 2>/dev/null | grep -i "vga\|3d\|display" | head -1 | cut -d: -f3 | xargs || echo "unknown")
  echo "  \"gpu\": \"${gpu}\","
fi

# Local subnet (for network scanning)
primary_ip=$(ipconfig getifaddr en0 2>/dev/null || ip addr show 2>/dev/null | grep 'inet ' | grep -v '127.0.0.1' | head -1 | awk '{print $2}' | cut -d/ -f1 || echo "unknown")
subnet=$(echo "$primary_ip" | cut -d. -f1-3)
echo "  \"local_subnet\": \"${subnet}.0/24\","
ips=$(ifconfig 2>/dev/null | grep "inet " | grep -v "127.0.0.1" | awk '{print $2}' | paste -sd "," - || echo "unknown")
echo "  \"ip\": [$(echo "$ips" | sed 's/,/\", \"/g; s/^/\"/; s/$/\"/')],"

# Hermes version
hermes_cmd=$(command -v hermes 2>/dev/null || echo "$HOME/.hermes/hermes-agent/venv/bin/hermes")
hermes_ver=$("$hermes_cmd" --version 2>/dev/null | head -1 || echo "unknown")
echo "  \"hermes_version\": \"${hermes_ver}\","

# Python
python_ver=$(python3 --version 2>/dev/null | awk '{print $2}' || echo "none")
echo "  \"python\": \"${python_ver}\","

# Docker
if command -v docker &>/dev/null; then
  docker_ver=$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ',' || echo "unknown")
  echo "  \"docker\": \"${docker_ver}\","
else
  echo "  \"docker\": null,"
fi

# Node
if command -v node &>/dev/null; then
  node_ver=$(node --version 2>/dev/null || echo "unknown")
  echo "  \"node\": \"${node_ver}\","
else
  echo "  \"node\": null,"
fi

# Bun
if command -v bun &>/dev/null; then
  bun_ver=$(bun --version 2>/dev/null || echo "unknown")
  echo "  \"bun\": \"${bun_ver}\","
else
  echo "  \"bun\": null,"
fi

echo "  \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
echo "}"
