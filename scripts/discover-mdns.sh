#!/bin/bash
# discover-mdns.sh — mDNS/Bonjour 网络服务发现
# 不扫端口，靠 Bonjour 广播自动发现设备

set -euo pipefail

echo "=== mDNS/Bonjour 服务发现 ==="
echo ""

# dns-sd 扫描并提取设备名
scan_service() {
  local type="$1"
  local label="$2"
  local timeout="${3:-4}"
  
  tmpfile=$(mktemp)
  dns-sd -B "$type" > "$tmpfile" 2>/dev/null &
  pid=$!
  sleep "$timeout"
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  
  # 提取 Add 行中的服务名（去重）
  names=$(grep "Add" "$tmpfile" 2>/dev/null | \
    sed 's/.*Add[[:space:]]*[0-9]*[[:space:]]*[0-9]*[[:space:]]*[^ ]*[[:space:]]*[^ ]*[[:space:]]*//' | \
    sed 's/^[[:space:]]*//' | \
    sort -u || true)
  rm -f "$tmpfile"
  
  if [[ -n "$names" ]]; then
    count=$(echo "$names" | wc -l | tr -d ' ')
    echo "  $label ($count 个):"
    echo "$names" | while IFS= read -r name; do
      [[ -n "$name" ]] && echo "    📡 $name"
    done
    echo ""
  fi
}

# ---------------------------------------------------------------
# 媒体投屏
# ---------------------------------------------------------------
echo "--- 📺 媒体投屏 ---"
scan_service "_airplay._tcp"    "AirPlay"
scan_service "_googlecast._tcp" "Chromecast"
scan_service "_raop._tcp"       "AirPlay 音频 (RAOP)"

# ---------------------------------------------------------------
# 音箱/音频
# ---------------------------------------------------------------
echo "--- 🔊 音箱/音频 ---"
scan_service "_sonos._tcp"      "Sonos"
scan_service "_spotify-connect._tcp" "Spotify Connect"
scan_service "_homepod._tcp"    "HomePod"

# ---------------------------------------------------------------
# 打印机
# ---------------------------------------------------------------
echo "--- 🖨️ 网络打印机 ---"
scan_service "_ipp._tcp"        "IPP 打印机"
scan_service "_printer._tcp"    "LPR 打印机"
scan_service "_pdl-datastream._tcp" "Raw 打印机"

# ---------------------------------------------------------------
# 智能家居
# ---------------------------------------------------------------
echo "--- 🏠 智能家居 ---"
scan_service "_hap._tcp"        "HomeKit"
scan_service "_hue._tcp"        "Philips Hue"

# ---------------------------------------------------------------
# 文件共享
# ---------------------------------------------------------------
echo "--- 📁 文件共享 ---"
scan_service "_smb._tcp"        "SMB"
scan_service "_afpovertcp._tcp" "AFP"
scan_service "_nfs._tcp"        "NFS"
scan_service "_sftp-ssh._tcp"   "SFTP"

# ---------------------------------------------------------------
# NAS/服务器
# ---------------------------------------------------------------
echo "--- 🖥️ NAS/服务器 ---"
scan_service "_synology._tcp"   "Synology DSM"
scan_service "_http._tcp"       "HTTP 服务"

# ---------------------------------------------------------------
# 媒体服务器
# ---------------------------------------------------------------
echo "--- 🎬 媒体服务器 ---"
scan_service "_plex._tcp"       "Plex"
scan_service "_jellyfin._tcp"   "Jellyfin"

# ---------------------------------------------------------------
# 远程访问
# ---------------------------------------------------------------
echo "--- 🔗 远程访问 ---"
scan_service "_rfb._tcp"        "VNC 屏幕共享"
scan_service "_ssh._tcp"        "SSH"

echo "scan complete: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
