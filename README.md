# Agent Embodiment · 身体感

> 我知道自己是谁、站在哪里、能举起什么。

让 AI Agent 理解自己的「身体」和所处的物理世界——我是谁、我在哪、我能控制什么、我的边界。

## 这是什么

Agent Embodiment 是一个 [Hermes Agent](https://github.com/anthropics/hermes-agent) Skill，为 AI Agent 提供**本体感知**（proprioception）能力。

就像人闭上眼睛也知道自己的手在哪、能举多重，Agent 也需要类似的基础能力才能从「无状态对话」进化为「有身体的行动者」。

**核心差异**：
- 🌐 **通用** — 不绑定 HomeLab/PVE，适用于 Mac、Linux、Docker、NAS、嵌入式设备
- 📋 **Schema 驱动** — 设备能力写在 `body-schema.json` 里，Agent 自行决定怎么做
- 🔒 **安全内置** — 4 级安全分级，不是事后补丁，是操作框架的第一公民
- 🔄 **完整闭环** — 发现 → 探测 → 确认 → 操作 → 验证 → 持久化

## 功能

| 功能 | 说明 |
|------|------|
| 自我发现 | 采集本机系统、网络拓扑、推理能力、外设硬件 |
| 设备感知 | 维护 body-schema.json，记录所有可控设备 |
| 安全操作 | 4 级安全分级 + 确认模板 + 验证闭环 |
| 持久化 | 发现结果写入 agent memory，跨 session 保持 |
| 三种模式 | 快速读取 / 定向发现 / 完发，精确匹配用户意图 |

## 安装

```bash
# 安装到 Hermes Agent skills 目录
cd ~/.hermes/skills/
git clone https://github.com/<your-username>/agent-embodiment.git

# 首次激活 — 自动生成初始 schema
python3 ~/.hermes/skills/agent-embodiment/scripts/merge-schema.py
```

## 快速开始

### 查看环境

直接问 Agent：

> "你跑在什么上面？"
> "你能控制什么？"
> "看看网络里有什么"

Agent 会自动读取 `body-schema.json` 或运行发现脚本。

### 操作设备

> "帮我重启 PVE 上的 VM 102"

Agent 会查 safety_level → 触发确认模板 → 执行 → 验证闭环。

### 刷新环境

> "刷新一下设备信息"

Agent 跑完整发现流程（Phase 1 全部脚本）→ Schema 合并 → 持久化。

## 工作流程

```
Phase 0: 前置条件
  └─ 读 schema → 判断模式（快速读取 / 定向发现 / 完整发现）

Phase 1: 发现与探测
  ├─ 1.1 本机信息    (discover-self.sh)
  ├─ 1.2 网络发现    (discover-network.sh)  ─┐
  ├─ 1.3 推理能力    (discover-inference.sh) ├─ 可并行
  ├─ 1.4 本机硬件    (discover-hardware.sh)  ─┘
  ├─ 1.5 设备深入探测 (按 type 决策树)
  └─ 1.6 发现确认    (向用户汇报)

Phase 2: Schema 合并
  └─ merge-schema.py → 更新 body-schema.json

Phase 3: 安全操作
  ├─ 安全分级（🟢只读 / 🟡低风险 / 🟠中风险 / 🔴高风险）
  ├─ 确认模板（中/高风险操作）
  └─ 验证闭环（verify-action.sh）

Phase 4: 持久化
  └─ memory 工具 + discovery_meta 更新
```

## 发现脚本

| 脚本 | 功能 |
|------|------|
| `discover-self.sh` | hostname、OS、架构、CPU、内存、IP、Hermes 版本 |
| `discover-hardware.sh` | 音频、蓝牙、显示器、摄像头、USB、存储 |
| `discover-network.sh` | 存活探测 + 27 种端口扫描 + mDNS/Bonjour |
| `discover-mdns.sh` | mDNS/Bonjour 服务发现 |
| `discover-pve.sh` | PVE VM 列表（可选） |
| `discover-inference.sh` | GPU/VRAM/推理后端/模型/容量评估 |
| `merge-schema.py` | 自动合并 → body-schema.json |
| `verify-action.sh` | 操作结果验证（VM/SSH/HTTP/Ollama/磁盘等） |

## body-schema.json 结构

```json
{
  "self": {
    "hostname": "my-server",
    "os": "Darwin",
    "arch": "arm64",
    "cpu": "Apple M1",
    "memory_gb": 16,
    "ip": ["10.0.0.1"]
  },
  "environment": {
    "timezone": "Asia/Shanghai",
    "networks": ["10.0.0.0/24"]
  },
  "devices": [{
    "id": "pve-01",
    "type": "hypervisor",
    "name": "Proxmox VE",
    "ip": "10.0.0.100",
    "access": {
      "method": "ssh",
      "ssh": "ssh root@10.0.0.100"
    },
    "capabilities": ["vm-management", "storage"],
    "safety_level": "high",
    "status": "reachable"
  }],
  "services": [{
    "id": "ollama",
    "name": "Ollama",
    "url": "http://10.0.0.109:11434",
    "capabilities": ["inference"],
    "safety_level": "low"
  }],
  "discovery_meta": {
    "last_full_discovery": "2026-04-15T16:00:00",
    "schema_version": "1.0"
  }
}
```

首次运行 `merge-schema.py` 会自动生成 schema，无需手动创建。

## 安全框架

| 级别 | 定义 | 行为 |
|------|------|------|
| 🟢 只读 | 不改变任何状态 | 直接执行 |
| 🟡 低风险 | 可逆，影响可控 | 执行后报告 |
| 🟠 中风险 | 部分可逆，可能影响服务 | 先确认 |
| 🔴 高风险 | 不可逆或影响全局 | 必须确认 + 说明后果 |

## 扩展

### 添加新设备

编辑 `body-schema.json`，在 `devices` 中添加条目：

```json
{
  "id": "nas-01",
  "type": "nas",
  "name": "Synology DS920+",
  "ip": "10.0.0.50",
  "access": {
    "method": "http",
    "url": "http://10.0.0.50:5000"
  },
  "capabilities": ["file-storage", "docker"],
  "safety_level": "medium"
}
```

### 支持的设备类型

| type | 探测方式 |
|------|---------|
| `hypervisor` | SSH `qm list` / PVE API |
| `vm` | SSH / HTTP API |
| `docker_host` | `docker ps` / Docker API |
| `inference_server` | HTTP API (`/api/tags`, `/v1/models`) |
| `nas` | DSM API / SMB |
| `smart_home` | 对应 skill 探测 |

### 从外部 Skill 注册

其他 skill 可往 `body-schema.json` 注册设备，embodiment 成为**统一注册中心**。

## 局限性

- 发现能力有限 — ping 只能发现存活主机，端口可能被防火墙阻挡
- 不替代专业监控 — 这是环境感知，不是 Zabbix
- Schema 可能过时 — DHCP 下 IP 会变，需定期刷新
- 安全分级是参考 — 最终判断权在用户

## 依赖

- Bash (macOS/Linux)
- Python 3.6+
- `curl`, `ping`, `jq`（通常已预装）
- [Hermes Agent](https://github.com/anthropics/hermes-agent)

## 许可证

MIT

## 致谢

设计理念受人类 proprioception（本体感）启发——Agent 需要知道自己有「身体」才能行动。
