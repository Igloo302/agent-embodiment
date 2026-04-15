---
name: agent-embodiment
description: |
  让 Agent 理解自己的「身体」和所处的物理世界——我是谁、我在哪、我能控制什么、我的边界。
  适用于任何能执行 shell 命令的 Agent（Hermes Agent、Claude Code、OpenClaw、Cursor、Codex CLI 等）。
  自动发现运行环境、扫描网络设备、维护持久化的本体 Schema、安全分级执行操作。
  触发词：我的环境、我在哪跑、我的设备、我有什么、自我感知、embodiment、body schema、设备发现、扫描网络、我能控制什么、系统状态、homelab、PVE、虚拟机、VM状态、开关机、启动/关闭VM、查看虚拟机状态、SSH连接、Ollama、本地模型、GPU状态、VRAM、推理能力、模型部署、算力。
  也适用于：用户问「你跑在什么上面」「你能控制哪些设备」「看看我的网络环境」。
  English triggers: what am I running on, my devices, scan network, what can I control, my environment, system status.
---

# Agent Embodiment · 身体感

> 我知道自己是谁、站在哪里、能举起什么。

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

## Phase 0: 首次运行引导

**触发条件**：`body-schema.json` 不存在 = 用户第一次使用。

### 流程（两步完成）

**Step 1: 介绍 + 等待确认**

```
👋 你好！我是 Agent Embodiment —— 你的「身体感」模块。

我能做什么：
  🔍 自动发现你的运行环境和网络设备
  📋 维护一份「身体 Schema」—— 记录所有可控设备
  🔒 安全地帮你操作设备（有确认 + 验证）

说「开始」我就自动完成初始化（约 30 秒）。
```

等用户回复「好」「继续」「开始」再进入 Step 2。

**Step 2: 一键初始化**

用户确认后，**按顺序自动执行全部步骤**，中间不需要用户干预：

```bash
# 1. 本机发现
bash ~/.hermes/skills/agent-embodiment/scripts/discover-self.sh

# 2. 网络扫描
bash ~/.hermes/skills/agent-embodiment/scripts/discover-network.sh

# 3. 生成 Schema（会自动调用上面两个脚本 + 合并结果）
python3 ~/.hermes/skills/agent-embodiment/scripts/merge-schema.py
```

完成后汇报：

```
✅ 初始化完成！

📡 我的「身体」：
  - 主机：{hostname} ({os} {arch})
  - 网络设备：{N} 台
  - 推理能力：{摘要}

我的「身体档案」已保存：~/.hermes/skills/agent-embodiment/body-schema.json

以后你可以直接问我：
  - 「你跑在什么上面？」→ 我读档案回答
  - 「扫描一下网络」→ 我重新发现
  - 「帮我重启 XX」→ 我安全操作 + 验证

随时叫我就好 🤖
```

### 跳过引导

用户已熟悉 skill 或直接发了具体指令（如「看看我的环境」），**跳过引导**，直接执行对应 Phase。

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
bash ~/.hermes/skills/agent-embodiment/scripts/discover-self.sh
```

采集：hostname、OS、架构、CPU、内存、IP、Hermes 版本、Python/Docker/Node 状态。

**失败 fallback**：
```bash
echo "hostname:$(hostname) os:$(uname -s) arch:$(uname -m) ip:$(ipconfig getifaddr en0 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')"
```

### 1.2 网络发现

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-network.sh
```

自动执行：存活探测（schema 已知 IP + ARP 补充）→ 端口扫描（27 种端口）→ mDNS/Bonjour。

**失败 fallback**：
```bash
net=$(ipconfig getifaddr en0 2>/dev/null | cut -d. -f1-3)
for i in $(seq 1 20); do ping -c 1 -t 1 ${net}.$i 2>/dev/null && echo "${net}.$i alive"; done
```

### 1.3 推理能力

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-inference.sh
```

探测 GPU（CUDA/Metal/ROCm）、VRAM、推理后端（Ollama/vLLM/llama.cpp/LM Studio）、模型清单、容量评估。**不绑定特定后端**。

### 1.4 本机硬件

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-hardware.sh
```

音频设备、蓝牙、显示器、摄像头、USB、打印机、挂载存储。

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
| `hypervisor` | `~/.hermes/skills/agent-embodiment/scripts/discover-pve.sh <ip>` |
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
python3 ~/.hermes/skills/agent-embodiment/scripts/merge-schema.py
```

### 什么时候跑

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

### body-schema.json 格式

参见 `body-schema.example.json`（完整示例）。核心字段：

```json
{
  "self": { "hostname", "os", "arch", "cpu", "memory_gb", "ip", ... },
  "environment": { "timezone", "networks" },
  "devices": [{
    "id", "type", "name", "ip", "access", "capabilities", "safety_level", "status"
  }],
  "services": [{ "id", "name", "url", "capabilities", "safety_level" }],
  "discovery_meta": { "last_full_discovery", "schema_version" }
}
```

---

## Phase 3: 安全操作

### 安全分级

| 级别 | 定义 | 行为 |
|------|------|------|
| 🟢 只读 | 不改变任何状态 | 直接执行 |
| 🟡 低风险 | 可逆，影响可控 | 执行后报告 |
| 🟠 中风险 | 部分可逆，可能影响服务 | 先确认 |
| 🔴 高风险 | 不可逆或影响全局 | 必须确认 + 说明后果 |

不确定时按高一级处理。

### 确认模板

**中风险：**
```
⚠️ 准备执行：{操作描述}
设备：{设备名} ({ip})
影响：{具体影响}
可逆性：{是/否，如何回滚}
确认执行？[是/否]
```

**高风险：**
```
🔴 危险操作确认：{操作描述}
设备：{设备名} ({ip})
后果：{不可逆影响}
回滚：{能否回滚，怎么做}
请回复「确认执行」继续，或说「取消」中止。
```

### 验证闭环

操作完成后必须验证：

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/verify-action.sh <action> <target> [expected]
```

返回 JSON：`{"status": "pass"|"fail", "detail": "..."}`

| 动作 | 参数 | 用途 |
|------|------|------|
| `vm-running` | `<pve-ip> <vmid>` | VM 是否运行 |
| `ssh-reachable` | `<ip>` | SSH 端口开放 |
| `service-up` | `<url>` | HTTP 服务响应 |
| `ollama-up` / `ollama-model` | `<url> [model]` | 推理服务/模型状态 |
| `process-running` | `<name>` | 进程状态 |
| `disk-space` | `<mount> <max%>` | 磁盘使用率 |
| `network-check` | `<ip> <ports>` | 多端口批量检查 |

**验证失败处理：**
- 等待 5 秒后重试一次（启动有延迟）
- 仍失败 → 汇报失败详情，建议可能原因
- **不自动重试操作** — 避免循环

---

## Phase 4: 持久化

发现完成后，用 memory 工具写入持久记忆：

```
memory(action="add", target="memory", content="**Agent 本体**: 跑在 <hostname> 上，Hermes v2026.x.x
**可控设备**: <设备列表摘要>
**已知限制**: <踩过的坑>
**最后发现**: <日期>")
```

更新 discovery_meta 时间戳：

```bash
python3 -c "
import json, datetime, os
p = os.path.expanduser('~/.hermes/skills/agent-embodiment/body-schema.json')
s = json.load(open(p))
s['discovery_meta']['last_full_discovery'] = datetime.datetime.now().isoformat()
json.dump(s, open(p, 'w'), indent=2)
"
```

### 写什么 vs 不写什么

| 写入 memory | 不写入 |
|-------------|--------|
| 设备类型和 IP | 密码/密钥 |
| 能力摘要 | 完整 model list（太长） |
| 踩过的坑 | 临时状态（如当前 CPU 占用） |

---

## 发现脚本

`~/.hermes/skills/agent-embodiment/scripts/` 下：

| 脚本 | 功能 |
|------|------|
| `discover-self.sh` | 本机信息 |
| `discover-hardware.sh` | 音频/蓝牙/显示器/摄像头/USB/存储 |
| `discover-network.sh` | 网络发现（存活探测 + 端口 + mDNS） |
| `discover-mdns.sh` | mDNS/Bonjour 服务发现（discover-network.sh 也会调用） |
| `discover-pve.sh` | PVE VM 列表（可选插件） |
| `discover-inference.sh` | GPU/VRAM/推理后端/模型 |
| `merge-schema.py` | 自动合并 → body-schema.json |
| `verify-action.sh` | 操作结果验证 |

脚本失败 fallback：用基础命令（`uname -a`、`hostname`、`ping`）逐个采集。

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
| 所有设备 unreachable | 检查本机网络连通性，建议刷新 schema，不删除旧数据 |
| 脚本无执行权限 | `chmod +x scripts/*.sh` 后重试 |
| JSON 解析失败 | 删除损坏 schema，重新完整发现 |
| 发现脚本超时 | 单设备超时跳过，不阻塞整体流程 |
| 网络扫描结果不一致 | `discover-network.sh` 每次运行可能发现不同设备（ARP/mDNS 时序差异）。merge-schema.py 已处理：旧缓存 + 新扫描结果合并，累积发现不丢设备 |

### merge-schema.py 设计要点

- **统一缓存**：`run_script()` 运行脚本后自动将 stdout 存入 `.cache/<script>.stdout`。`read_cached()` 读取缓存。所有脚本共享同一套缓存机制
- **网络发现累积**：`discover_network_devices()` 先读旧缓存，再跑新扫描，两者合并（IP 去重，端口/服务追加）。解决 `discover-network.sh` 每次扫描结果不一致的问题
- **本机跳过**：`get_local_ips()` 用 `ifconfig` 获取本机 IP，自动过滤
- **设备类型猜测**：`guess_device_type(ip, info)` 按端口优先级推断（PVE > NAS > Ollama > LM-Studio > llama.cpp > HTTP > SSH > SMB > DNS > unknown）
- **输出解析**：`parse_network_output(output)` 纯函数，将脚本文本输出转为 `{ip: {ports, services}}` dict

### merge-schema.py 函数清单

| 函数 | 职责 |
|------|------|
| `run_script(name, timeout)` | 运行脚本 + 缓存 stdout |
| `read_cached(script_name)` | 读缓存，无缓存返回空串 |
| `load_schema()` | 读 body-schema.json，不存在返回空模板 |
| `discover_self()` | 读缓存的本机信息 JSON |
| `test_reachability(ips)` | ping 测试 IP 连通性 |
| `detect_inference_backends()` | 探测 Ollama/vLLM/LM Studio |
| `parse_network_output(output)` | 解析网络扫描文本 → dict |
| `get_local_ips()` | 获取本机所有 IP |
| `guess_device_type(ip, info)` | 端口 → 设备类型推断 |
| `discover_network_devices()` | 旧缓存 + 新扫描 → 累积合并设备列表 |
| `merge_schema(...)` | 合并 self + 设备 + 推理后端 → schema |
| `main()` | 6 步流程编排 |

---

**维护者**: 劲阳
**最后更新**: 2026-04-15
**版本**: 3.6 (缓存机制重构 + 设备累积发现)
