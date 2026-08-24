#!/bin/bash
# ========================================
# 记忆系统维护 - Linux适配版
# ========================================
# 功能：记忆衰减 + 归档 + 检查点
# 频率：每 6 小时
# ========================================

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
LOG_DIR="$WORKSPACE/humanbrain-claw/logs"
ARCHIVE_DIR="$WORKSPACE/humanbrain-claw/archives"
MEMORY_DIR="$WORKSPACE/memory"

mkdir -p "$LOG_DIR" "$ARCHIVE_DIR" "$MEMORY_DIR"

LOG_FILE="$LOG_DIR/maintenance-$(date +%Y%m%d-%H%M%S).log"

echo "🔧 [$(date '+%Y-%m-%d %H:%M:%S')] 记忆系统维护开始" | tee -a "$LOG_FILE"

# 1. 清理旧日志（保留7天）
echo "🧹 [1/4] 清理旧日志..." | tee -a "$LOG_FILE"
find "$LOG_DIR" -name "*.log" -mtime +7 -delete 2>/dev/null || true
echo "✅ 日志清理完成" | tee -a "$LOG_FILE"

# 2. 归档老旧记忆文件（7天前的移到archives）
echo "📦 [2/4] 归档老旧记忆..." | tee -a "$LOG_FILE"
find "$MEMORY_DIR" -name "2026-*.md" -mtime +7 -exec mv {} "$ARCHIVE_DIR/" \; 2>/dev/null || true
echo "✅ 归档完成" | tee -a "$LOG_FILE"

# 3. 检查 MEMORY.md 大小（超过 5000 字符则提醒压缩）
echo "📏 [3/4] 检查 MEMORY.md 大小..." | tee -a "$LOG_FILE"
if [ -f "$WORKSPACE/MEMORY.md" ]; then
    SIZE=$(wc -c < "$WORKSPACE/MEMORY.md")
    if [ "$SIZE" -gt 5000 ]; then
        echo "⚠️ MEMORY.md 过大 (${SIZE} 字节)，建议压缩" | tee -a "$LOG_FILE"
    else
        echo "✅ MEMORY.md 大小正常 (${SIZE} 字节)" | tee -a "$LOG_FILE"
    fi
fi

# 4. 统计今日记忆
echo "📊 [4/4] 统计记忆状态..." | tee -a "$LOG_FILE"
TODAY=$(date +%Y-%m-%d)
TODAY_FILE="$MEMORY_DIR/$TODAY.md"
if [ -f "$TODAY_FILE" ]; then
    LINES=$(wc -l < "$TODAY_FILE")
    echo "✅ 今日记忆: $LINES 行" | tee -a "$LOG_FILE"
else
    echo "⚠️ 今日尚无记忆记录" | tee -a "$LOG_FILE"
fi

ARCHIVE_COUNT=$(ls -1 "$ARCHIVE_DIR" 2>/dev/null | wc -l)
echo "📁 归档文件: $ARCHIVE_COUNT 个" | tee -a "$LOG_FILE"

echo "🎉 [$(date '+%Y-%m-%d %H:%M:%S')] 记忆系统维护完成" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "📊 维护摘要:" | tee -a "$LOG_FILE"
echo "  日志文件：$LOG_FILE" | tee -a "$LOG_FILE"
echo "  状态：成功" | tee -a "$LOG_FILE"
