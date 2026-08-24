#!/bin/bash
# ========================================
# 增强监控 - Linux适配版
# ========================================
# 功能：监控记忆系统健康状态
# 频率：每 4 小时
# ========================================

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
LOG_DIR="$WORKSPACE/humanbrain-claw/logs"
REPORT_DIR="$WORKSPACE/humanbrain-claw/reports"

mkdir -p "$LOG_DIR" "$REPORT_DIR"

LOG_FILE="$LOG_DIR/monitor-$(date +%Y%m%d-%H%M%S).log"
STATUS_FILE="$REPORT_DIR/latest-status.json"

echo "📊 [$(date '+%Y-%m-%d %H:%M:%S')] 增强监控开始" | tee -a "$LOG_FILE"

# 收集指标
MEMORY_SIZE=$(test -f "$WORKSPACE/MEMORY.md" && wc -c < "$WORKSPACE/MEMORY.md" || echo "0")
MEMORY_FILES=$(find "$WORKSPACE/memory" -name "*.md" 2>/dev/null | wc -l)
ARCHIVE_FILES=$(find "$WORKSPACE/humanbrain-claw/archives" -name "*.md" 2>/dev/null | wc -l)
M1_FILES=$(find "$WORKSPACE/humanbrain-claw/m1" -name "*.md" 2>/dev/null | wc -l)
M2_FILES=$(find "$WORKSPACE/humanbrain-claw/m2" -name "*.md" 2>/dev/null | wc -l)
LOG_COUNT=$(find "$LOG_DIR" -name "*.log" 2>/dev/null | wc -l)

# 计算健康评分 (0-100)
HEALTH=100
if [ "$MEMORY_SIZE" -gt 5000 ]; then
    HEALTH=$((HEALTH - 20))
fi
if [ "$LOG_COUNT" -gt 50 ]; then
    HEALTH=$((HEALTH - 10))
fi
if [ "$ARCHIVE_FILES" -gt 100 ]; then
    HEALTH=$((HEALTH - 10))
fi

# 输出状态
echo "📈 系统指标:" | tee -a "$LOG_FILE"
echo "  MEMORY.md: ${MEMORY_SIZE} 字节" | tee -a "$LOG_FILE"
echo "  记忆文件: $MEMORY_FILES 个" | tee -a "$LOG_FILE"
echo "  归档文件: $ARCHIVE_FILES 个" | tee -a "$LOG_FILE"
echo "  m1 摘要: $M1_FILES 个" | tee -a "$LOG_FILE"
echo "  m2 摘要: $M2_FILES 个" | tee -a "$LOG_FILE"
echo "  日志文件: $LOG_COUNT 个" | tee -a "$LOG_FILE"
echo "  健康评分: $HEALTH/100" | tee -a "$LOG_FILE"

# 保存JSON状态
cat > "$STATUS_FILE" << EOF
{
  "timestamp": "$(date -Iseconds)",
  "health_score": $HEALTH,
  "memory_md_size": $MEMORY_SIZE,
  "memory_files": $MEMORY_FILES,
  "archive_files": $ARCHIVE_FILES,
  "m1_count": $M1_FILES,
  "m2_count": $M2_FILES,
  "log_count": $LOG_COUNT
}
EOF

echo "✅ 状态已保存: $STATUS_FILE" | tee -a "$LOG_FILE"

# 健康告警
if [ "$HEALTH" -lt 80 ]; then
    echo "⚠️ 健康评分较低 (${HEALTH})，建议维护" | tee -a "$LOG_FILE"
fi

echo "🎉 [$(date '+%Y-%m-%d %H:%M:%S')] 监控完成" | tee -a "$LOG_FILE"
