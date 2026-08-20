#!/usr/bin/env python3
"""
选股策略 Jupyter 探索脚本
用法: python3 strategy_explorer.py
功能: 数据探索、回测可视化、策略参数调优
"""

import sys, json, os
from datetime import datetime
import pandas as pd
import numpy as np

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

# ═══════════════════════════════════════════════════════════════
# Cell 1: 加载数据
# ═══════════════════════════════════════════════════════════════
print("=" * 80)
print("📊 选股策略 Jupyter 探索器")
print("=" * 80)

# 加载昨晚的157只评分结果
result_file = '/tmp/scan_157_full_result.json'
if os.path.exists(result_file):
    with open(result_file, 'r', encoding='utf-8') as f:
        results = json.load(f)
    df = pd.DataFrame(results)
    print(f"\n✅ 加载 {len(df)} 只票的评分数据")
else:
    print(f"❌ 未找到 {result_file}")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════════
# Cell 2: 数据概览
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("📈 数据概览")
print("=" * 80)

print(f"\n总票数: {len(df)}")
print(f"Tier分布:")
for tier in ['S', 'A', 'B', 'X']:
    count = len(df[df['tier'] == tier])
    print(f"  {tier}: {count}只")

print(f"\n分数统计:")
print(f"  最高分: {df['final_score'].max():.2f}")
print(f"  最低分: {df['final_score'].min():.2f}")
print(f"  平均分: {df['final_score'].mean():.2f}")
print(f"  中位数: {df['final_score'].median():.2f}")

# ═══════════════════════════════════════════════════════════════
# Cell 3: 过夜分 vs 融合分 散点图（文本版）
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("🎯 过夜分 vs 融合分 分布")
print("=" * 80)

# 分箱统计
overnight_bins = pd.cut(df['overnight_score'], bins=[0, 5, 8, 10, 12, 20], labels=['0-5', '5-8', '8-10', '10-12', '12+'])
fusion_bins = pd.cut(df['fusion_score'], bins=[0, 3, 5, 7, 10], labels=['0-3', '3-5', '5-7', '7+'])

crosstab = pd.crosstab(overnight_bins, fusion_bins)
print("\n" + crosstab.to_string())

# 高过夜分 + 高融合分的票（黄金区域）
gold = df[(df['overnight_score'] >= 10) & (df['fusion_score'] >= 6)]
print(f"\n⭐ 黄金区域票（过夜≥10 & 融合≥6）: {len(gold)}只")
for _, r in gold.head(10).iterrows():
    print(f"  {r['code']} {r['name']} | 过夜{r['overnight_score']:.0f} 融合{r['fusion_score']:.0f} | {r.get('change_pct', 0):+.1f}%")

# ═══════════════════════════════════════════════════════════════
# Cell 4: 战法统计
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("⚔️ 战法命中统计")
print("=" * 80)

tactic_df = df[df['tactic_score'] > 0]
print(f"\n战法命中: {len(tactic_df)}只")

# 统计各战法
all_tactics = []
for tactics in tactic_df['tactic_names']:
    if isinstance(tactics, list):
        all_tactics.extend(tactics)

tactic_counts = pd.Series(all_tactics).value_counts()
print("\n战法分布:")
for tactic, count in tactic_counts.items():
    print(f"  {tactic}: {count}只")

# ═══════════════════════════════════════════════════════════════
# Cell 5: 板块分布
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("🏷️ 板块分布（Top 15）")
print("=" * 80)

all_sectors = []
for sectors in df['sectors']:
    if isinstance(sectors, list):
        all_sectors.extend(sectors)

sector_counts = pd.Series(all_sectors).value_counts().head(15)
print()
for sector, count in sector_counts.items():
    bar = "█" * count
    print(f"  {sector:12s} {bar} ({count})")

# ═══════════════════════════════════════════════════════════════
# Cell 6: 涨幅分布
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("📉 涨跌幅分布")
print("=" * 80)

change_bins = pd.cut(df['change_pct'], bins=[-20, -5, 0, 2, 5, 10, 30], labels=['大跌<-5%', '-5~0%', '0~2%', '2~5%', '5~10%', '涨停>10%'])
print("\n" + change_bins.value_counts().sort_index().to_string())

# ═══════════════════════════════════════════════════════════════
# Cell 7: Top 20 推荐清单
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("🏆 Top 20 推荐清单")
print("=" * 80)

top20 = df.nlargest(20, 'final_score')[['code', 'name', 'tier', 'final_score', 'overnight_score', 'fusion_score', 'change_pct', 'tactic_names']]
print()
print(top20.to_string(index=False))

# ═══════════════════════════════════════════════════════════════
# Cell 8: 策略参数敏感性分析
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("🔬 策略参数敏感性分析")
print("=" * 80)

# 测试不同过夜分阈值下的A级票数量
print("\n过夜分阈值 vs A级票数量:")
for threshold in [8, 9, 10, 11, 12]:
    a_count = len(df[(df['overnight_score'] >= threshold) & (df['tier'] == 'A')])
    total = len(df[df['overnight_score'] >= threshold])
    print(f"  过夜分≥{threshold}: A级{a_count}只 / 总计{total}只")

# 测试不同融合分阈值
print("\n融合分阈值 vs A级票数量:")
for threshold in [5, 6, 7, 8]:
    a_count = len(df[(df['fusion_score'] >= threshold) & (df['tier'] == 'A')])
    total = len(df[df['fusion_score'] >= threshold])
    print(f"  融合分≥{threshold}: A级{a_count}只 / 总计{total}只")

# ═══════════════════════════════════════════════════════════════
# Cell 9: 导出建议
# ═══════════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("💾 导出结果")
print("=" * 80)

# 导出黄金区域票
if len(gold) > 0:
    gold_file = '/tmp/gold_zone_stocks.csv'
    gold[['code', 'name', 'tier', 'final_score', 'overnight_score', 'fusion_score', 'change_pct', 'sectors']].to_csv(gold_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 黄金区域票已导出: {gold_file} ({len(gold)}只)")

# 导出Top 20
top20_file = '/tmp/top20_stocks.csv'
top20.to_csv(top20_file, index=False, encoding='utf-8-sig')
print(f"✅ Top 20已导出: {top20_file}")

print("\n" + "=" * 80)
print("🎉 探索完成！")
print("=" * 80)
