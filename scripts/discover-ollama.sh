#!/bin/bash
# discover-ollama.sh — Ollama 模型探测
# 扫描局域网中所有 Ollama 实例，列出模型

set -euo pipefail
SCHEMA="$HOME/.hermes/skills/agent-embodiment/body-schema.json"
endpoints=()

# 从 schema 读取已知端点
if [[ -f "$SCHEMA" ]]; then
  schema_endpoints=$(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    access = d.get('access', {})
    if isinstance(access, dict) and 'ollama_api' in access:
        print(access['ollama_api']['url'])
" 2>/dev/null)
  while IFS= read -r ep; do
    [[ -n "$ep" ]] && endpoints+=("$ep")
  done <<< "$schema_endpoints"
fi

# 也扫常见 Ollama 端口（通过 arp 表的存活主机）
for ip in $(arp -a 2>/dev/null | grep -oE '192\.168\.[0-9]+\.[0-9]+' | sort -u); do
  url="http://${ip}:11434"
  # 避免重复
  if [[ ${#endpoints[@]} -eq 0 ]] || [[ ! " ${endpoints[*]} " =~ " ${url} " ]]; then
    if curl -s --max-time 2 "$url/api/tags" >/dev/null 2>&1; then
      endpoints+=("$url")
    fi
  fi
done

# 也测试 schema 中已配置的 endpoint（跨网段）
if [[ -f "$SCHEMA" ]]; then
  known_endpoints=$(python3 -c "
import json
with open('$SCHEMA') as f:
    data = json.load(f)
for d in data.get('devices', []):
    access = d.get('access', {})
    if isinstance(access, dict) and 'ollama_api' in access:
        url = access['ollama_api'].get('url', '')
        if url:
            print(url)
" 2>/dev/null)
  while IFS= read -r ep; do
    set +u
    if [[ ${#endpoints[@]} -eq 0 ]] || [[ ! " ${endpoints[*]} " =~ " ${ep} " ]]; then
      if curl -s --max-time 3 "$ep/api/tags" >/dev/null 2>&1; then
        endpoints+=("$ep")
      fi
    fi
    set -u
  done <<< "$known_endpoints"
fi

set +u
echo "found ${#endpoints[@]} ollama instance(s)"
set -u
echo "---"

set +u
for endpoint in "${endpoints[@]}"; do
  echo "endpoint: $endpoint"
set -u

  # 获取模型列表
  response=$(curl -s --max-time 5 "$endpoint/api/tags" 2>/dev/null)

  if [[ -z "$response" ]]; then
    echo "  status: unreachable"
    continue
  fi

  # 解析模型信息
  python3 -c "
import json, sys
try:
    data = json.loads('''$response''')
    models = data.get('models', [])
    print(f'  models: {len(models)}')
    for m in models:
        name = m.get('name', 'unknown')
        size_gb = m.get('size', 0) / 1e9
        params = m.get('details', {}).get('parameter_size', '?')
        quant = m.get('details', {}).get('quantization_level', '?')
        print(f'    - {name} ({params}, {quant}, {size_gb:.1f}GB)')
except Exception as e:
    print(f'  parse_error: {e}')
" 2>/dev/null

  echo ""
done

echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
