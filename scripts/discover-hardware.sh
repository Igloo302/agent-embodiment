#!/bin/bash
# discover-hardware.sh — 本机硬件探测
# 检测音频、蓝牙、显示器、摄像头、USB、打印机、挂载存储

set -euo pipefail

echo "=== 本机硬件探测 ==="
echo ""

# ---------------------------------------------------------------
# 1. 音频设备
# ---------------------------------------------------------------
echo "--- 🔊 音频设备 ---"
audio=$(system_profiler SPAudioDataType 2>/dev/null || true)
if [[ -n "$audio" ]]; then
  echo "$audio" | grep -E "^\s+(.*麦克风|.*扬声器|.*Speaker|.*Microphone|.*Headphone|.*耳机|.*AirPods|.*Immersed|.*Virtual)" | while IFS= read -r line; do
    name=$(echo "$line" | sed 's/^[[:space:]]*//' | sed 's/:$//')
    echo "  🎵 $name"
  done
else
  echo "  (无法获取)"
fi

# ---------------------------------------------------------------
# 2. 蓝牙设备
# ---------------------------------------------------------------
echo ""
echo "--- 📱 蓝牙设备 ---"
bt=$(system_profiler SPBluetoothDataType 2>/dev/null || true)
if [[ -n "$bt" ]]; then
  # 蓝牙状态
  bt_state=$(echo "$bt" | grep -i "^\s*state:" | head -1 | sed 's/.*: //' || echo "unknown")
  echo "  状态: $bt_state"
  
  # 提取设备名和状态
  echo "$bt" | awk '
    /Device Name/ { name = $0; gsub(/.*: /, "", name) }
    /Chipset/ || /Device Name/ { next }
    /State: Connected/ { if (name != "") { print "  🟢 " name " (已连接)"; name = "" } }
    /State: Paired/ { if (name != "") { print "  ⚪ " name " (已配对)"; name = "" } }
    /State: Not Connected/ { if (name != "") { print "  ⚪ " name " (未连接)"; name = "" } }
  '
  if [[ -z "$(echo "$bt" | grep "Device Name")" ]]; then
    echo "  无蓝牙设备"
  fi
else
  echo "  (无法获取)"
fi

# ---------------------------------------------------------------
# 3. 显示器
# ---------------------------------------------------------------
echo ""
echo "--- 🖥️ 显示器 ---"
displays=$(system_profiler SPDisplaysDataType 2>/dev/null || true)
if [[ -n "$displays" ]]; then
  echo "$displays" | grep -E "(Resolution|Display Type|Chip)" | while IFS= read -r line; do
    cleaned=$(echo "$line" | sed 's/^[[:space:]]*//')
    echo "  📺 $cleaned"
  done
else
  echo "  (无法获取)"
fi

# ---------------------------------------------------------------
# 4. 摄像头
# ---------------------------------------------------------------
echo ""
echo "--- 📷 摄像头 ---"
cameras=$(system_profiler SPCameraDataType 2>/dev/null || true)
if [[ -n "$cameras" ]]; then
  echo "$cameras" | grep "Model ID" | while IFS= read -r line; do
    name=$(echo "$line" | sed 's/.*Model ID: //' | sed 's/^[[:space:]]*//')
    echo "  📸 $name"
  done
  cam_count=$(echo "$cameras" | grep -c "Model ID:" || echo "0")
  echo "  共 $cam_count 个摄像头"
else
  echo "  无摄像头"
fi

# ---------------------------------------------------------------
# 5. 打印机
# ---------------------------------------------------------------
echo ""
echo "--- 🖨️ 打印机 ---"
printers=$(system_profiler SPPrintersDataType 2>/dev/null || true)
if [[ -n "$printers" ]] && echo "$printers" | grep -q "Name:\|Location:\|Driver Version:"; then
  echo "$printers" | awk '
    /Name:/ { gsub(/^[[:space:]]+/, ""); print "  🖨️ " $0 }
    /Location:/ { gsub(/^[[:space:]]+/, ""); print "    " $0 }
    /Status:/ { gsub(/^[[:space:]]+/, ""); print "    " $0 }
  '
else
  # 尝试 CUPS
  if command -v lpstat &>/dev/null; then
    cups=$(lpstat -p 2>/dev/null | head -5 || true)
    if [[ -n "$cups" ]]; then
      echo "$cups" | sed 's/^/  /'
    else
      echo "  无打印机"
    fi
  else
    echo "  无打印机"
  fi
fi

# ---------------------------------------------------------------
# 6. USB 设备（顶层）
# ---------------------------------------------------------------
echo ""
echo "--- ⌨️ USB 设备 ---"
usb=$(system_profiler SPUSBDataType 2>/dev/null || true)
if [[ -n "$usb" ]]; then
  # 只取顶层设备名（两个空格开头的行）
  echo "$usb" | grep -E "^  [A-Z]" | sed 's/:$//' | head -20 | while IFS= read -r line; do
    name=$(echo "$line" | sed 's/^[[:space:]]*//')
    echo "  🔌 $name"
  done
else
  echo "  (无法获取)"
fi

# ---------------------------------------------------------------
# 7. 挂载存储
# ---------------------------------------------------------------
echo ""
echo "--- 💾 挂载存储 ---"
df -h 2>/dev/null | awk 'NR>1 && $6 !~ /^\/(System|private|dev|Library|cores|opt)\// && $1 !~ /^(devfs|map|tmpfs)/ {
  printf "  💽 %-12s %5s / %5s  → %s\n", $1, $3, $2, $6
}' | head -15

echo ""
echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
