#!/usr/bin/env python3
"""
daily_top.py — 每日盘后Top榜（iFinD纯数据版）
不依赖Baostock历史K线，用iFinD实时数据直接筛选排序
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ifind_call import call


def get_market_data(min_amount=50000000, pct_min=-3, pct_max=10, limit=100):
    """iFinD市场扫描"""
    result = call('stock', 'search_stocks', {
        'query': f'主板 涨幅大于{pct_min} 涨幅小于{pct_max} 成交额大于{min_amount/10000:.0f}万',
        'limit': limit
    })
    
    content = result['data']['result']['content'][0]['text']
    data = json.loads(content)
    answer = json.loads(data['data'])['answer']
    
    stocks = []
    for line in answer.split('\n'):
        if line.startswith('|') and '股票代码' not in line and '---' not in line:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 5:
                try:
                    code = parts[0].replace('.SZ', '').replace('.SH', '')
                    name = parts[1]
                    board = parts[2]
                    pct_chg = float(parts[3])
                    amount = float(parts[4])
                    
                    if name.startswith('*ST') or name.startswith('ST'):
                        continue
                    if board != '主板':
                        continue
                        
                    stocks.append({
                        'code': code, 'name': name,
                        'pct_chg': pct_chg,
                        'amount': amount,
                    })
                except:
                    pass
    return stocks


def simple_score(s):
    """盘后简化评分（无历史K线）"""
    score = 0.0
    reasons = []
    
    pct = s['pct_chg']
    amount = s['amount']
    
    # 涨幅得分 (0-0.3)
    if 3 <= pct <= 5:
        score += 0.3
        reasons.append('涨幅3-5%(温和上涨)')
    elif 5 < pct <= 8:
        score += 0.25
        reasons.append('涨幅5-8%(偏强)')
    elif 1 <= pct < 3:
        score += 0.15
        reasons.append('涨幅1-3%(弱涨)')
    elif pct > 8:
        score += 0.1
        reasons.append('涨幅>8%(追高)')
    elif -3 <= pct < 0:
        score += 0.05
        reasons.append('微跌(可能低吸)')
    else:
        score -= 0.1
        reasons.append('跌幅过大')
    
    # 成交额得分 (0-0.3)
    if amount >= 500000000:  # 5亿
        score += 0.3
        reasons.append('成交>5亿(高活跃)')
    elif amount >= 100000000:  # 1亿
        score += 0.2
        reasons.append('成交>1亿(活跃)')
    elif amount >= 50000000:  # 5000万
        score += 0.1
        reasons.append('成交>5000万')
    
    # 量价齐升
    if pct > 3 and amount > 100000000:
        score += 0.2
        reasons.append('量价齐升')
    
    # 涨停排除
    if pct > 9.5:
        score -= 0.3
        reasons.append('涨停(无法买入)')
    
    s['score'] = score
    s['reasons'] = reasons
    
    if score >= 0.6:
        s['tier'] = 'A'
    elif score >= 0.4:
        s['tier'] = 'B'
    elif score >= 0.2:
        s['tier'] = 'C'
    else:
        s['tier'] = 'X'
    
    return s


def main():
    print("=" * 60)
    print(f"A股动量选股系统 v2.2 - 盘后Top榜 ({datetime.now().strftime('%Y-%m-%d')})")
    print("=" * 60)
    
    stocks = get_market_data()
    print(f"\niFinD扫描: {len(stocks)}只主板票")
    
    for s in stocks:
        simple_score(s)
    
    stocks.sort(key=lambda x: x['score'], reverse=True)
    
    # Top 20
    print("\n" + "=" * 60)
    print("📊 Top 20")
    print("=" * 60)
    print(f"{'排名':<4} {'代码':<8} {'名称':<10} {'评分':<8} {'等级':<4} {'涨幅%':<8} {'成交额':<10} {'理由'}")
    print("-" * 85)
    
    for i, s in enumerate(stocks[:20], 1):
        reason = s['reasons'][0] if s['reasons'] else ''
        if len(reason) > 20:
            reason = reason[:17] + '...'
        amount_wan = s['amount'] / 10000
        print(f"{i:<4} {s['code']:<8} {s['name']:<10} {s['score']:<8.2f} {s['tier']:<4} {s['pct_chg']:<8.2f} {amount_wan:>8.0f}万 {reason}")
    
    # A/B级买入建议
    print("\n" + "=" * 60)
    print("💡 A/B级关注")
    print("=" * 60)
    buy_list = [s for s in stocks if s['tier'] in ['A', 'B']][:10]
    if buy_list:
        for i, s in enumerate(buy_list, 1):
            print(f"{i}. {s['code']} {s['name']} | {s['tier']}级 | +{s['pct_chg']:.2f}% | {s['reasons'][0]}")
    else:
        print("⚠️ 无A/B级标的，建议观望")
    
    print("\n" + "=" * 60)
    print("⚠️ 说明: Baostock被封，本榜仅用iFinD实时数据，缺少20日K线指标")
    print("=" * 60)


if __name__ == '__main__':
    main()
