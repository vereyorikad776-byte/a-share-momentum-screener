#!/bin/bash
# ========================================
# 夜间深度分析 - Linux适配版
# ========================================
# 功能：每日凌晨分析记忆，生成洞察报告
# 频率：每天 03:00
# ========================================

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
LOG_DIR="$WORKSPACE/humanbrain-claw/logs"
REPORT_DIR="$WORKSPACE/humanbrain-claw/reports"
MEMORY_DIR="$WORKSPACE/memory"

mkdir -p "$LOG_DIR" "$REPORT_DIR"

LOG_FILE="$LOG_DIR/nightly-$(date +%Y%m%d).log"
REPORT_FILE="$REPORT_DIR/daily-report-$(date +%Y%m%d).md"

echo "🌙 [$(date '+%Y-%m-%d %H:%M:%S')] 夜间深度分析开始" | tee -a "$LOG_FILE"

# 1. 统计过去24小时的记忆
echo "📊 [1/3] 统计记忆数据..." | tee -a "$LOG_FILE"
YESTERDAY=$(date -d "yesterday" +%Y-%m-%d 2>/dev/null || date -v-1d +%Y-%m-%d 2>/dev/null || echo "unknown")
YESTERDAY_FILE="$MEMORY_DIR/$YESTERDAY.md"

TOTAL_LINES=0
TOTAL_FILES=0
for f in "$MEMORY_DIR"/2026-*.md; do
    [ -f "$f" ] || continue
    LINES=$(wc -l < "$f")
    TOTAL_LINES=$((TOTAL_LINES + LINES))
    TOTAL_FILES=$((TOTAL_FILES + 1))
done

echo "   记忆文件: $TOTAL_FILES 个" | tee -a "$LOG_FILE"
echo "   总行数: $TOTAL_LINES 行" | tee -a "$LOG_FILE"

# 2. 生成日报
echo "📝 [2/3] 生成分析报告..." | tee -a "$LOG_FILE"

cat > "$REPORT_FILE" << EOF
# 记忆日报 - $(date +%Y-%m-%d)

## 统计概览
- **分析时间**: $(date '+%Y-%m-%d %H:%M:%S')
- **记忆文件**: $TOTAL_FILES 个
- **总行数**: $TOTAL_LINES 行
- **昨日文件**: $(test -f "$YESTERDAY_FILE" && echo "$YESTERDAY_FILE" || echo "无")

## 记忆活跃度
EOF

if [ -f "$YESTERDAY_FILE" ]; then
    Y_LINES=$(wc -l < "$YESTERDAY_FILE")
    echo "- **昨日记录**: $Y_LINES 行" >> "$REPORT_FILE"
else
    echo "- **昨日记录**: 无" >> "$REPORT_FILE"
fi

cat >> "$REPORT_FILE" << EOF

## 系统状态
- MEMORY.md 存在: $(test -f "$WORKSPACE/MEMORY.md" && echo "✅" || echo "❌")
- 今日记忆: $(test -f "$MEMORY_DIR/$(date +%Y-%m-%d).md" && echo "✅" || echo "❌")

## 建议
- 定期回顾 MEMORY.md，更新长期记忆
- 清理不再相关的归档文件
- 保持每日记忆记录习惯
EOF

echo "✅ 报告生成: $REPORT_FILE" | tee -a "$LOG_FILE"

# 3. 清理旧报告（保留30天）
echo "🧹 [3/3] 清理旧报告..." | tee -a "$LOG_FILE"
find "$REPORT_DIR" -name "daily-report-*.md" -mtime +30 -delete 2>/dev/null || true
echo "✅ 清理完成" | tee -a "$LOG_FILE"

echo "🎉 [$(date '+%Y-%m-%d %H:%M:%S')] 夜间分析完成" | tee -a "$LOG_FILE"
echo "📄 报告: $REPORT_FILE" | tee -a "$LOG_FILE"
