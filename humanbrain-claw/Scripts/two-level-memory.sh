#!/bin/bash
# ========================================
# 两级摘要系统 - Linux适配版
# ========================================
# 功能：m1任务摘要 → m2宏观摘要
# 阈值：10个m1触发m2
# ========================================

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
M1_DIR="$WORKSPACE/humanbrain-claw/m1"
M2_DIR="$WORKSPACE/humanbrain-claw/m2"
LOG_DIR="$WORKSPACE/humanbrain-claw/logs"

mkdir -p "$M1_DIR" "$M2_DIR" "$LOG_DIR"

LOG_FILE="$LOG_DIR/two-level-$(date +%Y%m%d-%H%M%S).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# 命令: generate-m1 <task_id> <task_desc> <content>
generate_m1() {
    local task_id="${1:-unknown}"
    local task_desc="${2:-unknown}"
    local content="${3:-}"
    
    local m1_file="$M1_DIR/m1-$(date +%Y%m%d-%H%M%S)-$task_id.md"
    
    cat > "$m1_file" << EOF
# m1 摘要 - $task_id
- **时间**: $(date '+%Y-%m-%d %H:%M:%S')
- **任务**: $task_desc
- **内容**: $content
EOF
    log "✅ 生成 m1: $(basename "$m1_file")"
    
    # 检查是否达到m2阈值
    check_m2_threshold
}

# 检查m2触发条件
check_m2_threshold() {
    local m1_count=$(ls -1 "$M1_DIR"/*.md 2>/dev/null | wc -l)
    log "📊 当前 m1 数量: $m1_count"
    
    if [ "$m1_count" -ge 10 ]; then
        log "🚀 触发 m2 生成（$m1_count 个m1）"
        generate_m2
    fi
}

# 生成m2宏观摘要
generate_m2() {
    local m2_file="$M2_DIR/m2-$(date +%Y%m%d-%H%M%S).md"
    
    cat > "$m2_file" << EOF
# m2 宏观摘要
- **生成时间**: $(date '+%Y-%m-%d %H:%M:%S')
- **包含m1数**: $(ls -1 "$M1_DIR"/*.md 2>/dev/null | wc -l)

## 近期任务概览
EOF
    
    # 列出所有m1
    for f in "$M1_DIR"/*.md; do
        [ -f "$f" ] || continue
        echo "- $(basename "$f")" >> "$m2_file"
    done
    
    # 清空m1（已归档到m2）
    mkdir -p "$M1_DIR/archive-$(date +%Y%m%d)"
    mv "$M1_DIR"/m1-*.md "$M1_DIR/archive-$(date +%Y%m%d)/" 2>/dev/null || true
    
    log "✅ 生成 m2: $(basename "$m2_file")，已归档 m1"
}

# 状态报告
status() {
    local m1_count=$(ls -1 "$M1_DIR"/*.md 2>/dev/null | wc -l)
    local m2_count=$(ls -1 "$M2_DIR"/*.md 2>/dev/null | wc -l)
    
    echo "=== 两级摘要系统状态 ==="
    echo "m1 数量: $m1_count (阈值: 10)"
    echo "m2 数量: $m2_count"
    echo "日志目录: $LOG_DIR"
}

# 主入口
case "${1:-status}" in
    generate-m1)
        if [ $# -lt 3 ]; then
            echo "用法: $0 generate-m1 <task_id> <task_desc> [content]"
            exit 1
        fi
        generate_m1 "$2" "$3" "${4:-}"
        ;;
    generate-m2)
        generate_m2
        ;;
    status)
        status
        ;;
    *)
        echo "用法: $0 {generate-m1|generate-m2|status}"
        exit 1
        ;;
esac
