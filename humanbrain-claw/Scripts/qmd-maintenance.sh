#!/bin/bash
# ========================================
# QMD维护替代 - Linux适配版
# ========================================
# 功能：文件索引维护（qmd不可用时用find替代）
# 频率：每天 06:00
# ========================================

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
LOG_DIR="$WORKSPACE/humanbrain-claw/logs"
INDEX_DIR="$WORKSPACE/humanbrain-claw/index"

mkdir -p "$LOG_DIR" "$INDEX_DIR"

LOG_FILE="$LOG_DIR/qmd-$(date +%Y%m%d).log"
INDEX_FILE="$INDEX_DIR/file-index-$(date +%Y%m%d).txt"

echo "🔍 [$(date '+%Y-%m-%d %H:%M:%S')] 文件索引维护开始" | tee -a "$LOG_FILE"

# 生成文件索引（qmd不可用，用find+grep替代）
echo "📝 生成文件索引..." | tee -a "$LOG_FILE"

# 索引所有md文件
echo "# 文件索引 - $(date +%Y-%m-%d)" > "$INDEX_FILE"
echo "" >> "$INDEX_FILE"

# memory/ 目录
echo "## memory/ 目录" >> "$INDEX_FILE"
find "$WORKSPACE/memory" -name "*.md" -type f 2>/dev/null | sort >> "$INDEX_FILE" || echo "(空)" >> "$INDEX_FILE"

# 技能目录
echo "" >> "$INDEX_FILE"
echo "## skills/ 目录" >> "$INDEX_FILE"
find "$WORKSPACE/skills" -name "*.md" -o -name "*.py" 2>/dev/null | sort >> "$INDEX_FILE" || echo "(空)" >> "$INDEX_FILE"

# MEMORY.md
echo "" >> "$INDEX_FILE"
echo "## 核心文件" >> "$INDEX_FILE"
echo "$WORKSPACE/MEMORY.md" >> "$INDEX_FILE"
echo "$WORKSPACE/USER.md" >> "$INDEX_FILE"
echo "$WORKSPACE/SOUL.md" >> "$INDEX_FILE"
echo "$WORKSPACE/AGENTS.md" >> "$INDEX_FILE"

FILE_COUNT=$(wc -l < "$INDEX_FILE")
echo "✅ 索引完成: $FILE_COUNT 行, 保存到 $INDEX_FILE" | tee -a "$LOG_FILE"

# 清理旧索引
find "$INDEX_DIR" -name "file-index-*.txt" -mtime +7 -delete 2>/dev/null || true
echo "🧹 清理旧索引完成" | tee -a "$LOG_FILE"

echo "🎉 [$(date '+%Y-%m-%d %H:%M:%S')] 索引维护完成" | tee -a "$LOG_FILE"
