---
name: agent-embodiment
description: |
  让 Agent 理解自己的「身体」和所处的物理世界——我是谁、我在哪、我能控制什么、我的边界。
  自动发现运行环境、扫描网络设备、维护持久化的本体 Schema、安全分级执行操作。
  触发词：我的环境、我在哪跑、我的设备、我有什么、自我感知、embodiment、body schema、设备发现、扫描网络、我能控制什么、系统状态、homelab、PVE、虚拟机、VM状态、开关机、启动/关闭VM、查看虚拟机状态、SSH连接、Ollama、本地模型、GPU状态、VRAM、推理能力、模型部署、算力。
  也适用于：用户问「你跑在什么上面」「你能控制哪些设备」「看看我的网络环境」。
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

这不是任何特定场景的管理工具。这是 Agent 的**身体 Schema**。
适用于 Mac、Linux、Docker 容器、NAS、甚至嵌入式设备。

---

## Phase 0: 前置条件

激活时先读本体 Schema：

**路径**：`~/.hermes/skills/agent-embodiment/body-schema.json`

### 缓存检查

- 文件存在且距上次发现 **< 1 小时** → 直接用缓存，跳到 Phase 4
- 文件不存在 → 运行完整发现流程（Phase 1），生成初始 schema
- 文件损坏/JSON 解析失败 → 删除重建

### 新用户首次激活

schema 为空时，只需运行：

```bash
python3 ~/.hermes/skills/agent-embodiment/scripts/merge-schema.py
```

它会自动跑所有发现脚本并生成初始 schema。

---

## Phase 1: 自我发现

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-self.sh
```

采集：hostname、OS、架构、CPU、内存、IP、Hermes 版本、Python/Docker/Node 状态。

### 网络发现

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-network.sh
```

自动执行：存活探测（schema 已知 IP + ARP 补充）→ 端口扫描（SSH/HTTP/SMB/Ollama/PVE 等 27 种端口）→ mDNS/Bonjour 服务发现。

### 推理能力

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-inference.sh
```

探测 GPU（CUDA/Metal/ROCm）、VRAM、推理后端（Ollama/vLLM/llama.cpp/LM Studio）、模型清单、容量评估。**不绑定特定后端**。

### 本机硬件

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-hardware.sh
```

音频设备、蓝牙、显示器、摄像头、USB、打印机、挂载存储。

---

## Phase 2: 设备探测

对已发现的设备进一步探测。具体命令取决于设备类型——Agent 根据 body-schema.json 中的 `type` 和 `capabilities` 自行决定。

常见设备类型：

| type | 探测方式 |
|------|---------|
| `hypervisor` (PVE 等) | SSH `qm list` / API |
| `vm` | SSH / HTTP API |
| `nas` (Synology 等) | DSM API / SMB |
| `docker_host` | `docker ps` / Docker API |
| `smart_home` | 对应 skill 探测 |
| `inference_server` | HTTP API (`/api/tags`, `/v1/models`) |

Agent 不需要在 skill 里记住每个设备的具体命令。body-schema.json 的 `access` 字段告诉 Agent 怎么连，`capabilities` 告诉 Agent 能做什么。

---

## Phase 2.5: 安全确认模板

### 中风险

```
⚠️ 准备执行：{操作描述}
设备：{设备名} ({ip})
影响：{具体影响}
可逆性：{是/否，如何回滚}
确认执行？[是/否]
```

### 高风险

```
🔴 危险操作确认：{操作描述}
设备：{设备名} ({ip})
后果：{不可逆影响}
回滚：{能否回滚，怎么做}
请回复「确认执行」继续，或说「取消」中止。
```

---

## Phase 3: Schema 自动合并

```bash
python3 ~/.hermes/skills/agent-embodiment/scripts/merge-schema.py
```

自动执行：读 schema → discover-self → 测试连通性 → 检测推理后端 → 合并写回。

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

## Phase 4: 安全操作框架

| 级别 | 定义 | 行为 |
|------|------|------|
| 🟢 只读 | 不改变任何状态 | 直接执行 |
| 🟡 低风险 | 可逆，影响可控 | 执行后报告 |
| 🟠 中风险 | 部分可逆，可能影响服务 | 先确认 |
| 🔴 高风险 | 不可逆或影响全局 | 必须确认 + 说明后果 |

不确定时按高一级处理。

---

## Phase 4.5: 动作验证闭环

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/verify-action.sh <action> <target> [expected]
```

返回 JSON：`{"status": "pass"|"fail", "detail": "..."}`

常用验证：

| 动作 | 参数 | 用途 |
|------|------|------|
| `vm-running` | `<pve-ip> <vmid>` | VM 是否运行 |
| `ssh-reachable` | `<ip>` | SSH 端口开放 |
| `service-up` | `<url>` | HTTP 服务响应 |
| `ollama-up` / `ollama-model` | `<url> [model]` | 推理服务/模型状态 |
| `process-running` | `<name>` | 进程状态 |
| `disk-space` | `<mount> <max%>` | 磁盘使用率 |
| `network-check` | `<ip> <ports>` | 多端口批量检查 |

---

## Phase 5: 持久化

发现完成后，把关键信息写入 agent 持久记忆：

```
**Agent 本体**: 跑在 <hostname> 上，Hermes v2026.x.x
**可控设备**: <设备列表>
**已知限制**: <踩过的坑>
**最后发现**: <日期>
```

---

## 发现脚本

`~/.hermes/skills/agent-embodiment/scripts/` 下：

| 脚本 | 功能 |
|------|------|
| `discover-self.sh` | 本机信息 |
| `discover-hardware.sh` | 音频/蓝牙/显示器/摄像头/USB/存储 |
| `discover-network.sh` | 网络发现（存活探测 + 端口 + mDNS） |
| `discover-mdns.sh` | mDNS/Bonjour 服务发现 |
| `discover-pve.sh` | PVE VM 列表（可选插件） |
| `discover-inference.sh` | GPU/VRAM/推理后端/模型 |
| `merge-schema.py` | 自动合并 → body-schema.json |
| `verify-action.sh` | 操作结果验证 |

脚本失败 fallback：用基础命令（`uname -a`、`hostname`、`ping`）逐个采集。

---

## 使用场景

**「你跑在什么上面？」** → 读 schema 的 `self` 字段回答。

**「你能控制什么？」** → 读 `devices` 列表 + `capabilities`。

**「看看网络里有什么」** → 跑 `discover-network.sh`。

**「我有什么算力？」** → 跑 `discover-inference.sh`，汇报 GPU/VRAM/模型/容量。

**「帮我重启 XX」** → 查 safety_level + 操作分级 → 确认 → 执行 → `verify-action.sh` 验证。

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

---

**维护者**: 劲阳
**最后更新**: 2026-04-15
**版本**: 3.0 (精简瘦身 + 通用化 + 脚本整合)
