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

这不是 HomeLab 管理工具，这是 Agent 的**身体 Schema**。

---

## 环境上下文

激活时同步感知的两个维度——不是脚本，是读取 session 状态。

### 平台感知

Agent 的会话来源包含当前平台信息。读取后据此调整行为：

| 平台 | 风格 |
|------|------|
| Telegram | 简洁，不用 markdown，可以发语音/图片 |
| 飞书 | 工作场景，紧凑排版，可用富文本 |
| Discord | 可以用代码块、较长回复 |
| 微信 | 最简洁，不用格式，纯文字 |

知道自己「站在哪个通道里」，就不需要用户说「别发 markdown」。

### 时间感知

每次激活时读取当前时间（`date`），结合 body-schema.json 的 timezone 判断：

- **深夜 (23:00-07:00)**：用户可能在休息，非紧急操作延后或格外谨慎确认
- **工作时间 (09:00-18:00)**：用户可能在忙，回复简洁高效
- **晚间 (18:00-23:00)**：用户可能在休闲，可以更放松

时间信息也可以用于：
- 「上次发现是 3 小时前」→ 提示 schema 可能过时
- 「VM 上次重启是凌晨 2 点」→ 推断可能是自动更新

---

## Phase 0: 前置条件

每次激活时，先读取本体 Schema：

**路径**：`~/.hermes/skills/agent-embodiment/body-schema.json`

### 缓存检查

- 文件存在且距上次发现 **< 1 小时** → 直接用缓存，跳到 Phase 4
- 文件不存在或过期 → 运行发现流程（Phase 1）
- 文件损坏/JSON 解析失败 → 删除重建，运行完整发现流程

### 网络前置

执行发现前确认网络连通。如果使用 ZeroTier 等 VPN，注意跨网段路由。

连通性速检：

```bash
zerotier-cli status          # 确认 ZT 在线 (ONLINE)
zerotier-cli listnetworks    # 确认网络 OK，看分配的 IP
ping -c 1 <pve-ip>           # 测试 PVE 路由（ZT 延迟 ~200ms 正常）
ping -c 1 <vm-ip>            # 测试目标 VM
```

### SSH 配置

所有远程设备通过 SSH Host 别名连接。`~/.ssh/config` 示例：

```
Host pve-alias
  HostName 192.168.x.100
  User root
  KexAlgorithms curve25519-sha256,ecdh-sha2-nistp256,diffie-hellman-group14-sha256
  ConnectTimeout 15

Host vm-alias
  HostName 192.168.x.109
  User your-username
  KexAlgorithms curve25519-sha256,ecdh-sha2-nistp256,diffie-hellman-group14-sha256
  ConnectTimeout 15
```

> ⚠️ **macOS 后量子 KEX 问题**: macOS OpenSSH 10.2+ 默认启用 `mlkem768x25519-sha256`，握手包 ~1.5KB，过 ZT 隧道（延迟 200ms+、MTU 2800）会分片丢失导致 **SSH 在密钥交换卡死**。必须在 SSH config 中禁用 PQ 算法（见上方配置）。

> ⚠️ **Windows VM 管理员 SSH**: 管理员组的 authorized_keys 路径**不是** `~/.ssh/authorized_keys`，而是 `C:\ProgramData\ssh\administrators_authorized_keys`。设置公钥后需 `icacls` 调整权限。

---

## Phase 1: 自我发现

分 3 步，逐步建立 Agent 的自我认知。

### Step 1: 我是谁（本机探测）

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-self.sh
```

输出示例：

```
hostname: your-hostname
os: macOS 15.x
arch: arm64
cpu: Apple M4 Pro (12核)
memory_gb: 16
hermes_version: v2026.x.x
hermes_path: /Users/your-username/.hermes/hermes-agent
ips: 192.168.x.x, 10.x.x.x
python: 3.13
docker: installed
node: v22.x
```

### Step 2: 我在哪（网络发现）

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-network.sh
```

扫描策略：
1. 读本机 IP 和子网掩码，确定扫描范围
2. ping 扫描存活主机（并行，30 秒内完成）
3. 对存活主机做端口探测（22/SSH、8006/PVE、11434/Ollama、3389/RDP）
4. 根据端口推断设备类型

输出示例：

```
192.168.x.1    alive  ports=80,443        type=router
192.168.x.100  alive  ports=22,8006       type=pve
192.168.x.109  alive  ports=11434         type=vm
```

### Step 3: 生成/更新 Schema

将发现结果写入 `body-schema.json`，合并已有配置（保留手动添加的设备信息）。

---

## Phase 2: 设备探测 + 操作速查

对已发现的每个设备，进一步探测能力和状态。每个设备类型附带操作速查卡。

### PVE（虚拟化平台）

**探测**：

```bash
ssh <pve-alias> "qm list"                                    # 列出 VM 状态
ssh <pve-alias> "pvesh get /cluster/resources --type vm --output-format json"  # 详细资源
```

**操作速查**：

```bash
# VM 生命周期
ssh <pve-alias> "qm list"                   # 查看所有 VM 状态
ssh <pve-alias> "qm start <vmid>"           # 启动 VM
ssh <pve-alias> "qm shutdown <vmid>"        # 正常关机
ssh <pve-alias> "qm stop <vmid>"            # 强制关机（危险！）
ssh <pve-alias> "qm config <vmid>"          # 查看 VM 详情
ssh <pve-alias> "ip neigh | grep -i '<mac>'"  # 查找 VM IP（ARP 表）
```

提取：VMID、名称、状态（running/stopped）、CPU/内存分配、磁盘大小。

### Windows VM

**探测**：

```bash
curl -s http://<vm-ip>:11434/api/tags    # Ollama 模型列表（无需 SSH）
ssh vm-alias "hostname && whoami"                  # SSH 测试（可能不稳定）
```

**操作速查**：

```bash
# SSH 免密执行
ssh vm-alias "hostname && whoami"

# 需要密码时（密码通过环境变量传入，不要写死）
sshpass -p "$VM_PASSWORD" ssh -o StrictHostKeyChecking=no user@<vm-ip> "command"

# Ollama API（推荐，无需 SSH）
curl -s http://<vm-ip>:11434/api/tags | python3 -m json.tool
curl -s http://<vm-ip>:11434/api/show -d '{"model": "model-name"}' | python3 -m json.tool
curl -s http://<vm-ip>:11434/api/generate -d '{"model": "model-name", "prompt": "Hello", "stream": false}'
```

### macOS VM

```bash
ssh <user>@<vm_ip> "sw_vers; sysctl -n machdep.cpu.brand_string; system_profiler SPDisplaysDataType"
```

### 网络设备（路由器等）

```bash
curl -s -o /dev/null -w "%{http_code}" http://<router_ip>   # 简单探测
nmap -sV -p 80,443,8080 <router_ip>                          # 端口扫描
```

### 本地推理能力（重点关注）

本地模型部署是核心能力。探测每个设备的推理潜力：

```bash
bash ~/.hermes/skills/agent-embodiment/scripts/discover-inference.sh
```

探测内容：
1. **GPU** — NVIDIA CUDA / Apple Metal / AMD ROCm，型号、显存总量/已用/空闲
2. **推理后端** — Ollama / vLLM / llama.cpp / LM Studio，自动发现运行中的实例
3. **模型清单** — 每个模型的参数量、量化方式、大小、是否已加载
4. **容量评估** — 根据可用 VRAM 估算能跑多大的模型

### MoE 模型理解

"Gemma 4 E4B" 中的 "E" = **Effective 参数**（MoE 混合专家架构）：
- 总参数 8B — 知识容量
- 每次推理只激活 ~4B 参数 — 实际计算量
- 效果：推理速度相当于 4B 模型，知识质量接近更大模型
- 实测：E4B 在所有 benchmark 上碾压 Gemma 3 27B

12GB VRAM 甜点：
- **E4B (8B Q4)** — ~10GB VRAM，115 tok/s (RTX 5070)，最佳选择
- **13B Q4** — ~8GB VRAM，80+ tok/s，质量更高
- **26B MoE (4B active)** — 18GB，放不下 12GB 卡

输出示例：

```
--- 本机 GPU ---
backend: CUDA (nvidia-smi)
  GPU 0: NVIDIA GeForce RTX 5070 | 12288MB total, 8192MB free | 15% util | 42°C

--- 推理后端 ---
ollama: running (localhost:11434)
  models: 2
vllm: running (localhost:8000)

--- 推理容量评估 ---
  可用 VRAM: 8.0GB → 约可运行 7B-13B (Q4)
  当前已加载模型: 1 个
```

**推理能力速查卡**：

```bash
# Ollama
curl -s http://<endpoint>/api/tags | python3 -m json.tool    # 模型列表
curl -s http://<endpoint>/api/ps | python3 -m json.tool      # 已加载模型

# GPU
nvidia-smi                                                    # NVIDIA 显卡状态
system_profiler SPDisplaysDataType                            # macOS Metal

# 快速测试推理（验证端点可用）
curl -s http://<endpoint>/api/generate \
  -d '{"model":"<model-name>","prompt":"hi","stream":false}' | head -c 200
```

---

## Phase 2.5: 安全确认模板

执行中/高风险操作前，使用以下确认格式：

### 中风险确认

```
⚠️ 准备执行：{操作描述}
设备：{设备名} ({ip})
影响：{具体影响}
可逆性：{是/否，如何回滚}
确认执行？[是/否]
```

### 高风险确认

```
🔴 危险操作确认：{操作描述}
设备：{设备名} ({ip})
后果：{不可逆影响}
回滚：{能否回滚，怎么做}
请回复「确认执行」继续，或说「取消」中止。
```

---

## Phase 3: Schema 自动合并

运行 `merge-schema.py` 自动完成发现 → 合并 → 写入全流程：

```bash
python3 ~/.hermes/skills/agent-embodiment/scripts/merge-schema.py
```

自动执行：
1. 读取现有 body-schema.json
2. 运行 discover-self.sh 获取本机信息
3. 测试所有已知设备连通性
4. 运行 discover-inference.sh 探测推理能力
5. 按合并规则写回 body-schema.json

### 合并规则

1. 自动发现的设备 → 新增或更新（标记 `discovered: true`）
2. 手动配置的设备 → 保留不动，只更新 status
3. 缓存中存在但本次未发现 → 标记 `status: unreachable`，不删除
4. 敏感信息（密码）→ 不写入 schema

### body-schema.json 完整格式

```json
{
  "self": {
    "hostname": "your-hostname",
    "os": "macOS 15.x",
    "arch": "arm64",
    "cpu": "Apple M4 Pro",
    "memory_gb": 16,
    "hermes_version": "v2026.x.x",
    "hermes_path": "/Users/your-username/.hermes/hermes-agent",
    "ip": ["192.168.x.x", "10.x.x.x"],
    "discovered_at": "2026-01-01T00:00:00+08:00"
  },
  "environment": {
    "timezone": "Asia/Shanghai",
    "networks": ["192.168.x.0/24"],
    "gateway": "192.168.x.1"
  },
  "devices": [
    {
      "id": "pve",
      "type": "hypervisor",
      "name": "Proxmox VE",
      "ip": "192.168.x.100",
      "os": "Proxmox VE 8.x",
      "access": "ssh:<pve-alias>",
      "capabilities": ["vm_lifecycle", "vm_console", "storage", "network"],
      "safety_level": "high",
      "vms": [
        {"vmid": 101, "name": "VM-1", "status": "running"}
      ],
      "discovered": true,
      "status": "reachable",
      "notes": "填写你的 PVE 实际信息"
    },
    {
      "id": "vm-example",
      "type": "vm",
      "name": "Example VM",
      "ip": "192.168.x.109",
      "os": "Windows 11",
      "host": "pve",
      "vmid": 103,
      "access": {
        "ssh": {"available": true, "command": "ssh <vm-alias>"},
        "ollama_api": {"available": true, "url": "http://192.168.x.109:11434"}
      },
      "capabilities": ["ollama_inference", "powershell"],
      "safety_level": "medium",
      "gpu": "your-gpu-model",
      "ollama_models": ["model-name:size"],
      "discovered": true,
      "status": "reachable",
      "notes": "填写你的 VM 实际信息"
    }
  ],
  "services": [
    {
      "id": "hermes-dashboard",
      "name": "Hermes Dashboard",
      "url": "http://192.168.x.x:9119",
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
    "last_full_discovery": "2026-01-01T00:00:00+08:00",
    "schema_version": "1.1"
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
**Agent 本体**: 跑在 <hostname> 上，Hermes v2026.x.x
**可控设备**: PVE (<pve-ip>)、VM (<vm-ip>)、Hermes Dashboard
**已知限制**: <你的已知限制>
**最后发现**: <日期>
```

### Schema 文件

完整 schema 存 `body-schema.json`，每次激活时读取，发现变化时更新。

---

## 发现脚本

所有脚本在 `~/.hermes/skills/agent-embodiment/scripts/` 下：

| 脚本 | 功能 | 耗时 |
|------|------|------|
| `discover-self.sh` | 本机信息采集 | <5秒 |
| `discover-hardware.sh` | **本机硬件**（音频/蓝牙/显示器/摄像头/USB/打印机/存储） | <10秒 |
| `discover-network.sh` | **网络发现统一入口**（编排存活探测 + mDNS + NAS） | ~60秒 |
| `discover-mdns.sh` | mDNS/Bonjour 服务发现 | ~30秒 |
| `discover-nas.sh` | NAS/服务端口探测 | ~30秒 |
| `discover-pve.sh` | PVE VM 列表 | ~5秒 |
| `discover-ollama.sh` | Ollama 模型探测 | ~3秒 |
| `discover-inference.sh` | **推理能力探测**（GPU/VRAM/后端/模型） | ~10秒 |
| `merge-schema.py` | **Phase 3 自动合并**（运行所有脚本 + 写入 schema） | ~90秒 |

手动运行全部发现：

```bash
for script in ~/.hermes/skills/agent-embodiment/scripts/discover-*.sh; do
  echo "=== $(basename $script) ==="
  bash "$script"
done
```

### 脚本失败 Fallback

| 场景 | Fallback |
|------|---------|
| discover-self.sh 失败 | 用 `uname -a`、`hostname` 等基础命令逐个采集 |
| discover-network.sh 无结果 | 直接 ping 已知 IP（从 body-schema.json 读取） |
| discover-pve.sh SSH 失败 | 尝试 Ollama API 确认 VM 是否在线 |
| discover-ollama.sh 跨网段扫不到 | 用配置的 endpoint 直连测试 |
| body-schema.json 不存在 | 运行全部 discover 脚本，生成初始 schema |
| 脚本无执行权限 | `chmod +x` 后重试，或直接 `bash` 执行 |

---

## 使用场景

### 用户问「你跑在什么上面？」

→ 读 body-schema.json，告诉用户：
「我跑在你的 MacBook Pro 上，M4 Pro 芯片，16GB 内存，macOS 15.4.1。」

### 用户问「你能控制什么？」

→ 读 devices 列表：
「我能管理 PVE 上的 2 台 VM（macOS 和 Windows），Windows 上的 Ollama 有 2 个模型。Hermes Dashboard 也能访问。」

### 用户说「看看网络里有什么」

→ 运行 discover-network.sh + 跨网段 ping，报告发现结果。

### 用户说「帮我重启 Windows VM」

→ 查 safety_level=high（PVE 操作）+ 操作分级=中风险
→ 使用中风险确认模板：
```
⚠️ 准备执行：重启 VM (VMID <vmid>)
设备：PVE (<pve-ip>)
影响：<VM 名> 将重启，服务中断，约 2 分钟恢复
可逆性：否（重启无法撤回，但可以重新启动）
确认执行？[是/否]
```

### 用户问「我有什么算力？」

→ 运行 discover-inference.sh，汇报：
「你有一张 RTX 5070 (12GB VRAM)，当前空闲 8GB，能跑 7B-13B 量化的模型。Ollama 已加载 2 个模型。」

### 用户问「能跑什么模型？」

→ 查 body-schema.json 的 inference 信息：
「根据当前 VRAM，可以流畅跑 7B-13B Q4 量化模型。推荐：Qwen2.5-7B、Llama3-8B。如果用 CPU 推理，7B 约 8-12 tok/s。」

### 用户说「看看 Ollama 状态」

→ 运行 discover-inference.sh 或直接 curl Ollama API：
「Ollama 运行中，3 个模型已安装（model-name、model-name、model-name），当前 gemma4 已加载，VRAM 占用 5.2GB。」

---

## 与其他 Skill 的关系

| Skill | 关系 |
|-------|------|
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

## 排障速查

### ZeroTier

1. `zerotier-cli status` → 确认 ONLINE
2. `zerotier-cli listnetworks` → 确认网络 OK，看分配的 IP
3. `ping <pve-ip>` → 确认路由可达
4. `nc -z -w5 <pve-ip> 22` → 确认端口 open
5. ZT 重连后端口仍不通 → 先 `leave` 再 `join` 重新加入网络

### SSH

6. SSH 卡在 `KEXINIT` / `KEX_ECDH_REPLY` → 后量子算法问题，加 `KexAlgorithms`（见 Phase 0）
7. SSH Permission denied 但密码正确 → Windows 管理员检查 `C:\ProgramData\ssh\administrators_authorized_keys`

### HuggingFace

8. 下载 401 错误 → 需先在 HF 页面点 Agree 接受协议，然后配置 token：
   ```bash
   setx HF_TOKEN "hf_xxxxx"
   curl -L -H "Authorization: Bearer hf_xxxxx" -o model.gguf "https://huggingface.co/.../resolve/main/file.gguf"
   ```

---

## 诚实边界

1. **发现能力有限** — ping 扫描只能发现存活主机，端口探测可能被防火墙阻挡
2. **不替代专业监控** — 这是 agent 的环境感知，不是 Zabbix/Prometheus
3. **Schema 可能过时** — DHCP 环境下 IP 会变，需要定期刷新
4. **安全分级是参考** — 最终判断权在用户，agent 只是提供建议
5. **只覆盖已知协议** — SSH、HTTP API、Ollama，未知协议需要手动配置

---

**维护者**: 劲阳
**最后更新**: 2026-04-15
**版本**: 2.1 (结构重组：整合连接实操、统一 Phase 入口)
