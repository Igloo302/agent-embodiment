# Agent Embodiment

> 让 AI Agent 拥有「身体感」——知道自己是谁、站在哪里、能控制什么。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AI Agent 能对话、能写代码、能搜索，但它**不知道自己跑在什么机器上、局域网里有什么设备、能不能控制那台服务器**。

Agent Embodiment 解决这个问题。它为 AI Agent 提供**本体感知**（proprioception）能力——自动发现运行环境、扫描网络设备、维护一份「身体 Schema」，并安全地操作可控设备。

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
- **安全操作** — 4 级安全分级（🟢只读→🔴高风险），中高风险操作必须确认
- **验证闭环** — 操作后自动验证结果，失败有回退方案
- **通用** — Mac、Linux、Docker、NAS、HomeLab，不绑定任何平台

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

首次使用生成初始 Schema：

```bash
python3 ~/agent-embodiment/scripts/merge-schema.py
# 或
python3 ~/.hermes/skills/agent-embodiment/scripts/merge-schema.py
```

## 使用

**首次使用** — Agent 会自动引导你完成初始化：

```
Agent：👋 你好！我是 Agent Embodiment —— 你的「身体感」模块。
      我能自动发现你的运行环境和网络设备。
      整个初始化大概 30 秒，我带你走一遍？
你：好
Agent：📡 我的「身体」：MacBook Pro, macOS 26.3, Apple M1, 16GB
      接下来要不要扫描一下网络？
你：扫
Agent：📡 发现 3 台设备：PVE、Windows VM、路由器
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

| 脚本 | 做什么 |
|------|--------|
| `discover-self.sh` | 本机信息（hostname/OS/CPU/内存/IP） |
| `discover-network.sh` | 网络扫描（存活探测 + 27 种端口 + mDNS） |
| `discover-inference.sh` | 推理能力（GPU/VRAM/后端/模型） |
| `discover-hardware.sh` | 外设（音频/蓝牙/显示器/USB/存储） |
| `discover-pve.sh` | PVE 虚拟机列表 |
| `merge-schema.py` | 合并结果 → body-schema.json |
| `verify-action.sh` | 操作验证（VM/SSH/HTTP/Ollama/磁盘） |

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

## 平台适配

| Agent 平台 | 安装方式 | 持久化方式 |
|-----------|---------|-----------|
| Hermes Agent | `hermes skills install` | memory 工具自动写入 |
| Claude Code | clone + 系统 prompt | CLAUDE.md 或项目文件 |
| OpenClaw | clone 到 skills 目录 | 内置记忆机制 |
| 其他 | 将 SKILL.md 加入上下文 | 写入本地文件或 .md |

SKILL.md 的 Phase 0-3（发现、Schema、安全操作）对所有平台通用。Phase 4（持久化）根据各平台能力适配。

## 依赖

- Bash + Python 3.6+
- `curl` · `ping` · `jq`（通常已预装）

## License

MIT
