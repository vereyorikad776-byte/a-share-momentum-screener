#!/bin/bash
# run_intraday.sh - 盘中扫描入口脚本
#
# 用法:
#   bash run_intraday.sh              # 手动运行
#   bash run_intraday.sh --notify     # 扫描后推送微信
#
# 定时任务设置:
#   crontab -e
#   0 10,11 * * 1-5 bash /root/.openclaw/workspace/skills/ifind-momentum-screener/scripts/run_intraday.sh
#   30 13,14 * * 1-5 bash /root/.openclaw/workspace/skills/ifind-momentum-screener/scripts/run_intraday.sh

set -e

cd /root/.openclaw/workspace/skills/ifind-momentum-screener/scripts

echo "========================================"
echo "📊 A股动量选股 - 盘中扫描"
echo "时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"

# 运行盘中扫描
python3 intraday_scan_live.py 2>&1 | tee /tmp/intraday_scan_$(date +%H%M).log

echo ""
echo "========================================"
echo "扫描完成"
echo "========================================"

# 如果有 --notify 参数，推送微信（需手动配置）
if [ "$1" = "--notify" ]; then
    echo "推送功能待配置..."
fi
