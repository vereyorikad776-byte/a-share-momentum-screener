#!/bin/bash
# ========================================
# 预压缩钩子 - Linux适配版
# ========================================
# 功能：监控上下文使用率，触发压缩
# 阈值：MEMORY.md > 3000 字符
# ========================================

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
LOG_DIR="$WORKSPACE/humanbrain-claw/logs"

mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/compression-$(date +%Y%m%d-%H%M%S).log"

echo "🪝 [$(date '+%Y-%m-%d %H:%M:%S')] 预压缩检查开始" | tee -a "$LOG_FILE"

# 检查 MEMORY.md 大小
MEMORY_FILE="$WORKSPACE/MEMORY.md"
if [ -f "$MEMORY_FILE" ]; then
    SIZE=$(wc -c < "$MEMORY_FILE")
    echo "📏 MEMORY.md 大小: ${SIZE} 字节" | tee -a "$LOG_FILE"
    
    if [ "$SIZE" -gt 3000 ]; then
        echo "⚠️ 超过阈值 (3000)，建议压缩或归档旧内容" | tee -a "$LOG_FILE"
        
        # 自动归档旧内容到 archives
        ARCHIVE_DIR="$WORKSPACE/humanbrain-claw/archives"
        mkdir -p "$ARCHIVE_DIR"
        
        # 提取旧内容（简单策略：保留前30行作为核心，其余归档）
        if [ "$SIZE" -gt 5000 ]; then
            BACKUP_FILE="$ARCHIVE_DIR/memory-backup-$(date +%Y%m%d-%H%M%S).md"
            tail -n +31 "$MEMORY_FILE" > "$BACKUP_FILE"
            head -n 30 "$MEMORY_FILE" > "$MEMORY_FILE.tmp"
            mv "$MEMORY_FILE.tmp" "$MEMORY_FILE"
            echo "✅ 已自动归档旧内容到: $BACKUP_FILE" | tee -a "$LOG_FILE"
        fi
    else
        echo "✅ 大小正常，无需压缩" | tee -a "$LOG_FILE"
    fi
else
    echo "⚠️ MEMORY.md 不存在" | tee -a "$LOG_FILE"
fi

# 检查 memory/ 目录总大小
MEMORY_DIR="$WORKSPACE/memory"
if [ -d "$MEMORY_DIR" ]; then
    DIR_SIZE=$(du -sb "$MEMORY_DIR" 2>/dev/null | cut -f1)
    FILE_COUNT=$(find "$MEMORY_DIR" -name "*.md" 2>/dev/null | wc -l)
    echo "📁 memory/ 目录: ${FILE_COUNT} 个文件, ${DIR_SIZE} 字节" | tee -a "$LOG_FILE"
fi

echo "🎉 [$(date '+%Y-%m-%d %H:%M:%S')] 预压缩检查完成" | tee -a "$LOG_FILE"
