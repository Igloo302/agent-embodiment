#!/bin/bash
# discover-inference.sh — 本地推理能力探测（通用，不绑定特定后端）
# 自动检测 GPU、VRAM、推理后端（Ollama/vLLM/llama.cpp/LM Studio/任意 OpenAI 兼容 API）
# 新用户友好：无 body-schema.json 时也能跑

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"

echo "=== 推理能力探测 ==="
echo ""

# ---------------------------------------------------------------
# 1. GPU 探测
# ---------------------------------------------------------------
echo "--- GPU ---"
gpu_backend="none"
gpu_name="none"
gpu_mem_total=0
gpu_mem_free=0

# NVIDIA (CUDA)
if command -v nvidia-smi &>/dev/null; then
  gpu_backend="cuda"
  nvidia_out=$(nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 || true)
  if [[ -n "$nvidia_out" ]]; then
    gpu_name=$(echo "$nvidia_out" | cut -d',' -f1 | xargs)
    gpu_mem_total=$(echo "$nvidia_out" | cut -d',' -f2 | xargs)
    gpu_mem_free=$(echo "$nvidia_out" | cut -d',' -f3 | xargs)
    echo "  $gpu_name (${gpu_backend})"
    echo "  VRAM: ${gpu_mem_total}MB total, ${gpu_mem_free}MB free"
  fi
# Apple Metal
elif [[ "$(uname)" == "Darwin" ]]; then
  gpu_backend="metal"
  gpu_name=$(system_profiler SPDisplaysDataType 2>/dev/null | grep "Chip Model" | head -1 | sed 's/.*: //' || echo "Apple GPU")
  mem_gb=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}' || echo "0")
  echo "  $gpu_name (${gpu_backend}, unified ${mem_gb}GB)"
# AMD (ROCm)
elif command -v rocm-smi &>/dev/null; then
  gpu_backend="rocm"
  echo "  AMD GPU (${gpu_backend})"
else
  echo "  无独立 GPU（CPU-only）"
fi

# ---------------------------------------------------------------
# 2. 推理后端探测（通用，扫描常见端口和协议）
# ---------------------------------------------------------------
echo ""
echo "--- 推理后端 ---"

backends_found=0

# 探测函数：测试一个 OpenAI 兼容的 /v1/models 端点
check_openai_compat() {
  local url="$1" name="$2"
  resp=$(curl -s --max-time 3 "$url/v1/models" 2>/dev/null || true)
  if [[ -n "$resp" ]] && echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if 'data' in d or 'models' in d else 1)" 2>/dev/null; then
    count=$(echo "$resp" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('data', d.get('models',[]))))" 2>/dev/null || echo "?")
    echo "  $name ($url): running, $count models"
    backends_found=$((backends_found + 1))
    return 0
  fi
  return 1
}

# 探测函数：测试 Ollama API
check_ollama() {
  local url="$1" label="$2"
  resp=$(curl -s --max-time 3 "$url/api/tags" 2>/dev/null || true)
  if [[ -n "$resp" ]] && echo "$resp" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
    count=$(echo "$resp" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
    echo "  Ollama ($url): running, $count models"
    
    # 列出模型
    echo "$resp" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for m in d.get('models', []):
    name = m.get('name', '?')
    size_gb = m.get('size', 0) / 1e9
    params = m.get('details', {}).get('parameter_size', '?')
    quant = m.get('details', {}).get('quantization_level', '?')
    print(f'    - {name} ({params}, {quant}, {size_gb:.1f}GB)')
" 2>/dev/null || true
    
    # 检查已加载模型
    loaded=$(curl -s --max-time 2 "$url/api/ps" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
models = d.get('models', [])
if models:
    print(', '.join(m.get('name','?') for m in models))
else:
    print('none')
" 2>/dev/null || echo "unknown")
    echo "    loaded: $loaded"
    
    backends_found=$((backends_found + 1))
    return 0
  fi
  return 1
}

# 本机扫描
echo "  本机扫描:"
check_ollama "http://localhost:11434" "localhost:11434" || true
check_openai_compat "http://localhost:8000" "localhost:8000 (vLLM)" || true
check_openai_compat "http://localhost:1234" "localhost:1234 (LM Studio)" || true

# llama.cpp (health check)
for port in 8080 8888; do
  if curl -s --max-time 2 "http://localhost:$port/health" >/dev/null 2>&1; then
    echo "  llama.cpp (localhost:$port): running"
    backends_found=$((backends_found + 1))
  fi
done

# 远程扫描（从 body-schema.json 读取已知端点，或从 ARP 扫描）
if [[ -f "$SCHEMA" ]]; then
  remote_endpoints=$(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    access = d.get('access', {})
    if isinstance(access, dict):
        if 'ollama_api' in access:
            url = access['ollama_api'].get('url', '')
            if url: print(f\"{d.get('id','?')}|ollama|{url}\")
" 2>/dev/null || true)
  
  while IFS='|' read -r dev_id backend url; do
    [[ -z "$dev_id" ]] && continue
    if [[ "$backend" == "ollama" ]]; then
      check_ollama "$url" "$dev_id" || true
    fi
  done <<< "$remote_endpoints"
fi

# ARP 补充扫描 Ollama 常见端口
for ip in $(arp -a 2>/dev/null | grep -oE '([0-9]+\.){3}[0-9]+' | sort -u); do
  # 跳过已覆盖的
  [[ "$ip" == "127.0.0.1" ]] && continue
  if curl -s --max-time 2 "http://$ip:11434/api/tags" >/dev/null 2>&1; then
    # 避免重复
    if ! echo "$remote_endpoints" 2>/dev/null | grep -q "$ip"; then
      check_ollama "http://$ip:11434" "$ip:11434" || true
    fi
  fi
done

if [[ $backends_found -eq 0 ]]; then
  echo "  未检测到运行中的推理后端"
fi

# ---------------------------------------------------------------
# 3. 推理容量评估
# ---------------------------------------------------------------
echo ""
echo "--- 容量评估 ---"

python3 -c "
backend = '$gpu_backend'
free_mb = $gpu_mem_free
total_mb = $gpu_mem_total

if backend == 'cuda' and free_mb > 0:
    free_gb = free_mb / 1024
    if free_gb >= 45: tier = '70B+ (Q4)'
    elif free_gb >= 15: tier = '13B-33B (Q4)'
    elif free_gb >= 7: tier = '7B-13B (Q4)'
    elif free_gb >= 4: tier = '7B (Q4)'
    else: tier = '3B 以下'
    print(f'  可用 VRAM: {free_gb:.1f}GB → 约可运行 {tier}')
elif backend == 'metal':
    print('  Apple Metal: 统一内存，模型大小受总内存限制')
elif backend == 'rocm':
    print('  AMD ROCm: 需手动评估')
else:
    print('  无 GPU → CPU 推理，7B Q4 约 5-15 tok/s')
" 2>/dev/null || echo "  评估失败"

echo ""
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
