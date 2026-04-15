#!/bin/bash
# discover-inference.sh — 本地推理能力探测
# 检测 GPU、VRAM、推理后端（Ollama/vLLM/llama.cpp）、可用模型
# 输出 JSON 格式，可直接合并入 body-schema.json

set -euo pipefail

SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"
results="[]"

# ============================================================
# 1. 本机 GPU 探测
# ============================================================
echo "--- 本机 GPU ---"

gpu_info="[]"

# NVIDIA (CUDA)
if command -v nvidia-smi &>/dev/null; then
  echo "backend: CUDA (nvidia-smi)"
  nvidia_out=$(nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,driver_version,temperature.gpu,utilization.gpu \
    --format=csv,noheader,nounits 2>/dev/null || true)
  
  if [[ -n "$nvidia_out" ]]; then
    idx=0
    while IFS= read -r line; do
      name=$(echo "$line" | cut -d',' -f1 | xargs)
      mem_total=$(echo "$line" | cut -d',' -f2 | xargs)
      mem_used=$(echo "$line" | cut -d',' -f3 | xargs)
      mem_free=$(echo "$line" | cut -d',' -f4 | xargs)
      driver=$(echo "$line" | cut -d',' -f5 | xargs)
      temp=$(echo "$line" | cut -d',' -f6 | xargs)
      util=$(echo "$line" | cut -d',' -f7 | xargs)
      
      echo "  GPU $idx: $name | ${mem_total}MB total, ${mem_free}MB free | ${util}% util | ${temp}°C"
      
      gpu_info=$(python3 -c "
import json, sys
info = json.loads('$gpu_info') if '$gpu_info' != '[]' else []
info.append({
    'index': $idx,
    'name': '$name',
    'backend': 'cuda',
    'memory_total_mb': $mem_total,
    'memory_used_mb': $mem_used,
    'memory_free_mb': $mem_free,
    'driver': '$driver',
    'temperature': $temp,
    'utilization': $util
})
print(json.dumps(info))
" 2>/dev/null || echo "$gpu_info")
      idx=$((idx + 1))
    done <<< "$nvidia_out"
  fi
fi

# Apple Metal (macOS)
if [[ "$(uname)" == "Darwin" ]]; then
  metal_info=$(system_profiler SPDisplaysDataType 2>/dev/null | grep -E "Chipset|VRAM|Metal" | head -5 || true)
  if [[ -n "$metal_info" ]]; then
    gpu_name=$(system_profiler SPDisplaysDataType 2>/dev/null | grep "Chip Model" | head -1 | sed 's/.*: //' || echo "Apple GPU")
    gpu_mem=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}' || echo "?")
    echo "backend: Metal ($gpu_name, shared ${gpu_mem}GB)"
    
    gpu_info=$(python3 -c "
import json
info = json.loads('$gpu_info') if '$gpu_info' != '[]' else []
info.append({
    'index': 0,
    'name': '$gpu_name',
    'backend': 'metal',
    'memory_total_mb': int('$gpu_mem') * 1024 if '$gpu_mem' != '?' else 0,
    'memory_note': 'unified_memory'
})
print(json.dumps(info))
" 2>/dev/null || echo "$gpu_info")
  fi
fi

# AMD (rocm-smi, less common)
if command -v rocm-smi &>/dev/null; then
  echo "backend: ROCm (AMD)"
  rocm_out=$(rocm-smi --showproductname --showmeminfo vram --csv 2>/dev/null || true)
  if [[ -n "$rocm_out" ]]; then
    echo "  $rocm_out"
    gpu_info=$(python3 -c "
import json
info = json.loads('$gpu_info') if '$gpu_info' != '[]' else []
info.append({'index': 0, 'name': 'AMD GPU', 'backend': 'rocm'})
print(json.dumps(info))
" 2>/dev/null || echo "$gpu_info")
  fi
fi

if [[ "$gpu_info" == "[]" ]]; then
  echo "  无独立 GPU（CPU-only 推理）"
fi

# ============================================================
# 2. 本机推理后端探测
# ============================================================
echo ""
echo "--- 推理后端 ---"

backends="[]"

# Ollama（本地 + 远程）
ollama_local="http://localhost:11434"
if curl -s --max-time 2 "$ollama_local/api/tags" >/dev/null 2>&1; then
  echo "ollama: running (localhost:11434)"
  
  # 获取模型列表 + 运行状态
  tags_resp=$(curl -s --max-time 5 "$ollama_local/api/tags" 2>/dev/null)
  running_resp=$(curl -s --max-time 5 "$ollama_local/api/ps" 2>/dev/null)
  
  model_info=$(python3 -c "
import json
tags = json.loads('''$tags_resp''') if '''$tags_resp''' else {'models': []}
running = json.loads('''$running_resp''') if '''$running_resp''' else {'models': []}
running_names = {m['name'] for m in running.get('models', [])}

models = []
for m in tags.get('models', []):
    name = m.get('name', '?')
    size_gb = m.get('size', 0) / 1e9
    params = m.get('details', {}).get('parameter_size', '?')
    quant = m.get('details', {}).get('quantization_level', '?')
    models.append({
        'name': name,
        'size_gb': round(size_gb, 1),
        'parameters': params,
        'quantization': quant,
        'loaded': name in running_names
    })

print(json.dumps(models))
" 2>/dev/null || echo "[]")
  
  backends=$(python3 -c "
import json
backends = json.loads('$backends') if '$backends' != '[]' else []
models = json.loads('$model_info')
backends.append({
    'type': 'ollama',
    'url': '$ollama_local',
    'status': 'running',
    'models': models,
    'models_count': len(models),
    'loaded_count': sum(1 for m in models if m.get('loaded'))
})
print(json.dumps(backends))
" 2>/dev/null || echo "$backends")
  
  echo "  models: $(echo "$model_info" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))" 2>/dev/null || echo "?")"
fi

# vLLM（常见端口 8000）
for port in 8000 8001 8080; do
  vllm_url="http://localhost:$port"
  if curl -s --max-time 2 "$vllm_url/v1/models" >/dev/null 2>&1; then
    echo "vllm: running (localhost:$port)"
    vllm_models=$(curl -s --max-time 3 "$vllm_url/v1/models" 2>/dev/null | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    models = data.get('data', [])
    for m in models:
        print(f'  - {m.get(\"id\", \"?\")}')
    print(f'  total: {len(models)}')
except: print('  parse_error')
" 2>/dev/null || true)
    echo "$vllm_models"
    
    backends=$(python3 -c "
import json
backends = json.loads('$backends') if '$backends' != '[]' else []
backends.append({'type': 'vllm', 'url': '$vllm_url', 'status': 'running'})
print(json.dumps(backends))
" 2>/dev/null || echo "$backends")
    break
  fi
done

# llama.cpp server（常见端口 8080, 8888）
for port in 8080 8888; do
  llama_url="http://localhost:$port"
  if curl -s --max-time 2 "$llama_url/health" >/dev/null 2>&1; then
    echo "llama.cpp: running (localhost:$port)"
    
    backends=$(python3 -c "
import json
backends = json.loads('$backends') if '$backends' != '[]' else []
backends.append({'type': 'llama_cpp', 'url': '$llama_url', 'status': 'running'})
print(json.dumps(backends))
" 2>/dev/null || echo "$backends")
    break
  fi
done

# LM Studio（常见端口 1234）
for port in 1234; do
  lmstudio_url="http://localhost:$port"
  if curl -s --max-time 2 "$lmstudio_url/v1/models" >/dev/null 2>&1; then
    echo "lmstudio: running (localhost:$port)"
    
    backends=$(python3 -c "
import json
backends = json.loads('$backends') if '$backends' != '[]' else []
backends.append({'type': 'lmstudio', 'url': '$lmstudio_url', 'status': 'running'})
print(json.dumps(backends))
" 2>/dev/null || echo "$backends")
    break
  fi
done

if [[ "$backends" == "[]" ]]; then
  echo "  未检测到运行中的推理后端"
fi

# ============================================================
# 3. 远程设备推理能力（从 schema 读取）
# ============================================================
echo ""
echo "--- 远程推理端点 ---"

if [[ -f "$SCHEMA" ]]; then
  remote_endpoints=$(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    access = d.get('access', {})
    if isinstance(access, dict) and 'ollama_api' in access:
        url = access['ollama_api'].get('url', '')
        if url:
            print(f'{d[\"id\"]}|{url}')
" 2>/dev/null || true)
  
  while IFS='|' read -r dev_id url; do
    [[ -z "$dev_id" ]] && continue
    if curl -s --max-time 3 "$url/api/tags" >/dev/null 2>&1; then
      resp=$(curl -s --max-time 5 "$url/api/tags" 2>/dev/null)
      count=$(echo "$resp" | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
      echo "  $dev_id ($url): reachable, $count models"
    else
      echo "  $dev_id ($url): unreachable"
    fi
  done <<< "$remote_endpoints"
else
  echo "  (无 body-schema.json，跳过远程探测)"
fi

# ============================================================
# 4. 推理容量评估
# ============================================================
echo ""
echo "--- 推理容量评估 ---"

python3 -c "
import json, subprocess

gpu = json.loads('$gpu_info') if '$gpu_info' != '[]' else []
backends = json.loads('$backends') if '$backends' != '[]' else []

# GPU VRAM 估算可运行的模型大小
total_free_vram = 0
for g in gpu:
    if g.get('backend') in ('cuda', 'rocm'):
        total_free_vram += g.get('memory_free_mb', 0)

# 经验法则：Q4 量化模型约需 参数量(GB) * 1.2 的 VRAM
# 7B Q4 ≈ 5GB, 13B Q4 ≈ 9GB, 70B Q4 ≈ 45GB
if total_free_vram > 0:
    free_gb = total_free_vram / 1024
    if free_gb >= 45:
        tier = '70B+ (Q4)'
    elif free_gb >= 15:
        tier = '13B-33B (Q4)'
    elif free_gb >= 7:
        tier = '7B-13B (Q4)'
    elif free_gb >= 4:
        tier = '7B (Q4)'
    else:
        tier = '3B 以下'
    print(f'  可用 VRAM: {free_gb:.1f}GB → 约可运行 {tier}')
elif gpu and gpu[0].get('backend') == 'metal':
    print('  Apple Metal: 统一内存，模型大小受总内存限制')
else:
    print('  无 GPU → CPU 推理，速度约 5-15 tok/s (7B Q4)')

# 已加载模型状态
loaded = 0
for b in backends:
    loaded += b.get('loaded_count', 0)
if loaded > 0:
    print(f'  当前已加载模型: {loaded} 个')
" 2>/dev/null || echo "  评估失败"

echo ""
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
