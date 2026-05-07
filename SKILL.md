---
name: agent-embodiment
description: |
  让 Agent 理解自己的「身体」和所处的物理世界——我是谁、我在哪、我能控制什么、我的边界。
  只管「有什么」，不管「怎么用」。操作由各自的 skill 负责（PVE、Docker、Ollama 等）。
  触发词：我的环境、我在哪跑、有什么设备、扫描网络、embodiment、body schema。
  English triggers: what am I running on, my devices, scan network, my environment.
  ⚠️ 首次加载检测：如果 body-schema.json 不存在，主动询问用户是否要初始化。
---

# Agent Embodiment · 身体感

> 我知道自己是谁、站在哪里、周围有什么。

> **📁 路径说明**：本文档中用 `<SKILL_DIR>` 表示 skill 所在的根目录，实际路径取决于你的 Agent 软件。
> 例如 Hermes Agent 下为 `~/.hermes/skills/agent-embodiment/`，其他软件请自行替换。

## 🖥️ 平台兼容性

**当前状态**：在 macOS 上完整测试通过。Linux/Windows 可运行但需要针对性调整。

**跨平台脚本**（无需修改）：
- `discover-network.sh` — 使用 `arp -a`, `nc -z`，Linux/macOS 通用
- `merge-schema.py` — 纯 Python，跨平台

**需要调整的脚本**：

| 脚本 | macOS 特有命令 | Linux 替代方案 |
|------|----------------|----------------|
| `discover-self.sh` | `system_profiler`, `sysctl -n machdep.cpu.brand_string` | `/proc/cpuinfo`, `lscpu` |
| `discover-hardware.sh` | `system_profiler SPAudioDataType` 等 | `lspci`, `lsusb`, `/proc/asound` |
| `discover-inference.sh` | `system_profiler SPDisplaysDataType` (Apple Metal) | `nvidia-smi`, `lspci \| grep -i vga` |

**适配方式**：在脚本中检测 `uname`，分支处理不同平台。

## ⚠️ 首次加载检测（Agent 必读）

**加载此 skill 时，立即检查**：

```bash
test -f <SKILL_DIR>/body-schema.json && echo "exists" || echo "not_found"
```

**如果 body-schema.json 不存在**，主动询问用户：

```
👋 检测到这是首次使用 Agent Embodiment。

我可以帮你自动发现：
  🔍 本机信息（系统、CPU、内存、IP）
  🌐 网络设备（扫描局域网内的服务器、NAS、VM 等）
  🎮 推理能力（GPU、Ollama、模型）
  📷 硬件设备（摄像头、音频、蓝牙等）

要现在开始自动扫描吗？（约 1-2 分钟）
```

**用户确认后**，执行一键初始化（见 Phase 0）。

**如果 body-schema.json 已存在**，跳过询问，正常加载 skill。

## 核心定位

**只管「有什么」，不管「怎么用」**

| 职责 | 属于 embodiment | 属于其他 skill |
|------|----------------|---------------|
| 发现设备 | ✅ | ❌ |
| 记录设备信息 | ✅ | ❌ |
| 查询设备状态 | ✅ | ❌ |
| 操作设备 | ❌ | PVE skill, Docker skill, Ollama skill 等 |
| 安全分级 | ❌ | 各操作 skill 自己负责 |
| 验证操作结果 | ❌ | 各操作 skill 自己负责 |

**embodiment 只回答「有什么」，不执行操作。**

### 架构原则：Agent Orchestrates, Scripts Process

整个 embodiment 生态遵循一条红线：

| 由谁做 | 做什么 | 为什么 |
|--------|--------|--------|
| **Agent（AI）** | 读取外部信息（记忆、Hindsight、配置、对话上下文）、做判断、决定调用哪些脚本 | Agent 知道上下文和意图，能做弹性决策 |
| **脚本/工具** | 纯函数式数据处理：接收参数 → 处理 → 输出结果。不读文件，不联网，不做推理 | 脚本是确定性的，可测试的，不会因为文件缺失而崩溃 |

**典型分解示例**（这次会话中用户纠正的案例）：

```
❌ 错误：脚本自己读 MEMORY.md 解析设备
    merge-schema.py → read_file("MEMORY.md") → 正则提取 IP → 补充到 schema

✅ 正确：Agent 读取记忆 → 通过参数传给脚本
    Agent → hindsight_recall("我的设备") → 提取列表 →
    merge-schema.py --memory-devices '[{...}]' → 补充到 schema
```

**好处**：
- 脚本不依赖特定的存储格式（今天用 MEMORY.md，明天换 Hindsight，脚本不需要改）
- Agent 可以灵活组合多个信息源（记忆 + 当前对话 + 实时探测）
- 脚本变得可测试：给什么输入，输出什么结果，不需要文件系统 mock

## 设计理念

人有「本体感」（proprioception）——闭上眼睛你也知道自己手在哪、能举多重。

Agent 也需要类似的能力：

- **我是谁** — 我跑在什么系统上，什么配置
- **我在哪** — 网络拓扑、局域网里有什么
- **我能动什么** — 可控设备清单和能力边界
- **什么不能碰** — 安全红线和分级确认

这不是任何特定平台的管理工具。这是 Agent 的**身体 Schema**。
适用于任何能执行 shell 命令的 Agent——Hermes Agent、Claude Code、OpenClaw、Cursor、Codex CLI。
运行在 Mac、Linux、Docker 容器、NAS、甚至嵌入式设备上。

---

## Phase 0: 一键初始化（Setup Wizard）

**触发条件**：用户确认首次加载时的询问，或用户主动说「初始化」「扫描环境」。

**完整流程**（5个阶段）：

### Phase 0.0: 环境检查

```
1. 检查 MCP Server 状态
   - query_device 工具可用？
   - learn_device 工具可用？
   - 失败 → 自动配置 MCP（见下方「MCP 自动配置」）

2. 检查依赖
   - Python 3.8+
   - nmap / arp / ping（网络扫描）
   - 缺失 → 提示安装命令

3. 检查权限
   - 网络访问权限（macOS 需要授权）
   - 摄像头/麦克风权限（可选）
```

#### MCP 自动配置

如果 MCP 工具不可用，Agent 自动执行：

```bash
# 1. 检查 MCP wrapper 脚本
test -f ~/.hermes/scripts/embodiment-mcp.sh || {
  # 创建 wrapper 脚本
  mkdir -p ~/.hermes/scripts
  cat > ~/.hermes/scripts/embodiment-mcp.sh << 'EOF'
#!/bin/bash
cd <SKILL_DIR>/mcp
exec ~/.hermes/hermes-agent/venv/bin/python server.py
EOF
  chmod +x ~/.hermes/scripts/embodiment-mcp.sh
}

# 2. 检查 config.yaml 中的 MCP 配置
grep -q "embodiment:" ~/.hermes/config.yaml || {
  # 追加 MCP 配置
  cat >> ~/.hermes/config.yaml << 'EOF'

mcp_servers:
  embodiment:
    command: <SKILL_DIR>/mcp/.venv/bin/python
    args:
      - <SKILL_DIR>/mcp/server.py
    description: Agent Embodiment - Device and infrastructure management
EOF
}

# 3. 提示用户重启 Hermes
echo "✅ MCP 配置已添加，请重启 Hermes Agent 使其生效"
```

**用户确认**：
- 配置完成后提示：「MCP 已配置，需要重启 Hermes 才能生效。是否现在重启？」
- 用户确认 → 重启 Hermes
- 用户拒绝 → 继续用脚本方式，提示「MCP 工具将在下次启动时可用」

### Phase 0.1: 本机扫描（~5秒）

采集：hostname、OS、架构、CPU、内存、IP、MAC、硬件能力

### Phase 0.2: 网络扫描（~30-60秒）

- 自动检测网段（en0 → 本地网络，zt* → ZeroTier）
- ARP 扫描 → 端口探测 → 服务识别
- 发现设备列表展示（可逐个确认）

### Phase 0.3: 能力探测（可选，~1-2分钟）

对已确认设备深入探测：
- PVE → SSH 测试（需要认证则引导配置 SSH 密钥）
- Ollama → GET /api/tags → 发现模型
- ComfyUI → GET /system_stats → 发现 GPU

**凭据处理原则**：
- 不存储密码/token 到 schema
- SSH：引导用户配置 `~/.ssh/config`
- API：引导用户设置环境变量

### Phase 0.4: 生成 Schema & 演示

1. 写入 body-schema.json
2. 首次查询演示（让用户看到 query_device 效果）
3. 完成确认

**自动执行全部步骤**（约 1-2 分钟）：

```bash
# 1. 本机发现
bash <SKILL_DIR>/scripts/discover-self.sh

# 2. 网络扫描
bash <SKILL_DIR>/scripts/discover-network.sh

# 3. 生成 Schema（会自动调用上面两个脚本 + 合并结果）
python3 <SKILL_DIR>/scripts/merge-schema.py
```

完成后汇报：

```
✅ 初始化完成！

📡 我的「身体」：
  - 主机：{hostname} ({os} {arch})
  - 网络设备：{N} 台
  - 推理能力：{摘要}

我的「身体档案」已保存：<SKILL_DIR>/body-schema.json

以后你可以直接问我：
  - 「你跑在什么上面？」→ 我读档案回答
  - 「扫描一下网络」→ 我重新发现
  - 「设备状态怎么样？」→ 我报告网络拓扑

随时叫我就好 🤖
```

### 跳过初始化

用户说「跳过」「不用」「以后再说」→ 不执行初始化，skill 正常加载，下次启动时不再询问（创建空的 body-schema.json 标记已访问）。

---

## Phase 1: 缓存检查 + 发现与探测

schema 已存在时，先检查缓存再决定做什么。

### 缓存检查

- 文件存在且距上次发现 **< 1 小时** → 直接用缓存，跳到 Phase 3
- 文件不存在 → 跳到 Phase 0（首次运行引导）
- 文件损坏/JSON 解析失败 → 删除重建，跳到 Phase 0
- 距上次发现 **> 24 小时** 且用户要求操作 → 建议刷新后再操作

### 发现模式

| 用户意图 | 模式 | 跑哪些脚本 |
|---------|------|-----------|
| 问「我在哪跑」「有什么设备」 | **快速读取** | 不跑脚本，直接读 schema |
| 说「看看 Ollama」 | **定向发现** | 只跑 1.3 (discover-inference.sh) |
| 说「扫描网络」「看看环境」 | **定向发现** | 跑 1.2 + 1.3 |
| 首次激活 / schema 缺失 | **完整发现** | 跑 1.1-1.5 全部 |

按需运行脚本。**定向发现**只跑相关的，**完整发现**全跑。

> 1.1-1.4 的脚本互相独立，可以并行跑。1.5 依赖 1.2 的网络发现结果，必须等 1.2 完成。

### 1.1 本机信息

```bash
bash <SKILL_DIR>/scripts/discover-self.sh
```

采集：hostname、OS、架构、CPU、内存、IP、Hermes 版本、Python/Docker/Node 状态。

**失败 fallback**：
```bash
echo "hostname:$(hostname) os:$(uname -s) arch:$(uname -m) ip:$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
```

### 1.2 网络发现

```bash
bash <SKILL_DIR>/scripts/discover-network.sh
```

**自动发现流程**：
1. **路由表解析** — 从 `netstat -rn` 提取所有可达私有网段（192.168.x, 10.x, 172.16-31.x）
2. **设备扫描** — 并行 ping 每个网段的全部 254 个 IP（分批 50 个等待）
3. **端口扫描** — 对存活设备扫描 27 种常用端口

**MAC 地址获取**：
- 输出格式：`IP MAC Port Service Status`（5列）
- MAC 从 ARP 表获取（`arp -a` 解析）
- 无 ARP 记录的设备显示 `?`

**进度汇报**：每个网段扫描完成后汇报发现数量。

**失败 fallback**：
```bash
net=$(ipconfig getifaddr en0 2>/dev/null | cut -d. -f1-3)
for i in $(seq 1 20); do ping -c 1 -t 1 ${net}.$i 2>/dev/null && echo "${net}.$i alive"; done
```

**注意事项**：
- 扫描 5 个网段 × 254 IP 需 10-15 分钟，建议后台运行
- 不要缩减扫描范围，必须覆盖全部 IP 避免遗漏设备
- ping 超时设为 1 秒（`-t 1`）
- MAC 地址仅在设备有 ARP 记录时可用（需同网段或之前通信过）

### 1.3 推理能力

```bash
bash <SKILL_DIR>/scripts/discover-inference.sh
```

探测 GPU（CUDA/Metal/ROCm）、VRAM、推理后端（Ollama/vLLM/llama.cpp/LM Studio）、模型清单、容量评估。**不绑定特定后端**。

**ARP 扫描策略**：

`discover-inference.sh` 会扫描 ARP 表中的所有 IP，探测 Ollama 端口（11434）。

| 场景 | ARP 表大小 | 扫描时间 | 策略 |
|------|-----------|---------|------|
| 小型网络 | < 50 IP | < 1 分钟 | 直接全扫 |
| 中型网络 | 50-200 IP | 1-3 分钟 | 分批扫描（每 20 IP 暂停 0.5s） |
| 大型网络 | > 200 IP | > 3 分钟 | 分批扫描 + 用户确认 |

**分批扫描实现**（已内置）：
```bash
batch_size=20
for ip in $arp_ips; do
  curl --max-time 1 "http://$ip:11434/api/tags" ...
  # 每 20 个 IP 暂停 0.5 秒，避免网络拥塞
  if [[ $((count % batch_size)) -eq 0 ]]; then
    sleep 0.5
  fi
done
```

**注意**：ARP 表可能包含过期条目（如 500+ IP），这是正常的。分批扫描保证不会超时或阻塞。

**输出字段**（自动合并到 `body-schema.json` 的 `self.gpu` 和 `self.inference_backends`）：

| 字段 | 说明 | 示例 |
|------|------|------|
| `gpu.backend` | GPU 类型 | `cuda`, `metal`, `rocm`, `cpu` |
| `gpu.name` | GPU 名称 | `Apple GPU`, `NVIDIA GeForce RTX 5070` |
| `gpu.memory_total_mb` | 总显存/统一内存 | `16384`, `12288` |
| `gpu.memory_free_mb` | 可用显存 | `8192` |
| `inference_backends[].type` | 后端类型 | `ollama`, `vllm`, `llama.cpp` |
| `inference_backends[].url` | API 地址 | `http://localhost:11434` |
| `inference_backends[].models` | 模型列表 | `["gemma4:e4b", "qwen2.5:7b"]` |

### 1.4 本机硬件

```bash
bash <SKILL_DIR>/scripts/discover-hardware.sh
```

音频设备、蓝牙、显示器、摄像头、USB、打印机、挂载存储。

**输出字段**（自动合并到 `body-schema.json` 的 `self.hardware`）：

| 字段 | 说明 | 示例 |
|------|------|------|
| `hardware.cameras` | 摄像头列表 | `[{"name": "FaceTime HD Camera"}]` |
| `hardware.audio` | 音频设备 | `[{"name": "MacBook Pro扬声器"}]` |
| `hardware.displays` | 显示器 | `[{"name": "Color LCD"}]` |
| `hardware.bluetooth` | 蓝牙状态和设备 | `{"state": "On", "devices": [...]}` |
| `hardware.usb` | USB 设备 | `[{"name": "USB Keyboard"}]` |
| `hardware.storage` | 挂载存储 | `[{"filesystem": "/dev/disk3s1", "used": "418Gi", "total": "460Gi", "mount": "/"}]` |

**查询硬件能力**：

```python
# 通过 MCP 查询
mcp_embodiment_query_device()  # 无参数返回完整 schema

# 或直接读取
python3 -c "
import json
with open('<SKILL_DIR>/body-schema.json') as f:
    s = json.load(f)
print('GPU:', s['self'].get('gpu', {}).get('name'))
print('摄像头:', len(s['self'].get('hardware', {}).get('cameras', [])))
"
```

### 1.5 设备深入探测

对已发现的设备进一步探测。Agent 按以下决策树执行：

```
遍历 body-schema.json 的 devices 列表：
  ├── hypervisor → 运行 discover-pve.sh 或 SSH `qm list`
  ├── vm → 根据 access.method 连接（SSH/HTTP）
  ├── docker_host → `docker ps` / Docker API
  ├── inference_server → GET /api/tags 或 /v1/models
  ├── nas → DSM API / SMB 列共享
  └── smart_home → 对应 skill 探测
```

| type | 探测命令 |
|------|---------|
| `hypervisor` | `<SKILL_DIR>/scripts/discover-pve.sh <ip>` |
| `vm` | SSH `uname -a && df -h && free -h` |
| `docker_host` | `docker ps -a --format '{{.Names}} {{.Status}}'` |
| `inference_server` | `curl -s http://<ip>:11434/api/tags` |
| `nas` | `curl -s http://<ip>:5000/webapi/entry.cgi` |

如果 `access` 字段不可用（缺密码/key），跳过该设备，标记 `status: auth_required`。

### 1.6 发现确认

完成后暂停，向用户汇报：

```
📡 发现完成：
  - 本机：{hostname} ({os} {arch})
  - 网络设备：{N} 台存活，{M} 台已探测
  - 推理能力：{摘要}

这些信息正确吗？需要手动添加/修改设备吗？
```

确认后再进入 Phase 2。

---

## Phase 2: Schema 合并

Phase 1 的结果写入 schema：

```bash
python3 <SKILL_DIR>/scripts/merge-schema.py
```

### 什么时候跑

调用方式（Agent 先读取记忆，提取设备列表后传参）：

```bash
# Agent 从记忆提取设备列表
# 然后调用 merge-schema
python3 <SKILL_DIR>/scripts/merge-schema.py \
  --memory-devices '<记忆设备 JSON 列表>'
```

如果不传 `--memory-devices`，则脚本只处理扫描到的设备，不从记忆补充。

| 场景 | 跑不跑 |
|------|--------|
| 完整发现 | **必须跑** |
| 定向发现 | 跑（只更新变化部分） |
| 只读 schema 回答问题 | **不跑** |
| 用户手动改了 schema | 不跑（手动优先） |

### 合并规则

1. 自动发现的设备 → 新增或更新（标记 `discovered: true`）
2. 手动配置的设备 → 保留不动，只更新 status
3. 缓存中存在但本次未发现 → 标记 `status: unreachable`，不删除
4. 敏感信息（密码）→ 不写入 schema
5. 推理后端 → 通用检测（Ollama/vLLM/llama.cpp/LM Studio），不绑特定软件

### ID 迁移：从 IP-based → MAC-based

**背景**：v1.0 开始，设备唯一标识从 IP 改为 MAC 地址。

**迁移过程**：

当 `merge_schema()` 运行时，新扫描的设备使用 MAC 作为 id，而老 schema 中的设备用 IP-based id（如 `192-168-5-100`）。

```
旧 schema:  { id: "192-168-5-100", ip: "192.168.5.100", ... }
新扫描:     { id: "aa:bb:cc:dd:ee:ff", mac: "aa:bb:cc:dd:ee:ff", ips: ["192.168.5.100"], ... }
```

**匹配策略**（三步）：

1. **MAC 直接匹配**：新设备 `id` 在 `seen_ids` 中 → 直接合并
2. **IP 匹配**：新设备 `id` 不在 `seen_ids`，但 `ips[]` 中的 IP 匹配到旧设备 → 迁移旧设备的 id 为 MAC，合并字段
3. **全新设备**：以上都不匹配 → 作为新设备添加

**鸡生蛋问题与预清理**：

```
问题：第一次合并后，新旧两套设备同时存在于 schema。
第二次运行时，ip_to_existing 索引被新设备的 ips 覆盖，
旧 IP-based 设备再也匹配不上，成为「僵尸」条目。

解决方案：合并前做预清理。
**解决方案：合并前做预清理。**
扫描已有设备，找到被 MAC-based 设备替代的旧 IP-based 设备，移除之。
判断条件：同名（name 相同）或 IP 匹配（old.ip in new.ips[]）。

**额外过滤**：同时在预清理阶段移除 `.0`/`.255` 网段地址设备（`supplement_from_memory()` 已有该过滤，但已写入 schema 的遗留设备需要预清理处理）。

**清理代码逻辑**（在 `merge_schema()` 中）：
```python
# 1. 建立 MAC → device 索引
mac_to_dev = {d["mac"]: d for d in existing.values() if d.get("mac")}

# 2. 找到被替代的旧 IP-based 设备 + 网段地址
cleanup_ids = set()
for dev_id, device in existing.items():
    # 过滤 .0/.255 网段地址
    old_ip = device.get("ip") or ""
    if old_ip:
        try:
            last_octet = int(old_ip.split('.')[-1])
            if last_octet == 0 or last_octet == 255:
                cleanup_ids.add(dev_id)
                continue
        except (ValueError, IndexError):
            pass
    # 检查同名或同 IP 的 MAC-based 设备
    if not device.get("mac"):
        if (old_name and any(d.get("name") == old_name for d in mac_to_dev.values())) or \
           (old_ip and any(old_ip in d.get("ips", []) for d in mac_to_dev.values())):
            cleanup_ids.add(dev_id)

# 3. 移除
for cid in cleanup_ids:
    existing.pop(cid, None)
```

### body-schema.json 格式（v1.0）

参见 `body-schema.example.json`（完整示例）。核心字段：

```json
{
  "self": {
    "hostname": "...", "os": "...", "arch": "...",
    "cpu": "...", "memory_gb": 16,
    "ips": ["192.168.1.2"], "mac": "aa:bb:cc:dd:ee:ff"
  },
  "environment": { "timezone": "Asia/Shanghai", "networks": [] },
  "devices": [{
    "id": "aa:bb:cc:dd:ee:ff",
    "mac": "aa:bb:cc:dd:ee:ff",
    "name": "PVE-192.168.5.100",
    "type": "hypervisor",
    "ip": "192.168.5.100",
    "ips": ["192.168.5.100", "10.0.0.1"],
    "primary_ip": "192.168.5.100",
    "capabilities": ["SSH", "PVE"],
    "ports": [22, 8006],
    "safety_level": "read_only",
    "status": "reachable",
    "discovered": true,
    "source": "network_scan",
    "last_seen": "2026-05-02T00:35:38+08:00"
  }],
  "services": [{ "id": "...", "name": "...", "url": "...", "capabilities": [], "safety_level": "read_only" }],
  "discovery_meta": { "last_full_discovery": "...", "schema_version": "1.1" }
}
```

**设备唯一标识（v1.0 核心改进）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 设备唯一标识，使用 MAC 地址（如 `00:11:22:33:44:55`）；无 MAC 时用 IP-based（`192-168-5-100`） |
| `mac` | string|null | MAC 地址（与 id 相同，等下次扫描到 MAC 后接管） |
| `ip` | string | 旧格式向后兼容的单个 IP |
| `ips` | string[] | IP 地址数组（支持多网络：本地 + VPN + ZeroTier） |
| `primary_ip` | string | 主要 IP（用于默认连接） |
| `last_seen` | string (ISO8601) | 最后发现时间 |
| `source` | string | 数据来源：`network_scan` / `memory_supplement` / `passive_learning` / `manual` |

**合并逻辑**：
- 扫描发现新 IP → 查询 MAC → MAC 已存在则追加 IP 到 ips 数组
- MAC 获取失败（ARP 无记录）→ 用 IP-based id，等下次扫描到 MAC 后再迁移
- 无 MAC 设备在后续扫描获得 MAC 后，通过 IP 匹配自动合并

**为什么用 MAC 地址**：
- IP 地址会变（DHCP）
- hostname 可能重复或修改
- MAC 地址是硬件唯一标识，不随网络变化
- 多网卡设备（ZT + 本地）通过 ips 数组管理

---

## Phase 3: 被动学习（从对话和操作中学习设备）

**核心原则**：不要专门跑扫描——在日常对话和操作中，遇到新的网络/硬件/能力就顺手记录。

**两种学习路径**：
1. **对话学习** — 用户提到设备信息（IP、类型、能力）
2. **操作学习** — Agent 使用设备上的软件/服务时，从返回信息中提取硬件能力

### 触发条件

#### 对话学习（用户提及）

以下场景**自动触发**增量更新，不需要用户提醒：

| 用户说 | 发现什么 | 做什么 |
|--------|---------|--------|
| "打开 192.168.5.1 的路由器..." | IP + 类型(router) | `mcp_embodiment_learn_device(text="...")` |
| "连上 PVE 看看" | 已知设备名 PVE | `mcp_embodiment_learn_device(text="...")` |
| "用 Ollama 跑一下" | 推理能力暗示 | `mcp_embodiment_learn_device(text="...")` |

#### 操作学习（使用中发现）

Agent 在**实际使用设备上的软件/服务**时，从返回信息中提取硬件能力：

| 操作 | 返回信息 | 提取什么 | 更新到 schema |
|------|---------|---------|---------------|
| SSH 成功后 `uname -a` | `Linux ... x86_64` | OS、架构、hostname | `os_type`, `arch`, `name` |
| SSH 成功后 `nvidia-smi` | `RTX 5070, 12288 MiB` | GPU 型号、显存 | `capabilities: [cuda]`, `gpu.name`, `gpu.memory_mb` |
| SSH 成功后 `docker ps` | 容器列表 | Docker 宿主机 | `type: docker_host`, `capabilities: [docker]` |
| SSH 成功后 `qm list` | VM 列表 | Hypervisor | `type: hypervisor`, `capabilities: [pve]` |
| 调用 Ollama API `/api/tags` | 模型列表 | 推理后端 | `capabilities: [inference]`, `inference.type: ollama` |
| 调用 Ollama API `/api/ps` | `GPU: NVIDIA RTX 5070` | GPU 型号 | `gpu.name` |
| 调用 ComfyUI `/system_stats` | `GPU: 12288 MB` | 显存大小 | `gpu.memory_mb` |
| 调用 vLLM `/v1/models` | 模型列表 | 推理后端 | `capabilities: [inference]`, `inference.type: vllm` |
| 连 DSM `/webapi/entry.cgi` | 存储信息 | NAS | `type: nas`, `capabilities: [storage]` |
| SSH 失败 | Connection refused | 连不上 | `status: unreachable` |

**操作学习的执行时机**：
- Agent 在调用其他 skill（PVE、Ollama、ComfyUI、SSH 等）**成功后**
- 从返回的 stdout/API response 中提取信息
- **静默调用** `mcp_embodiment_learn_device` 或 `scripts/update-device.py`
- 不打断用户当前任务

### 学习边界

**embodiment 记录什么**（硬件/拓扑/能力）：
- ✅ 设备类型（server/vm/nas/hypervisor）
- ✅ 网络信息（IP、MAC、端口）
- ✅ 硬件能力（GPU、显存、摄像头、存储）
- ✅ 软件能力标签（cuda/inference/docker/pve/ssh）
- ✅ 设备状态（reachable/unreachable/auth_required）

**不记录什么**（交给其他 skill/memory）：
- ❌ Ollama 模型列表 → memory 或 ollama-model-manager
- ❌ ComfyUI 工作流 → memory
- ❌ API endpoint 详情 → memory
- ❌ 软件版本号 → memory
- ❌ 服务内部配置 → 对应 skill
- ❌ 凭据信息 → credential pool（不写入 schema）

### 执行规则

1. **静默更新**：顺手做，不打断用户当前任务。更新完不用特别汇报，除非是重要发现（新设备上线）。
2. **轻量优先**：用 `scripts/update-device.py` 单设备增量更新，不跑完整发现流程。
3. **不重复添加**：MCP 工具自动处理——已存在就更新，不存在才新增。
4. **保守判断**：不确定设备类型就标 `unknown`，不瞎猜。
5. **重要发现汇报**：新设备上线、硬件能力变化时，一句话告诉用户。
6. **操作后提取**：调用其他 skill/API 成功后，从返回信息中提取硬件能力并更新。

### 工具

**MCP 工具**（供 Agent 调用）：

```bash
# 查询设备信息（返回完整 schema 或按条件筛选）
mcp_embodiment_query_device()
mcp_embodiment_query_device(name="Windows")
mcp_embodiment_query_device(capability="cuda")

# 从对话或操作结果中学习设备信息（被动学习核心工具）
mcp_embodiment_learn_device(text="用户消息或操作返回信息")
mcp_embodiment_learn_device(text="SSH 成功连接到 RTX5070", ip="192.168.5.109", capabilities="cuda,inference")
```

**内部脚本**（供 skill 逻辑直接调用）：

```bash
# 更新单个设备信息（操作学习后调用）
python3 scripts/update-device.py --ip 192.168.5.100 --type server --name "主服务器"

# 示例：SSH 到某台 Windows VM 后更新
python3 scripts/update-device.py --ip 192.168.5.109 --type vm --name "Win-RTX5070" --ports "22,11434,8188" --capabilities "cuda,rtx5070,vram_12gb"

# 示例：发现某设备连不上了
python3 scripts/update-device.py --ip 192.168.5.100 --status unreachable

# 示例：Ollama API 调用后发现 GPU 信息
python3 scripts/update-device.py --ip 192.168.5.109 --capabilities "inference" --gpu-name "RTX 5070" --gpu-memory-mb 12288

# 从对话中学习（脚本 fallback）
python3 scripts/learn-device.py --text "用户消息"
```

### 从操作中学习硬件能力

Agent 在使用设备上的软件/服务时，应从返回信息中提取硬件能力：

#### SSH 操作后提取

```bash
# SSH 成功后，静默执行信息采集
ssh <ip> "uname -a && hostname && cat /etc/os-release 2>/dev/null | head -3"

# 提取字段：
# - hostname → device.name
# - OS (Linux/Darwin/Windows) → device.os_type
# - 架构 (x86_64/arm64) → device.arch

# 如果有 nvidia-smi
ssh <ip> "nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null"
# 提取：GPU 型号、显存 → device.gpu.name, device.gpu.memory_mb

# 如果有 docker
ssh <ip> "docker ps -q 2>/dev/null | wc -l"
# 有输出 → device.capabilities.append("docker"), device.type = "docker_host"

# 如果是 PVE
ssh <ip> "qm list 2>/dev/null | wc -l"
# 有输出 → device.capabilities.append("pve"), device.type = "hypervisor"
```

#### API 调用后提取

```bash
# Ollama API
curl -s http://<ip>:11434/api/tags
# 提取：模型列表 → device.inference.models (不写入 schema，只标记能力)
# 标记：device.capabilities.append("inference"), device.inference.type = "ollama"

curl -s http://<ip>:11434/api/ps
# 返回示例：{"models": [...], "gpu": "NVIDIA RTX 5070"}
# 提取：GPU 型号 → device.gpu.name

# ComfyUI API
curl -s http://<ip>:8188/system_stats
# 返回示例：{"devices": [{"name": "cuda:0", "vram_total": 12884901888}]}
# 提取：显存 → device.gpu.memory_mb

# vLLM API
curl -s http://<ip>:8000/v1/models
# 有返回 → device.capabilities.append("inference"), device.inference.type = "vllm"

# DSM/Synology API
curl -s "http://<ip>:5000/webapi/entry.cgi?api=SYNO.Storage.CGI.Storage"
# 有返回 → device.type = "nas", device.capabilities.append("storage")
```

#### 调用示例（Agent 内部逻辑）

```python
# 伪代码：SSH 成功后自动提取信息
def on_ssh_success(ip, stdout):
    # 解析 uname 输出
    hostname = parse_hostname(stdout)
    os_type = parse_os(stdout)
    arch = parse_arch(stdout)
    
    # 更新设备信息
    mcp_embodiment_learn_device(
        text=f"SSH connected to {hostname}",
        ip=ip,
        name=hostname,
        type="server",  # 默认，后续可能被修正为 vm/docker_host
        capabilities=["ssh"]
    )
    
    # 如果发现 GPU
    if "nvidia-smi" in stdout or "RTX" in stdout:
        gpu_name = extract_gpu_name(stdout)
        vram_mb = extract_vram(stdout)
        update_device(ip, capabilities=["cuda"], gpu={"name": gpu_name, "memory_mb": vram_mb})

# 伪代码：Ollama API 调用后提取
def on_ollama_api_success(ip, response):
    # 标记推理能力
    update_device(ip, capabilities=["inference"], inference={"type": "ollama"})
    
    # 如果返回 GPU 信息
    if "gpu" in response:
        update_device(ip, gpu={"name": response["gpu"]})
```

### 从对话中学习设备信息

用户可能在日常对话中提及设备信息，Agent 应自动识别并记录：

| 用户说 | 发现什么 | 调用 |
|--------|---------|------|
| "打开 192.168.5.1 的路由器..." | IP + 类型(router) | `mcp_embodiment_learn_device(text="...")` |
| "拍一张照片" | 暗示摄像头能力 | `mcp_embodiment_learn_device(text="...", ip="<本机IP>", capabilities="camera")` |
| "连上 PVE 看看" | 已知设备名 PVE | `mcp_embodiment_learn_device(text="...")` |
| "用 Ollama 跑一下" | 推理能力 | `mcp_embodiment_learn_device(text="...")` |

**提取规则**：

```
IP 地址：正则匹配 (\d{1,3}\.){3}\d{1,3}

设备类型关键词：
  路由器/router → router
  交换机/switch → switch
  NAS/群晖/威联通 → nas
  服务器/server → server
  PVE/Proxmox → hypervisor
  摄像头/相机/camera → camera
  打印机/printer → printer
  VM/虚拟机 → vm

设备能力关键词：
  拍照/摄像头 → camera
  SSH/ssh → ssh
  HTTP/网页 → http
  Ollama/推理 → inference
  ComfyUI/生图 → image_gen
```

**使用示例**（优先 MCP 工具）：

```bash
# 从对话文本中自动提取（MCP 工具，推荐）
mcp_embodiment_learn_device(text="打开 192.168.5.1 的路由器设置")

# 预览模式（不实际更新）
mcp_embodiment_learn_device(text="连上 PVE 看看", dry_run=true)

# 显式指定信息
mcp_embodiment_learn_device(text="那个服务器", ip="192.168.5.100", type="server", name="主服务器")

# 脚本方式（MCP 不可用时的 fallback）
python3 <SKILL_DIR>/scripts/learn-device.py --text "打开 192.168.5.1 的路由器设置"
```

**Agent 行为指南**：

1. **静默学习**：在对话中识别到设备信息时，自动调用 `mcp_embodiment_learn_device`，不打断用户
2. **置信度判断**：
   - 高：同时有 IP 和设备类型关键词
   - 中：只有 IP 或只有设备类型
   - 低：只有模糊描述
3. **不重复添加**：MCP 工具自动处理——已存在就更新，不存在才新增
4. **标记来源**：被动学习的设备标记 `discovered: false` 和 `source: "passive_learning"`
5. **重要发现汇报**：发现新设备时，一句话告诉用户

### 自动学习机制

Agent 应在对话和操作中**自动识别**设备信息并静默学习，无需用户显式请求。

#### 自动触发条件

以下模式出现时，Agent **应自动调用** `mcp_embodiment_learn_device`：

| 触发类型 | 模式 | 示例 |
|---------|------|------|
| **IP 地址** | `\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}` | "192.168.5.1"、"10.0.0.100" |
| **设备关键词** | 路由器/交换机/NAS/PVE/服务器/虚拟机/VM | "打开 PVE"、"那个 NAS" |
| **能力关键词** | SSH/Ollama/推理/ComfyUI/摄像头/拍照 | "用 Ollama 跑一下"、"拍张照" |
| **操作暗示** | 连接/登录/打开/访问 + 设备 | "连上那台服务器" |
| **操作返回** | SSH/API 调用成功后的返回信息 | nvidia-smi 输出、Ollama /api/ps 返回 |

#### 置信度规则

| 置信度 | 条件 | Agent 行为 |
|--------|------|-----------|
| **high** | IP + 类型关键词 同时出现 | **自动添加**，静默执行，完成后一句话告知 |
| **medium** | IP 或 类型关键词 单独出现 | **可选确认**，询问用户确认设备类型或 IP |
| **low** | 只有模糊描述（"那个机器"） | **不添加**，等待更多信息 |

#### 调用示例

```bash
# 高置信度：IP + 类型 → 自动执行
用户: "帮我看看 192.168.5.100 的服务器状态"
Agent: [静默调用] mcp_embodiment_learn_device(text="192.168.5.100 的服务器")
       → 自动添加 IP=192.168.5.100, type=server
       → 继续执行用户请求

# 中置信度：只有 IP → 询问确认
用户: "连一下 192.168.5.50"
Agent: "好的，192.168.5.50 是什么类型的设备？（服务器/VM/NAS/其他）"

# 中置信度：只有类型 → 询问 IP
用户: "看看那个 NAS"
Agent: "好的，NAS 的 IP 地址是多少？"

# 低置信度：模糊描述 → 不添加
用户: "那个机器怎么了"
Agent: [不调用 mcp_embodiment_learn_device，继续对话]

# 操作学习：SSH 成功后提取
Agent: ssh 192.168.5.109 "uname -a && nvidia-smi"
       → 返回: "Linux ... RTX 5070, 12288 MiB"
       → [静默调用] update_device(ip="192.168.5.109", capabilities=["cuda"], gpu={"name": "RTX 5070", "memory_mb": 12288})

# 操作学习：Ollama API 调用后提取
Agent: curl http://192.168.5.109:11434/api/ps
       → 返回: {"gpu": "NVIDIA RTX 5070"}
       → [静默调用] update_device(ip="192.168.5.109", gpu={"name": "RTX 5070"})
```

#### 静默调用代码片段

Agent 在识别到设备信息后，应在执行用户请求**之前**静默调用：

```python
# 伪代码：Agent 内部逻辑
def on_device_info_detected(text, ip=None, device_type=None):
    confidence = calculate_confidence(ip, device_type)

    if confidence == "high":
        # 静默调用 MCP 工具，不打断用户
        mcp_embodiment_learn_device(text=text)
        # 继续执行用户请求
        return True
    elif confidence == "medium":
        # 可选：询问用户确认
        if ip and not device_type:
            device_type = ask_user("这是什么类型的设备？")
        elif device_type and not ip:
            ip = ask_user("设备的 IP 地址是多少？")

        if ip and device_type:
            mcp_embodiment_learn_device(text=text, ip=ip, type=device_type)
            return True
    return False
```

#### 与被动感知的配合

- **对话学习**：在对话中识别新设备信息并添加
- **操作学习**：在使用设备上的软件/服务时，从返回信息中提取硬件能力

两者互补：
- 对话学习关注**新设备的发现和添加**
- 操作学习关注**已有设备的硬件能力细化**

### 不算被动感知的场景

- 用户明确说「扫描网络」→ 跑完整发现（Phase 1）
- 用户说「看看我有什么」→ 读 schema（Phase 1 快速读取）
- 定期过期检查（>24h）→ 建议刷新，但不自动跑

---

## 发现脚本

`<SKILL_DIR>/scripts/` 下：

| 脚本 | 功能 |
|------|------|
| `discover-self.sh` | 本机信息 |
| `discover-hardware.sh` | 音频/蓝牙/显示器/摄像头/USB/存储 |
| `discover-network.sh` | 网络发现（存活探测 + 端口 + mDNS），输出含 MAC 列 |
| `discover-mdns.sh` | mDNS/Bonjour 服务发现（discover-network.sh 也会调用） |
| `discover-pve.sh` | PVE VM 列表（可选插件） |
| `discover-inference.sh` | GPU/VRAM/推理后端/模型 |
| `merge-schema.py` | 自动合并 → body-schema.json |
| `verify-action.sh` | 操作结果验证 |
| `update-device.py` | 单设备增量更新（被动感知用） |
| `learn-device.py` | 从对话文本中学习设备信息 |

脚本失败 fallback：用基础命令（`uname -a`、`hostname`、`ping`）逐个采集。

---

## MCP Server

Embodiment 可以作为 MCP 服务器运行，让任何 MCP 客户端（Hermes、Claude Desktop 等）直接调用其工具。

### 启动

```bash
# 直接运行（stdio 模式）
~/.hermes/scripts/embodiment-mcp.sh

# 或用 Hermes venv
~/.hermes/hermes-agent/venv/bin/python <SKILL_DIR>/mcp/server.py
```

### 可用工具（v1.0 精简版）

| 工具 | 说明 |
|------|------|
| `query_device` | 查询设备（无参数返回完整schema，有参数按条件筛选） |
| `learn_device` | 从对话文本中自动学习设备信息（被动学习核心） |

**query_device 参数**：`name`（模糊匹配）、`ip`（精确匹配）、`capability`、`type`、`status`

**不暴露为 MCP 的功能**（用脚本实现）：
- 更新设备信息 → `scripts/update-device.py`
- 新手引导 → Skill 加载时自动检测
- 生命周期检查 → 后台定时任务
- 验证操作结果 → 调用方 skill 自己做

### learn_device 工具详解

`learn_device` 是被动感知的核心工具，让 Agent 能从自然语言对话中自动识别和记录设备信息。

#### 参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text` | string | ✅ | 用户对话文本，从中提取设备信息 |
| `context` | string | ❌ | 额外的对话上下文 |
| `ip` | string | ❌ | 显式指定 IP（覆盖自动提取） |
| `type` | string | ❌ | 显式指定设备类型 |
| `name` | string | ❌ | 显式指定设备名称 |
| `capabilities` | string | ❌ | 逗号分隔的能力列表 |
| `dry_run` | boolean | ❌ | 预览模式，不实际更新 schema |

#### 自动触发场景

MCP 客户端（如 Hermes）应在以下场景**自动调用** `learn_device`：

| 触发类型 | 模式 | 示例 |
|---------|------|------|
| **IP 地址** | `\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}` | "192.168.5.1"、"10.0.0.100" |
| **设备关键词** | 路由器/交换机/NAS/PVE/服务器/虚拟机/VM | "打开 PVE"、"那个 NAS" |
| **能力关键词** | SSH/Ollama/推理/ComfyUI/摄像头/拍照 | "用 Ollama 跑一下"、"拍张照" |
| **操作暗示** | 连接/登录/打开/访问 + 设备 | "连上那台服务器" |

#### 置信度规则

| 置信度 | 条件 | Agent 行为 |
|--------|------|------------|
| **high** | IP + 类型关键词 同时出现 | **自动添加**，静默执行，完成后一句话告知 |
| **medium** | IP 或 类型关键词 单独出现 | **可选确认**，询问用户确认设备类型或 IP |
| **low** | 只有模糊描述（"那个机器"） | **不添加**，等待更多信息 |

#### MCP 调用示例

```json
// 高置信度：IP + 类型 → 自动执行
{
  "name": "learn_device",
  "arguments": {
    "text": "帮我看看 192.168.5.100 的服务器状态"
  }
}
// 返回: {"status": "success", "devices_found": 1, "confidence": "high"}

// 显式指定信息
{
  "name": "learn_device",
  "arguments": {
    "text": "连上那个服务器",
    "ip": "192.168.5.100",
    "type": "server",
    "name": "主服务器"
  }
}

// 预览模式
{
  "name": "learn_device",
  "arguments": {
    "text": "打开 192.168.5.1 的路由器设置",
    "dry_run": true
  }
}
```

#### 返回值

```json
{
  "status": "success",
  "learned": {
    "parsed": {
      "ips": ["192.168.5.100"],
      "device_types": ["server"],
      "capabilities": ["ssh"],
      "device_name": "主服务器",
      "confidence": "high"
    },
    "devices": [
      {
        "id": "192-168-5-100",
        "type": "server",
        "name": "主服务器",
        "ip": "192.168.5.100",
        "capabilities": ["ssh"],
        "discovered": false,
        "source": "passive_learning"
      }
    ],
    "actions": ["added"]
  },
  "devices_found": 1,
  "confidence": "high"
}
```

#### 与被动感知的配合

- **被动感知**（Phase 5）：在日常操作中自动更新设备状态
- **learn_device MCP 工具**：在对话中识别新设备信息并添加

两者互补：
- 被动感知关注**已有设备的状态变化**
- learn_device 关注**新设备的发现和添加**

### CLI 测试

```bash
# 列出所有工具
python3 mcp/server.py --list

# 测试工具调用
python3 mcp/server.py --call discover_self
python3 mcp/server.py --call get_schema
```

### 配置 Hermes 使用

在 `~/.hermes/config.yaml` 添加：

```yaml
mcp_servers:
  embodiment:
    command: "~/.hermes/scripts/embodiment-mcp.sh"
    timeout: 120
    connect_timeout: 60
```

重启 Hermes 后，所有 `mcp_embodiment_*` 工具自动可用。

### 架构

```
agent-embodiment/
├── mcp/
│   ├── operations.py    # Contract-first 操作定义
│   └── server.py        # MCP stdio 服务器
├── scripts/             # 现有发现脚本
└── body-schema.json
```

参考 GBrain 的 contract-first 模式：`operations.py` 定义所有操作，`server.py` 自动生成 MCP 工具。CLI 和 MCP 共享同一套操作定义。

---

## 使用场景速查

**「你跑在什么上面？」**
→ Phase 0 (快速读取) → 读 schema `self` 字段

**「你能控制什么？」**
→ Phase 0 (快速读取) → 读 `devices` + `capabilities`

**「看看网络里有什么」**
→ Phase 0 (定向发现) → Phase 1.2 `discover-network.sh` → Phase 2 合并

**「我有什么算力？」**
→ Phase 0 (定向发现) → Phase 1.3 `discover-inference.sh` → 汇报 GPU/VRAM/模型

**「帮我重启 XX」**
→ Phase 0 → 查 `safety_level` → Phase 3 确认 → 执行 → Phase 3 验证

**「刷新一下设备信息」**
→ Phase 0 (完整发现) → Phase 1 全流程 → Phase 1.6 确认 → Phase 2 合并 → Phase 4 持久化

---

## 扩展指南

### 添加新设备

1. `body-schema.json` 的 `devices` 中添加条目
2. 定义 `type`、`capabilities`、`safety_level`、`access`
3. 可选：写 `discover-xxx.sh` 脚本

### 从外部 Skill 注册设备

其他 skill 可往 `body-schema.json` 注册设备，embodiment 成为**统一注册中心**。

---

## 诚实边界

1. 发现能力有限 — ping 只能发现存活主机，端口可能被防火墙阻挡
2. 不替代专业监控 — 这是环境感知，不是 Zabbix
3. Schema 可能过时 — DHCP 下 IP 会变，需定期刷新
4. 安全分级是参考 — 最终判断权在用户

### 常见异常

| 异常 | 处理 |
|------|------|
| SSH 权限不足 (Permission denied) | 标记该设备 `status: auth_required`，跳过，建议用户配置 key |
| 所有设备 unreachable | 检查本机网络连通性，确认是否在目标网段。被动学习的设备可能在不同网络 |
| 脚本无执行权限 | `chmod +x scripts/*.sh` 后重试 |
| JSON 解析失败 | 删除损坏 schema，重新完整发现 |
| 发现脚本超时 | 单设备超时跳过，不阻塞整体流程 |
| 网络扫描结果不一致 | `discover-network.sh` 每次运行可能发现不同设备（ARP/mDNS 时序差异）。merge-schema.py 已处理：旧缓存 + 新扫描结果合并，累积发现不丢设备 |
| 端口扫描全部失败 | 检查：(1) 是否在目标网段 (2) 目标设备是否开机 (3) 防火墙是否阻止。macOS 使用 `nc -G` 超时参数 |
| ARP 表为空 | 当前网段无其他设备，或刚开机 ARP 缓存未建立。等待几分钟或主动访问网络资源 |
| 扫描耗时过长 | 5 网段 × 254 IP ≈ 10-15 分钟，正常。后台运行不阻塞用户 |
| ARP 表过大（500+ IP） | 正常现象，ARP 缓存包含历史通信过的所有设备。`discover-inference.sh` 已内置分批扫描（每 20 IP 暂停 0.5s），不会超时 |
| `remote_endpoints: unbound variable` | `discover-inference.sh` 需在 ARP 扫描前初始化 `remote_endpoints=""` |
| **MAC 地址获取失败**（ARP 表无记录） | 设备不在同一广播域（如 ZeroTier 对端），或刚开机缓存未建立。不影响设备发现，下次扫描到 ARP 记录后自动合并 |
| **新旧设备 ID 格式冲突**（IP-based vs MAC-based） | 自动处理：预清理阶段移除被 MAC-based 替代的旧设备。见「ID 迁移」章节 |
| **`wait -n: command not found`**（macOS bash 3.x） | macOS 自带 bash 3.x 不支持 `wait -n`。已修复：改用 `wait` 每 N 个进程等待一次。见 `discover-network.sh` 并行扫描逻辑 |
| **`declare -A: invalid option`**（macOS bash 3.x） | macOS 自带 bash 3.x 不支持关联数组。已修复：改用 `arp -a | grep` 函数获取 MAC 地址 |

### merge-schema.py 设计要点

- **统一缓存**：`run_script()` 运行脚本后自动将 stdout 存入 `.cache/<script>.stdout`。`read_cached()` 读取缓存。所有脚本共享同一套缓存机制
- **网络发现累积**：`discover_network_devices()` 先读旧缓存，再跑新扫描，两者合并（IP 去重，端口/服务追加）。解决 `discover-network.sh` 每次扫描结果不一致的问题
- **本机跳过**：`get_local_ips()` 用 `ifconfig` 获取本机 IP，自动过滤
- **设备类型猜测**：`guess_device_type(ip, info)` 按端口优先级推断（PVE > NAS > Ollama > LM-Studio > llama.cpp > HTTP > SSH > SMB > DNS > unknown）
- **输出解析**：`parse_network_output(output)` 纯函数，将脚本文本输出转为 `{key: {mac, ips, ports, services}}` dict。支持新格式（5列含 MAC）和旧格式（4列无 MAC）
- **ID 迁移**：`merge_schema()` 中通过三步匹配（MAC ID → IP 匹配 → 全新）完成 MAC-based 迁移，并预清理被替代的旧设备

### merge-schema.py 函数清单

| 函数 | 职责 |
|------|------|
| `run_script(name, timeout)` | 运行脚本 + 缓存 stdout |
| `read_cached(script_name)` | 读缓存，无缓存返回空串 |
| `load_schema()` | 读 body-schema.json，不存在返回空模板 |
| `discover_self()` | 读缓存的本机信息 JSON |
| `test_reachability(ips)` | ping 测试 IP 连通性 |
| `detect_inference_backends()` | 探测 Ollama/vLLM/LM Studio |
| `parse_network_output(output)` | 解析网络扫描文本 → dict（支持新/旧两种格式） |
| `get_local_ips()` | 获取本机所有 IP |
| `get_device_by_ip(schema, ip)` | 根据 IP 查找设备（支持单 IP 和多 IP 设备） |
| `supplement_from_memory(schema, memory_devices)` | 从 Agent 传入的记忆列表补充设备（见下方详细说明） |
| `guess_device_type(ip, info)` | 多源推断设备类型类型、名称、操作系统和硬件能力。返回 `(dtype, name, os_type, capabilities)`。新增字段：`os_type`（操作系统）、`capabilities`（推断的硬件能力，如 `cuda`/`inference`/`vm_host`/`storage`） |
| `probe_device_fingerprint(ip, ports)` | 探测设备指纹（HTTP Server/SSH banner/Ollama info） |
| `get_cache_ttl(dtype)` | 获取设备类型的缓存 TTL |
| `is_device_cache_expired(device)` | 检查设备缓存是否过期 |
| `get_devices_needing_refresh(schema)` | 获取需要刷新的设备（分组） |
| `discover_network_devices()` | 旧缓存 + 新扫描 → 累积合并设备列表（使用 MAC 作为 key） |
| `_merge_device_fields(existing, new)` | 将新设备数据合并到已有设备，保留旧数据不丢（辅助函数） |
| `merge_schema(...)` | 合并 self + 设备 + 推理后端 → schema（含 ID 迁移和预清理） |
| `main()` | 7 步流程编排（Agent 传入记忆设备列表） |

### 从 Memory 补充设备信息

`supplement_from_memory(schema, memory_devices)` 从 Agent 传入的记忆设备列表补充网络扫描可能遗漏的设备。

**工作原理**：
1. **Agent 负责读取记忆**（不写死在脚本里）—— Agent 在调用 merge-schema.py 前，从自己的记忆中提取设备信息
2. Agent 通过 `--memory-devices` 参数将设备列表以 JSON 格式传入脚本
3. 脚本负责过滤重复、过滤无效 IP、补充到 schema
4. 补充的设备标记 `source: "memory_supplement"`, `discovered: false`

**注入方式**：
```bash
# Agent 先读取记忆，提取设备列表
# 然后传参调用
python3 <SKILL_DIR>/scripts/merge-schema.py \
  --memory-devices '[{"ip":"192.168.5.100","type":"hypervisor","name":"PVE","capabilities":["ssh"]}]'
```

**Agent 从哪里读记忆**：
- Agent 可以根据需要灵活选择来源：Hindsight memory、MEMORY.md、当前配置、或任何其他来源
- 脚本不绑定任何特定的记忆存储格式

**优先级**：扫描结果 > Memory 补充（已存在的设备跳过）

---

## v0.3.0 新功能

### 智能缓存策略

不同设备类型使用不同缓存时间：

| 设备类型 | 缓存 TTL |
|---------|---------|
| 物理服务器、NAS、Hypervisor、路由器 | 24h |
| VM、Docker 宿主机、推理服务器 | 4h |
| 手机、笔记本、平板 | 1h |
| 容器 | 30min |

缓存过期后自动标记，下次发现时优先刷新过期设备。

### 网络发现分层健壮性

`discover-network.sh` 采用三层发现架构：

1. **Layer 1: 本地网络**（en0/wlan0/eth0）→ 始终尝试
2. **Layer 2: VPN/ZeroTier**（utun/zt*）→ 可选，失败不影响本地发现
3. **Layer 3: 远程网络** → 通过 SSH 代理发现

一层失败不影响其他层，确保基础发现始终可用。

### 设备类型推断增强

`guess_device_type()` 结合多种信息推断：

1. **mDNS 名称**：MacBook-Pro.local → 笔记本，iPhone.local → 手机
2. **HTTP Server 响应头**：Server: Synology → NAS
3. **SSH banner**：OpenSSH_8.9p1 Ubuntu → Linux 服务器
4. **Ollama API 响应**：/api/tags 返回格式 → 推理服务器
5. **端口组合**：8006 → PVE，11434 → Ollama

### Credential Pool 集成

设备 `access` 字段支持引用 credential pool：

```json
{
  "access": {
    "method": "ssh",
    "credential_ref": "win-vm-ssh"
  }
}
```

凭证定义在 `credentials.json`：

```json
{
  "win-vm-ssh": {
    "user": "administrator",
    "password": "your-password"
  }
}
```

### 操作历史记录

`log-operation.py` 记录所有操作：

```bash
# 记录操作
python3 log-operation.py --action vm-start --target 192.168.5.109 --result success --duration 3500

# 查看历史
python3 log-operation.py --list
python3 log-operation.py --list --target 192.168.5.109

# 统计
python3 log-operation.py --stats --days 7
```

日志格式：
```json
{
  "timestamp": "2026-04-26T14:00:00+08:00",
  "action": "vm-start",
  "target": "192.168.5.109",
  "target_name": "Win-RTX5070",
  "result": "success",
  "duration_ms": 3500
}
```

### 被动感知自动化

`update-device.py` 增强 SSH 成功/失败处理：

```bash
# SSH 成功后自动更新
python3 update-device.py --ssh-success <ip> --hostname <hostname> --uname "<uname -a output>"

# SSH 失败后自动标记
python3 update-device.py --ssh-fail <ip> --reason "Connection refused"

# 解析 SSH 输出自动提取信息
python3 update-device.py --parse-output <ip> --ssh-output "$(ssh <ip> 'uname -a && docker ps')"
```

---

## v0.4.0 新功能

### 设备关系图（device-graph.py）

可视化设备之间的层级关系，支持多种输出格式：

```bash
# 打印 ASCII 关系树
python3 <SKILL_DIR>/scripts/device-graph.py

# 自动推断并更新设备关系
python3 <SKILL_DIR>/scripts/device-graph.py --build

# 输出 JSON 格式（可用于其他工具）
python3 <SKILL_DIR>/scripts/device-graph.py --format json

# 输出 Mermaid 图表代码（可渲染为图片）
python3 <SKILL_DIR>/scripts/device-graph.py --format mermaid -o graph.md
```

**关系推断规则**：
- PVE (hypervisor) → VM：通过 `qm list` 获取 VMID 关系
- SSH 代理发现 → 标记 `parent_id`：如果设备通过 `access.via` 或 `access.proxy` 访问
- Docker host → Container：同一 IP 的容器标记父设备

**输出示例**：
```
设备关系树:
========================================
🖥️ pve-main (192.168.1.100) [hypervisor] 🟢
└── 💻 win-vm (192.168.1.101) [vm] 🟢
└── 📦 docker-host (192.168.1.102) [docker_host] 🟢
    └── 📦 nginx-container (192.168.1.102) [container] 🟢
💾 nas (192.168.1.200) [nas] 🟢
```

### 异常检测（anomaly-detector.py）

自动检测设备状态变化并发出告警：

```bash
# 执行检测
python3 <SKILL_DIR>/scripts/anomaly-detector.py

# 查看历史告警
python3 <SKILL_DIR>/scripts/anomaly-detector.py --history

# 确认告警
python3 <SKILL_DIR>/scripts/anomaly-detector.py --ack <alert_id>
python3 <SKILL_DIR>/scripts/anomaly-detector.py --ack-all

# 配置 webhook 通知
python3 <SKILL_DIR>/scripts/anomaly-detector.py --set-webhook feishu:https://open.feishu.cn/...
```

**检测类型**：
| 类型 | 说明 | 级别 |
|------|------|------|
| `device_offline` | 设备离线（之前 reachable 现在 unreachable） | warning |
| `device_online` | 设备上线（之前 offline 现在 reachable） | info |
| `new_device` | 新设备发现 | info |
| `capability_lost` | 能力丢失（端口关闭、服务停止） | warning |
| `capability_gained` | 新能力获得 | info |
| `port_closed` | 端口关闭 | warning |
| `port_opened` | 端口开放 | info |

**告警冷却**：相同告警在 30 分钟内不重复发送。

### 首次引导优化

**并行发现**：
- 使用 `ThreadPoolExecutor` 并行运行发现脚本
- 互不依赖的脚本同时执行，总时间从 ~120s 降至 ~60s

**实时进度反馈**：
```
=== Schema 自动合并 ===

1/6 读取 schema...
   空 schema（首次运行）

2/6 并行发现（4 个脚本）...
   [1/4] discover-self.sh ✓ 完成 (2.3s)
   [2/4] discover-hardware.sh ✓ 完成 (5.1s)
   [3/4] discover-inference.sh ✓ 完成 (8.2s)
   [4/4] discover-network.sh ✓ 完成 (45.6s)

3/6 测试连通性...
   ...
```

**中断恢复**：
- 进度保存到 `<SKILL_DIR>/.cache/discovery-progress.json`
- 中断后重新运行，跳过已完成的脚本
- 手动清除缓存可重新开始：`rm -rf .cache/`

**单脚本超时**：
- 每个脚本有独立超时时间（默认 30s）
- 超时后跳过，不阻塞整体流程
- 网络发现脚本超时设为 60s

---

## 快速使用指南

### 常用命令速查表

#### MCP 工具调用（推荐）

```bash
# 获取当前设备清单
mcp_embodiment_query_device

# 按条件查询
mcp_embodiment_query_device(name="Windows")
mcp_embodiment_query_device(capability="cuda")
mcp_embodiment_query_device(type="vm", status="reachable")

# 从对话中学习设备信息（被动学习核心）
mcp_embodiment_learn_device(text="打开 192.168.5.1 的路由器设置")
```

#### 脚本调用（首次初始化/完整扫描）

```bash
# 本机信息
bash <SKILL_DIR>/scripts/discover-self.sh

# 网络扫描
bash <SKILL_DIR>/scripts/discover-network.sh

# 推理能力检测
bash <SKILL_DIR>/scripts/discover-inference.sh

# 硬件设备
bash <SKILL_DIR>/scripts/discover-hardware.sh

# 合并到 Schema（Agent 先读取记忆，通过参数传入设备列表）
python3 <SKILL_DIR>/scripts/merge-schema.py \
  --memory-devices '{"ip":"...","type":"...","name":"..."}'

# 查看设备关系图
python3 <SKILL_DIR>/scripts/device-graph.py

# 异常检测
python3 <SKILL_DIR>/scripts/anomaly-detector.py
```

### 典型使用场景

| 场景 | 方式 |
|------|------|
| 首次初始化 | 脚本：`merge-schema.py`（Setup Wizard） |
| 查看我的环境 | MCP：`mcp_embodiment_query_device` |
| 查询特定设备 | MCP：`mcp_embodiment_query_device(name="Windows")` |
| 扫描网络 | 脚本：`discover-network.sh` |
| 检查 GPU | 脚本：`discover-inference.sh` |
| 查看设备关系 | 脚本：`device-graph.py` |
| 检查异常 | 脚本：`anomaly-detector.py` |
| 更新设备状态 | 脚本：`update-device.py`（内部脚本，非 MCP） |
| 从对话学习 | MCP：`mcp_embodiment_learn_device` |

### 性能调优

```bash
# 快速网络扫描（只扫描 ARP 表，不扫全子网）
bash <SKILL_DIR>/scripts/discover-network.sh --quick

# 调整超时时间（单位：秒）
export DISCOVERY_TIMEOUT=60
python3 <SKILL_DIR>/scripts/merge-schema.py

# 并行发现（默认启用，可调整并发数）
export DISCOVERY_MAX_WORKERS=8
python3 <SKILL_DIR>/scripts/merge-schema.py

# 清除缓存重新发现
rm -rf <SKILL_DIR>/.cache/
mcp_embodiment_merge_schema
```

### 故障排除

| 问题 | 解决方案 |
|------|---------|
| 网络发现失败 | 检查本机网络连接，尝试 `--quick` 模式 |
| Schema 损坏 | 删除 `body-schema.json` 后重新运行 `merge_schema` |
| 脚本无权限 | `chmod +x <SKILL_DIR>/scripts/*.sh` |
| 发现结果不完整 | 清除缓存后重新扫描：`rm -rf .cache/ && mcp_embodiment_merge_schema` |
| 设备显示 unreachable | 检查目标设备是否开机、网络是否可达、防火墙设置 |
| MCP 工具不可用 | 检查 `~/.hermes/config.yaml` 中 embodiment MCP server 配置 |
| 端口扫描全部失败 | **常见原因**：(1) 当前不在目标网段 (2) 目标设备未开放常用端口 (3) 防火墙阻止扫描。**建议**：使用被动学习添加设备信息，当回到目标网络时会自动检测状态 |
| ARP 表为空 | 当前网段无其他设备，或刚开机 ARP 缓存未建立。等待几分钟或主动访问网络资源 |
| 扫描到 0 台设备 | 当前网段设备未开放常用端口（22, 80, 443, 5000, 8006, 11434 等）。这是正常的，说明端口扫描工作正常，只是目标网段不同 |
| **设备重复**（新旧格式冲突） | 自动修复：重新运行 `merge-schema.py`，预清理阶段会移除被替代的旧设备。如果重复持续存在，清除 cache 后重试 |

```
<SKILL_DIR>/
├── body-schema.json          # 主 Schema 文件
├── .cache/                   # 发现脚本缓存
│   ├── discover-self.stdout
│   ├── discover-network.stdout
│   └── discovery-progress.json
└── scripts/                  # 发现脚本
```

---

## 参考资料

- `references/mcp-vs-skill-vs-cli.md` — MCP vs Skill vs CLI 的触发可靠性分析，何时用 MCP、何时用 CLI
- `references/release-checklist.md` — v1.0 上线检查清单，核心功能验证步骤
- `references/hardware-scanning-impl.md` — 硬件能力扫描实现细节（GPU/音频/存储解析、超时修复）
- `references/v1.0-launch-testing.md` — v1.0 上线测试记录（性能基准、关键修复、用户偏好）
- **v1.0 产品方案** — `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/ObsidianVault/1-Projects/Skills/agent-embodiment-v1.md`

---

## 后续迭代（Roadmap）

### 🔮 远程设备硬件能力探测

**目标**：检查网段内其他设备的硬件能力（GPU、摄像头、存储等），如果设备允许控制和获取。

**实现思路**：

1. **SSH 远程探测**（针对有 SSH 访问权限的设备）
   - 对 `capabilities: [ssh]` 且 `status: reachable` 的设备
   - 执行远程命令获取硬件信息：
     ```bash
     ssh <ip> "system_profiler SPDisplaysDataType SPHardwareDataType"  # macOS
     ssh <ip> "lspci | grep -i vga && nvidia-smi"  # Linux with NVIDIA
     ssh <ip> "cat /proc/cpuinfo && free -h && df -h"  # Linux 通用
     ```
   - 结果写入对应设备的 `hardware` 字段

2. **API 探测**（针对有 HTTP API 的设备）
   - DSM/Synology NAS: `GET /webapi/entry.cgi?api=SYNO.Storage.CGI.Storage`
   - vLLM/Ollama: 已有模型信息，可扩展 GPU 利用率查询
   - PVE: `GET /api2/json/nodes/{node}/status` 获取 CPU/内存/存储

3. **安全考虑**
   - 仅探测 `access` 字段已配置凭据的设备
   - 敏感信息（密码）不写入 schema
   - 用户可配置「允许远程探测」白名单

4. **触发时机**
   - 用户明确请求：「检查 Windows VM 的 GPU」
   - 定期刷新（每日/每周 cron）
   - 设备首次发现时深入探测

**优先级**：P2（v1.1 迭代）

---

## 版本管理原则

**语义化版本**：`MAJOR.MINOR.PATCH`

| 变更类型 | 版本号变化 | 示例 |
|---------|-----------|------|
| 核心功能新增/架构重构 | MAJOR +1 | v1.0 → v2.0（新增 MCP 工具） |
| 功能增强/性能优化 | MINOR +1 | v1.0 → v1.1（MAC ID 迁移） |
| Bug 修复/文档更新 | PATCH +1 | v1.0 → v1.0.1（修复 ARP 扫描超时） |

**避免版本号虚高**：小改动不应导致 MINOR/MAJOR 跳跃。例如：
- ❌ v1.0 → v1.2（只改了 ARP 扫描策略）
- ✅ v1.0 → v1.0.1（修复 ARP 扫描超时）

---

**维护者**: 劲阳
**最后更新**: 2026-05-02
**版本**: 1.0.0 (核心功能: MCP 工具, 网络扫描, 硬件能力查询, 被动学习)
