---
name: agent-embodiment
description: |
  让 Agent 理解自己的「身体」和所处的物理世界——我是谁、我在哪、我能控制什么、我的边界。
  自动发现运行环境、扫描网络设备、维护持久化的本体 Schema、安全分级执行操作。
  触发词：我的环境、我在哪跑、我的设备、我有什么、自我感知、embodiment、body schema、设备发现、扫描网络、我能控制什么、系统状态、homelab、PVE、虚拟机、VM状态。
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

这不是 HomeLab 管理工具，这是 Agent 的**身体 Schema**。

---

## 本体文件

每次激活时，先读取本体 Schema：

**路径**：`~/.hermes/skills/agent-embodiment/body-schema.json`

如果文件存在且距上次发现 <1 小时，直接用缓存。
如果不存在或过期 → 运行发现流程（Phase 1）。

---

## Phase 1: 自我发现

分 3 步，逐步建立 Agent 的自我认知。

### Step 1: 我是谁（本机探测）

运行本机信息采集脚本，了解自己跑在哪里：

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-self.sh
```

输出示例：
```
hostname: my-macbook
os: macOS 15.4.1
arch: arm64
cpu: Apple M4 Pro (12核)
memory_gb: 16
gpu: Apple M4 Pro GPU
hermes_version: v2026.4.13
hermes_path: /Users/user/.hermes/hermes-agent
ips: 10.x.x.x, 192.168.x.x
python: 3.13
docker: installed
node: v22.x
```

### Step 2: 我在哪（网络发现）

扫描局域网，发现存活设备：

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-network.sh
```

扫描策略：
1. 先读本机 IP 和子网掩码，确定扫描范围
2. ping 扫描存活主机（并行，30 秒内完成）
3. 对存活主机做端口探测（22/SSH、8006/PVE、11434/Ollama、3389/RDP）
4. 根据端口推断设备类型

输出示例：
```
192.168.x.1    alive  ports=80,443        type=router
192.168.x.100  alive  ports=22,8006       type=pve
192.168.x.109  alive  ports=11434         type=windows_vm
192.168.x.110  alive  ports=22            type=unknown
```

### Step 3: 生成/更新 Schema

将发现结果写入 `body-schema.json`，合并已有配置（保留手动添加的设备信息）。

---

## Phase 2: 设备探测

对已发现的每个设备，进一步探测能力和状态：

### PVE（虚拟化平台）

```bash
# 列出所有 VM 及状态
ssh root@<pve_ip> "qm list"

# 获取详细资源
ssh root@<pve_ip> "pvesh get /cluster/resources --type vm --output-format json"
```

提取：VMID、名称、状态（running/stopped）、CPU/内存分配、磁盘大小。

### Windows VM

```bash
# Ollama 模型列表（不需要 SSH）
curl -s http://<vm_ip>:11434/api/tags

# 系统信息（需要 SSH，可能失败）
sshpass -p "$WIN_VM_PASSWORD" ssh <user>@<vm_ip> "systeminfo"
```

### macOS VM

```bash
ssh <user>@<vm_ip> "sw_vers; sysctl -n machdep.cpu.brand_string; system_profiler SPDisplaysDataType"
```

### 网络设备（路由器等）

```bash
# 简单探测
curl -s -o /dev/null -w "%{http_code}" http://<router_ip>
nmap -sV -p 80,443,8080 <router_ip>
```

---

## Phase 3: Schema 合并

发现结果 + 已有配置 = 完整的 body-schema。

**合并规则**：
1. 自动发现的设备 → 新增或更新（标记 `discovered: true`）
2. 手动配置的设备 → 保留不动（标记 `discovered: false`）
3. 缓存中存在但本次未发现的设备 → 标记 `status: unreachable`，不删除
4. 敏感信息（密码）→ 不写入 schema，引用 `.env`

### body-schema.json 完整格式

```json
{
  "self": {
    "hostname": "my-macbook",
    "os": "macOS 15.4.1",
    "arch": "arm64",
    "cpu": "Apple M4 Pro",
    "memory_gb": 16,
    "hermes_version": "v2026.4.13",
    "hermes_path": "/Users/user/.hermes/hermes-agent",
    "ip": ["10.x.x.x", "192.168.x.x"],
    "discovered_at": "2026-04-14T11:00:00+08:00"
  },
  "environment": {
    "timezone": "Asia/Shanghai",
    "network": "192.168.x.0/24",
    "gateway": "192.168.x.1"
  },
  "devices": [
    {
      "id": "pve",
      "type": "hypervisor",
      "name": "Proxmox VE",
      "ip": "192.168.x.100",
      "os": "Proxmox VE 8.x",
      "access": "ssh:root@192.168.x.100",
      "capabilities": ["vm_lifecycle", "vm_console", "storage", "network"],
      "safety_level": "high",
      "vms": [
        {"vmid": 101, "name": "macOS", "status": "running"},
        {"vmid": 103, "name": "Windows", "status": "running"}
      ],
      "discovered": true,
      "status": "reachable",
      "notes": "直接连接，无跳板机"
    },
    {
      "id": "win-vm",
      "type": "vm",
      "name": "Windows VM",
      "ip": "192.168.x.109",
      "os": "Windows 11",
      "host": "pve",
      "vmid": 103,
      "access": {
        "ssh": {"available": false, "reason": "key exchange reset"},
        "ollama_api": {"available": true, "url": "http://192.168.x.109:11434"}
      },
      "capabilities": ["ollama_inference", "powershell"],
      "safety_level": "medium",
      "gpu": "RTX 5070 12GB",
      "ollama_models": ["model-name", "model-name"],
      "discovered": true,
      "status": "reachable",
      "notes": "SSH 不稳定，Ollama API 可直连"
    }
  ],
  "services": [
    {
      "id": "hermes-dashboard",
      "name": "Hermes Dashboard",
      "url": "http://10.x.x.x:9119",
      "capabilities": ["config_management", "session_view"],
      "safety_level": "low"
    },
    {
      "id": "hermes-gateway",
      "name": "Hermes Gateway",
      "platforms": ["feishu", "telegram", "discord", "weixin"],
      "capabilities": ["messaging", "cron"],
      "safety_level": "low"
    }
  ],
  "discovery_meta": {
    "last_full_discovery": "2026-04-14T11:00:00+08:00",
    "last_incremental": "2026-04-14T11:30:00+08:00",
    "schema_version": "1.0"
  }
}
```

---

## Phase 4: 安全操作框架

执行任何操作前，先做安全分级：

### 操作分级表

| 级别 | 图标 | 定义 | 行为 | 示例 |
|------|------|------|------|------|
| 只读 | 🟢 | 不改变任何状态 | 直接执行 | `qm list`、`curl api/tags`、`ping` |
| 低风险 | 🟡 | 可逆操作，影响范围可控 | 执行后报告 | 启动 VM、下载模型、创建文件 |
| 中风险 | 🟠 | 部分可逆，可能影响服务 | 先简述影响，等确认 | 停止 VM、删除模型、修改配置 |
| 高风险 | 🔴 | 不可逆或影响整个系统 | 必须确认 + 说明后果 | 强制关机、删除 VM、`rm -rf` |

### 判断流程

```
收到操作请求
  ↓
查 body-schema.json → 这个设备的 safety_level 是什么？
  ↓
查操作分级表 → 这个操作是什么级别？
  ↓
只读？→ 直接执行
低风险？→ 执行，完成后告诉用户
中风险？→ 说「我准备做 X，会影响 Y，确认吗？」
高风险？→ 说「X 操作不可逆，会导致 Y，你确定？」
```

### 不确定时的默认行为

- 找不到设备信息 → 问用户
- 操作分级不明确 → 按高一级处理
- 网络不通 → 先检查连通性，不直接假设失败

---

## Phase 5: 持久化

### 写入 MEMORY.md

发现完成后，把关键信息写入 agent 持久记忆：

```
**Agent 本体**: 跑在 macOS M4 Pro 上，Hermes v2026.4.13
**可控设备**: PVE (192.168.x.100)、Windows VM (192.168.x.109, RTX 5070)、Hermes Dashboard
**已知限制**: Windows VM SSH 不稳定，用 Ollama API 替代
**最后发现**: 2026-04-14
```

### Schema 文件

完整 schema 存 `body-schema.json`，每次激活时读取，发现变化时更新。

---

## 使用场景

### 用户问「你跑在什么上面？」

→ 读 body-schema.json，告诉用户：
「我跑在你的 MacBook Pro 上，M4 Pro 芯片，16GB 内存，macOS 15.4。」

### 用户问「你能控制什么？」

→ 读 devices 列表：
「我能管理 PVE 上的 2 台 VM（macOS 和 Windows），Windows 上的 Ollama 有 2 个模型。Hermes Dashboard 也能访问。」

### 用户说「看看网络里有什么」

→ 运行 discover-network.sh，报告发现结果。

### 用户说「帮我重启 Windows VM」

→ 查 safety_level=high（PVE 操作）+ 操作分级=中风险
→ 先确认：「Windows VM 正在运行中，重启会中断 Ollama 推理。确认要重启吗？」

---

## 发现脚本

所有脚本在 `~/.hermes/skills/agent-embodiment/scripts/` 下：

| 脚本 | 功能 | 耗时 |
|------|------|------|
| `discover-self.sh` | 本机信息采集 | <5秒 |
| `discover-network.sh` | 局域网扫描 | ~30秒 |
| `discover-pve.sh` | PVE VM 列表 | ~5秒 |
| `discover-ollama.sh` | Ollama 模型探测 | ~3秒 |

### 手动运行全部发现

```bash
for script in ~/.hermes/skills/agent-embodiment/scripts/discover-*.sh; do
  echo "=== $(basename $script) ==="
  bash "$script"
done
```

---

## 与其他 Skill 的关系

| Skill | 关系 |
|-------|------|
| `homelab-control` | 提供具体设备的控制命令（SSH、PVE API），embodiment 调用它执行操作 |
| `openhue` | 智能家居设备，可纳入 embodiment 的 devices 列表 |
| `memory` | embodiment 的发现结果写入持久记忆 |
| `cron` | 可定期跑发现脚本，保持环境感知最新 |

---

## 扩展指南

### 添加新设备类型

1. 在 `body-schema.json` 的 devices 中添加条目
2. 写对应的 `discover-xxx.sh` 脚本（可选）
3. 定义 capabilities 和 safety_level
4. 测试连通性

### 从外部 Skill 注册设备

其他 skill 可以在 `body-schema.json` 中注册自己的设备：

```json
{
  "id": "philips-hue",
  "type": "smart_home",
  "name": "Philips Hue Bridge",
  "ip": "192.168.x.xxx",
  "registered_by": "openhue-skill",
  "capabilities": ["light_control", "scene"],
  "safety_level": "low"
}
```

这样 embodiment 就成了所有设备的**统一注册中心**。

---

## 诚实边界

1. **发现能力有限** — ping 扫描只能发现存活主机，端口探测可能被防火墙阻挡
2. **不替代专业监控** — 这是 agent 的环境感知，不是 Zabbix/Prometheus
3. **Schema 可能过时** — DHCP 环境下 IP 会变，需要定期刷新
4. **安全分级是参考** — 最终判断权在用户，agent 只是提供建议
5. **只覆盖已知协议** — SSH、HTTP API、Ollama，未知协议需要手动配置

---

**维护者**: 劲阳
**最后更新**: 2026-04-14
**版本**: 2.0 (从 homelab-control 重写)
