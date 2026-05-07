#!/usr/bin/env python3
"""
log-operation.py — 操作历史记录
记录 Agent 对设备的操作历史，用于审计和故障排查。

用法:
  python3 log-operation.py --action vm-start --target 192.168.5.109 --result success --duration 3500
  python3 log-operation.py --action ssh-connect --target 192.168.1.100 --result fail --reason "Connection refused"
  python3 log-operation.py --list  # 查看最近操作
  python3 log-operation.py --list --target 192.168.1.100  # 按设备筛选

操作日志格式:
{
  "timestamp": "2026-04-26T14:00:00+08:00",
  "action": "vm-start",
  "target": "192.168.5.109",
  "target_name": "Win-RTX5070",
  "result": "success",
  "duration_ms": 3500,
  "detail": "VM 103 started successfully"
}
"""

import json
import sys
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 动态获取 skill 目录（脚本所在目录的上一级）
SKILL_DIR = Path(__file__).parent.parent.resolve()
SCHEMA_PATH = SKILL_DIR / "body-schema.json"
OPERATIONS_LOG = SKILL_DIR / "operations.log"

CST = timezone(timedelta(hours=8))

# 操作类型分类
ACTION_CATEGORIES = {
    # VM 操作
    "vm-start": "vm",
    "vm-stop": "vm",
    "vm-restart": "vm",
    "vm-snapshot": "vm",
    "vm-migrate": "vm",

    # SSH 操作
    "ssh-connect": "ssh",
    "ssh-disconnect": "ssh",
    "ssh-command": "ssh",

    # 服务操作
    "service-start": "service",
    "service-stop": "service",
    "service-restart": "service",
    "service-reload": "service",

    # 推理服务
    "ollama-pull": "inference",
    "ollama-run": "inference",
    "ollama-delete": "inference",
    "model-load": "inference",
    "model-unload": "inference",

    # 文件操作
    "file-upload": "file",
    "file-download": "file",
    "file-delete": "file",

    # 网络操作
    "network-scan": "network",
    "port-forward": "network",

    # 容器操作
    "docker-start": "container",
    "docker-stop": "container",
    "docker-restart": "container",
    "docker-pull": "container",

    # 其他
    "discover": "discovery",
    "verify": "verification",
}


def get_device_name(ip: str) -> str:
    """从 schema 获取设备名称"""
    if not SCHEMA_PATH.exists():
        return ip

    try:
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        for device in schema.get("devices", []):
            if device.get("ip") == ip:
                return device.get("name", ip)
    except Exception:
        pass
    return ip


def log_operation(action: str, target: str, result: str, duration_ms: int = None,
                  detail: str = None, reason: str = None, user: str = None):
    """记录操作到日志文件

    Args:
        action: 操作类型 (vm-start, ssh-connect, etc.)
        target: 目标 IP 或设备 ID
        result: 结果 (success, fail, timeout)
        duration_ms: 操作耗时（毫秒）
        detail: 详细信息
        reason: 失败原因
        user: 操作用户（可选）
    """
    # 确保目录存在
    SKILL_DIR.mkdir(parents=True, exist_ok=True)

    # 构建日志条目
    entry = {
        "timestamp": datetime.now(CST).isoformat(),
        "action": action,
        "category": ACTION_CATEGORIES.get(action, "other"),
        "target": target,
        "target_name": get_device_name(target) if target else None,
        "result": result,
    }

    if duration_ms is not None:
        entry["duration_ms"] = duration_ms
    if detail:
        entry["detail"] = detail
    if reason:
        entry["reason"] = reason
    if user:
        entry["user"] = user

    # 追加到日志文件
    with open(OPERATIONS_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return entry


def list_operations(limit: int = 50, target: str = None, action: str = None,
                    result: str = None, category: str = None):
    """列出操作历史

    Args:
        limit: 最大返回条数
        target: 按目标筛选
        action: 按操作类型筛选
        result: 按结果筛选
        category: 按分类筛选

    Returns:
        操作列表
    """
    if not OPERATIONS_LOG.exists():
        return []

    operations = []
    with open(OPERATIONS_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)

                # 应用筛选条件
                if target and entry.get("target") != target:
                    continue
                if action and entry.get("action") != action:
                    continue
                if result and entry.get("result") != result:
                    continue
                if category and entry.get("category") != category:
                    continue

                operations.append(entry)
            except json.JSONDecodeError:
                continue

    # 按时间倒序，返回最近的记录
    operations.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return operations[:limit]


def get_statistics(days: int = 7):
    """获取操作统计

    Args:
        days: 统计最近 N 天

    Returns:
        统计信息 dict
    """
    if not OPERATIONS_LOG.exists():
        return {"total": 0, "by_action": {}, "by_result": {}, "by_target": {}}

    cutoff = datetime.now(CST) - timedelta(days=days)
    stats = {
        "total": 0,
        "by_action": {},
        "by_result": {},
        "by_target": {},
        "by_category": {},
    }

    with open(OPERATIONS_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ts_str = entry.get("timestamp", "")
                if ts_str:
                    ts = datetime.fromisoformat(ts_str)
                    if ts < cutoff:
                        continue

                stats["total"] += 1

                action = entry.get("action", "unknown")
                stats["by_action"][action] = stats["by_action"].get(action, 0) + 1

                result = entry.get("result", "unknown")
                stats["by_result"][result] = stats["by_result"].get(result, 0) + 1

                target = entry.get("target", "unknown")
                stats["by_target"][target] = stats["by_target"].get(target, 0) + 1

                category = entry.get("category", "other")
                stats["by_category"][category] = stats["by_category"].get(category, 0) + 1

            except (json.JSONDecodeError, ValueError):
                continue

    return stats


def main():
    parser = argparse.ArgumentParser(description="操作历史记录")
    parser.add_argument("--action", help="操作类型 (vm-start, ssh-connect, etc.)")
    parser.add_argument("--target", help="目标 IP 或设备 ID")
    parser.add_argument("--result", help="结果 (success/fail/timeout)")
    parser.add_argument("--duration", type=int, help="操作耗时（毫秒）")
    parser.add_argument("--detail", help="详细信息")
    parser.add_argument("--reason", help="失败原因")
    parser.add_argument("--user", help="操作用户")

    # 查询模式
    parser.add_argument("--list", action="store_true", help="列出操作历史")
    parser.add_argument("--limit", type=int, default=50, help="最大返回条数")
    parser.add_argument("--category", help="按分类筛选 (vm/ssh/service/inference/file/network/container)")
    parser.add_argument("--stats", action="store_true", help="显示操作统计")
    parser.add_argument("--days", type=int, default=7, help="统计最近 N 天")

    args = parser.parse_args()

    # 统计模式
    if args.stats:
        stats = get_statistics(days=args.days)
        print(f"📊 操作统计（最近 {args.days} 天）")
        print(f"   总计: {stats['total']} 次操作")
        print()
        print("   按分类:")
        for cat, count in sorted(stats["by_category"].items(), key=lambda x: -x[1]):
            print(f"     {cat}: {count}")
        print()
        print("   按结果:")
        for result, count in stats["by_result"].items():
            icon = "✅" if result == "success" else "❌"
            print(f"     {icon} {result}: {count}")
        return

    # 列表模式
    if args.list:
        operations = list_operations(
            limit=args.limit,
            target=args.target,
            action=args.action,
            result=args.result,
            category=args.category,
        )

        if not operations:
            print("📭 无操作记录")
            return

        print(f"📋 操作历史（最近 {len(operations)} 条）")
        print()
        for op in operations:
            icon = "✅" if op.get("result") == "success" else "❌"
            ts = op.get("timestamp", "")[11:19]  # 只显示时间
            action = op.get("action", "?")
            target = op.get("target_name") or op.get("target", "?")
            duration = f" ({op['duration_ms']}ms)" if op.get("duration_ms") else ""
            detail = f" — {op.get('detail', '')}" if op.get("detail") else ""
            reason = f" — {op.get('reason', '')}" if op.get("reason") else ""

            print(f"  {icon} {ts} [{action}] {target}{duration}{detail}{reason}")
        return

    # 记录模式
    if not args.action or not args.target or not args.result:
        print("❌ 错误: 记录操作需要 --action, --target, --result", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    entry = log_operation(
        action=args.action,
        target=args.target,
        result=args.result,
        duration_ms=args.duration,
        detail=args.detail,
        reason=args.reason,
        user=args.user,
    )

    icon = "✅" if args.result == "success" else "❌"
    print(f"{icon} 已记录: [{args.action}] {entry.get('target_name', args.target)} — {args.result}")


if __name__ == "__main__":
    main()
