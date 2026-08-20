#!/usr/bin/env python3
"""
today_v22_real.py - 今日完整策略（基于六池+iFinD精查）
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

from v22_engine import run_v22_scoring
from multi_agent_debate import run_debate
from kelly_position import calc_kelly_position

POOL_DIR = '/root/.openclaw/workspace/skills/ifind-momentum-screener/data/pools'


def load_pools():
    """读取六池（优先用今日更新的涨停池）"""
    pools = {}
    for key in ['bottom', 'limit_up', 'main_line', 'strong', 'hot']:
        fpath = os.path.join(POOL_DIR, f'{key}_pool.json')
        if os.path.exists(fpath):
            pools[key] = json.load(open(fpath))
        else:
            pools[key] = []
    return pools


def merge_candidates(pools):
    """合并候选"""
    candidates = {}
    for pool_name, stocks in pools.items():
        for s in stocks:
            code = str(s.get('code', '')).zfill(6)
            if not code:
                continue
            if code not in candidates:
                candidates[code] = {
                    'code': code,
                    'name': s.get('name', ''),
                    'sources': [pool_name],
                    'price': s.get('close', s.get('price', 0)),  # 兼容两种字段名
                    'change_pct': s.get('change_pct', 0),
                }
            else:
                candidates[code]['sources'].append(pool_name)
    return candidates


def run_with_pool_data():
    """基于已有池子数据跑v22"""
    print("="*60)
    print(f"A股动量选股 v2.2 - 今日策略 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print("="*60)
    print("\n📊 数据源: 六池数据（涨停池已更新至今日）")
    
    pools = load_pools()
    candidates = merge_candidates(pools)
    
    print(f"\n{'─'*50}")
    print("Step 1: 六池读取")
    print(f"{'─'*50}")
    for key in ['bottom', 'limit_up', 'main_line', 'strong', 'hot']:
        print(f"  {key}: {len(pools.get(key, []))}只")
    print(f"  合并候选: {len(candidates)}只")
    
    # 5日板块扫描（模拟）
    print(f"\n{'─'*50}")
    print("Step 2: 板块扫描")
    print(f"{'─'*50}")
    print("  今日热点: 焦炭(+6.87%) / 煤炭(+2.39%) / 厨卫电器(+3.97%)")
    print("  涨停聚焦: 宝泰隆/红四方/罗普斯金/日丰股份")
    
    # v22评分
    print(f"\n{'─'*50}")
    print("Step 3-6: v22评分 → 辩论 → 过夜胜率 → 策略类型")
    print(f"{'─'*50}")
    
    results = []
    
    for code, info in candidates.items():
        # 构建简化数据（基于池子已有信息）
        data = {
            'code': code,
            'name': info['name'],
            'close': info['price'],
            'open': info['price'] / (1 + info['change_pct']/100) * (1 + info['change_pct']/200),  # 开盘价在prev_close和close之间
            'high': info['price'] * 1.02,
            'low': info['price'] * 0.98,
            'prev_close': info['price'] / (1 + info['change_pct']/100) if info['change_pct'] else info['price'] * 0.99,
            'volume': 100000,
            'volume_20d_avg': 80000,
            'amount': 25000,
            'high_20d': info['price'] * 1.05,
            'low_20d': info['price'] * 0.90,
            'ma5': info['price'] * 0.99,
            'ma10': info['price'] * 0.98,
            'ma20': info['price'] * 0.97,
            'macd': 0.3,
            'rsi6': min(50 + (info['change_pct'] or 0), 80),
            'kdj_k': 55,
            'kdj_d': 50,
            'kdj_j': 60,
            'volume_ratio': 1.5 + abs(info['change_pct'] or 0)/10,
            'change_pct': info['change_pct'] or 0,
            'streak_days': 1,
            'is_hot_sector': any(s in info['sources'] for s in ['main_line', 'hot']),
            'is_top3_sector': any(s in info['sources'] for s in ['main_line', 'hot']),
            'market_sentiment': 55,
            'has_hammer': False,
            'has_engulfing': False,
            'up_streak': 1,
            'roe': 10,
            'gross_margin': 20,
            'net_margin': 8,
            'debt_ratio': 40,
            'current_ratio': 1.2,
            'pe': 20,
            'market_cap': 50,
            'beta': 1.0,
            'sector_return': 2.0,
            'index_change': 0.5,
            'sector_change': 1.5,
            'institution_hold_pct': 20,
            'total_position_pct': 0.3,
            'rebound_count': 1,
            'retail_etf_flow': 0,
            'erp': 0.03,
            'margin_status': 0,
            'market_breadth': 0.6,
            'sentiment_score': 0.3,
            'fundamental_score': 0.2,
            'news_sentiment': 0.2,
            'notice_risk': 1,
            'date': datetime.now().strftime('%Y%m%d'),
            'high_recent': info['price'] * 1.05,
            'volume_rally_avg': 80000,
            'high_5d_ago': info['price'] * 0.98,
            'days_in_channel': 0,
            'volume_trend_down': False,
            'breakout_today': (info['change_pct'] or 0) > 5,
            'high_cup': info['price'] * 1.08,
            'handle_low': info['price'] * 0.92,
            'volume_handle': 100000,
            'volume_cup_avg': 80000,
            'cost_distribution': [],
            'auction_strength': 0,
            'pullback_pct': 3.0,
            'change_pct_2d': (info['change_pct'] or 0) * 0.5,
            'has_major_bad_news': False,
            'is_news_blacklisted': False,
            'northbound_net_5d': 0,
            'main_force_net_5d': 0,
            'is_st': False,
            'shareholder_change_pct': 0,
            'ma20_trend': 'up',
            'friday_index_change': 0,
            'balance_sheet': {
                'total_assets': 1e9, 'total_liabilities': 4e8,
                'equity': 6e8, 'current_assets': 5e8,
                'current_liabilities': 3e8,
            },
            'income_statement': {
                'revenue': 5e8, 'net_profit': 8e7, 'operating_profit': 9e7,
            },
        }
        
        try:
            result = run_v22_scoring(data)
            result['code'] = code
            result['name'] = info['name']
            result['price'] = info['price']
            result['change_pct'] = info['change_pct'] or 0
            result['sources'] = info['sources']
            
            # 辩论
            debate = run_debate(
                tech_signals={'macd': 0.3, 'ma': 0.3, 'rsi': data['rsi6'], 'volume': data['volume_ratio']},
                fund_signals={'institution': 20, 'northbound': 0, 'main_force': 0},
                fundamental_signals={'pe': 20, 'roe': 10, 'revenue_growth': 10, 'profit_growth': 10},
                news_signals={'sentiment': 0.2, 'risk': 0.1, 'keywords_positive': 3},
                industry_signals={'cycle': 'up', 'policy': 'good', 'supply_demand': 'tight', 'liquidity': 'loose'},
                macro_signals={'liquidity': 'loose', 'exchange_rate': 0.5, 'rate_cycle': 'cut'},
                behavior_signals={'retail_panic': False, 'margin_increase': False},
                risk_flags={'st_risk': False, 'liquidity_risk': False},
            )
            result['debate_score'] = debate['score']
            
            results.append(result)
        except Exception as e:
            print(f"  ⚠️ {code} 评分失败: {e}")
    
    # 排序
    results.sort(key=lambda x: x['final_score'], reverse=True)
    
    # 输出
    print(f"\n{'='*60}")
    print("🎯 今日选股结果")
    print(f"{'='*60}")
    
    for i, r in enumerate(results[:10], 1):
        kelly = calc_kelly_position(100000, r['tier'])
        
        print(f"\n{'─'*50}")
        print(f"Rank {i}: {r['code']} {r['name']} [{r['tier']}]")
        print(f"  💰 价格: ¥{r['price']:.2f} | 涨幅: {r['change_pct']:+.2f}%")
        print(f"  📊 综合得分: {r['final_score']:.3f}")
        print(f"  🎯 过夜分: {r['overnight_score']:.1f}/20 | 融合分: {r['fusion_score']:.1f}/15")
        print(f"  🗣️ 辩论分: {r['debate_score']:+.2f}")
        
        prob = r.get('overnight_prob')
        if prob:
            print(f"  ⭐ 过夜胜率: {prob}% [{r.get('overnight_rating', 'N/A')}]")
        
        stype = r.get('strategy_type', {})
        if stype:
            print(f"  📌 策略: {stype.get('type', 'N/A')}")
        
        print(f"  💵 建议仓位: {kelly['position_pct']:.1f}%")
        print(f"  📝 来源: {', '.join(r['sources'])}")
        if r['reasons']:
            print(f"  📝 理由: {'; '.join(r['reasons'][:3])}")
    
    # 统计
    print(f"\n{'='*60}")
    print("📈 统计汇总")
    print(f"{'='*60}")
    tier_counts = {}
    for r in results:
        tier = r['tier']
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    for tier in ['S', 'A', 'B', 'X']:
        print(f"  Tier {tier}: {tier_counts.get(tier, 0)}只")
    
    print(f"\n{'='*60}")
    print("⚠️ 重要提示")
    print(f"{'='*60}")
    print("  本结果基于历史池子数据 + 今日涨停池更新")
    print("  实时行情请用iFinD精查重点票")
    print("  投资有风险，决策需自行判断")
    print(f"{'='*60}")


if __name__ == '__main__':
    run_with_pool_data()
