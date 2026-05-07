# Agent Embodiment

> 让 AI Agent 拥有「身体感」——知道自己是谁、站在哪里、能控制什么。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AI Agent 能对话、能写代码、能搜索，但它**不知道自己跑在什么机器上、局域网里有什么设备、能不能控制那台服务器**。

Agent Embodiment 解决这个问题。它为 AI Agent 提供**本体感知**（proprioception）能力——自动发现运行环境、扫描网络设备、维护一份「身体 Schema」。

**适用于任何能执行 shell 命令的 Agent**：Hermes Agent、Claude Code、OpenClaw、Cursor、Codex CLI 等。

## 效果

**没有 Embodiment：**
```
你：你跑在什么上面？
Agent：我不确定我的运行环境，让我查一下...
      （执行 15 条命令，耗时 99 秒，遗漏网络设备和服务）
```

**有 Embodiment：**
```
你：你跑在什么上面？
Agent：跑在 MacBook Pro 上，macOS 26.3，Apple M1，16GB 内存。
      可控设备：Proxmox VE（管理 4 台 VM）、Windows VM（RTX 5070，跑 Ollama）。
      （3 次 API 调用，35 秒，信息完整）
```

## 特性

- **自动发现** — 本机硬件、网络拓扑、推理能力（GPU/VRAM/模型）、mDNS 服务
- **Schema 驱动** — 所有设备信息存在 `body-schema.json`，Agent 自行决定怎么做
- **MCP 工具** — 提供 `query_device` 和 `learn_device` 两个工具，支持自然语言查询和被动学习
- **被动学习** — 对话中提到设备自动记录；操作设备时自动提取硬件能力（SSH/Ollama/ComfyUI 等）
- **安全操作** — 4 级安全分级（🟢只读→🔴高风险），中高风险操作必须确认
- **跨平台** — macOS 完整测试，Linux/Windows 可运行（部分脚本需适配）
- **路径无关** — 动态获取 skill 目录，可安装在任何位置

## 安装

### Hermes Agent

```bash
hermes skills install Igloo302/agent-embodiment
```

### Claude Code / 其他 Agent

```bash
git clone https://github.com/Igloo302/agent-embodiment.git ~/agent-embodiment
```

将 `SKILL.md` 的内容加入你的 Agent 系统 prompt，或放在 Agent 能读取的 skill 目录中。

### 初始化

首次使用生成初始 Schema（约 10-15 分钟）：

```bash
python3 <SKILL_DIR>/scripts/merge-schema.py
```

## 使用

**首次使用** — Agent 会自动引导你完成初始化：

```
Agent：👋 检测到这是首次使用 Agent Embodiment。
      我可以帮你自动发现：
        🔍 本机信息（系统、CPU、内存、IP）
        🌐 网络设备（扫描局域网内的服务器、NAS、VM 等）
        🎮 推理能力（GPU、Ollama、模型）
        📷 硬件设备（摄像头、音频、蓝牙等）
      
      要现在开始自动扫描吗？（约 10-15 分钟）
你：好
Agent：📡 扫描完成！发现 41 台设备，36 台可达。
      ✅ 初始化完成！
```

**日常使用** — 直接说自然语言：

| 你说 | Agent 做什么 |
|------|-------------|
| "你跑在什么上面？" | 读 Schema，汇报本机环境 |
| "你能控制什么？" | 列出设备清单和能力 |
| "看看网络里有什么" | 扫描局域网，发现设备和服务 |
| "我有什么算力？" | 检测 GPU、VRAM、推理后端和模型 |
| "帮我重启 XX" | 安全确认 → 执行 → 验证 |

**MCP 工具**：

```python
# 查询设备
query_device()                    # 返回所有设备
query_device(capability="inference")  # 查推理服务器
query_device(name="PVE")          # 模糊匹配名称

# 被动学习（对话中自动识别）
learn_device(text="我的路由器在 192.168.1.1，是 MikroTik")

# 被动学习（操作后自动提取）
# Agent 在 SSH/Ollama/ComfyUI 操作后会自动提取硬件能力
# 例如：SSH 后发现 GPU 型号、Ollama API 返回显存信息
```

## 工作原理

```
发现模式判断
  ├─ 快速读取 → 直接读 Schema（秒回）
  ├─ 定向发现 → 只跑相关脚本
  └─ 完整发现 → 全部脚本 → Schema 合并

操作流程
  查 safety_level → 确认模板 → 执行 → verify-action.sh 验证
```

## 发现脚本

| 脚本 | 做什么 | 耗时 |
|------|--------|------|
| `discover-self.sh` | 本机信息（hostname/OS/CPU/内存/IP） | ~1秒 |
| `discover-network.sh` | 网络扫描（ARP表 + 27 种端口） | ~4分钟 |
| `discover-inference.sh` | 推理能力（GPU/VRAM/后端/模型） | ~9分钟 |
| `discover-hardware.sh` | 外设（音频/蓝牙/显示器/USB/存储） | ~1分钟 |
| `merge-schema.py` | 合并结果 → body-schema.json | - |
| `log-operation.py` | 操作历史记录和查询 | - |

## 扩展

编辑 `body-schema.json` 添加设备：

```json
{
  "id": "nas-01",
  "type": "nas",
  "name": "Synology DS920+",
  "ip": "10.0.0.50",
  "access": { "method": "http", "url": "http://10.0.0.50:5000" },
  "capabilities": ["file-storage", "docker"],
  "safety_level": "medium"
}
```

支持的设备类型：`hypervisor` · `vm` · `docker_host` · `inference_server` · `nas` · `smart_home`

## 平台兼容性

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

## Agent 平台适配

| Agent 平台 | 安装方式 | 持久化方式 |
|-----------|---------|-----------|
| Hermes Agent | `hermes skills install` | memory 工具自动写入 |
| Claude Code | clone + 系统 prompt | CLAUDE.md 或项目文件 |
| OpenClaw | clone 到 skills 目录 | 内置记忆机制 |
| 其他 | 将 SKILL.md 加入上下文 | 写入本地文件或 .md |

## 依赖

- Bash + Python 3.6+
- `curl` · `ping` · `nc` · `jq`（通常已预装）

## License

MIT
