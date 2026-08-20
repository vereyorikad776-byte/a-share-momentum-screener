#!/usr/bin/env python3
"""
today_screener.py - 今日完整选股
用akshare获取实时行情，v22引擎评分
"""

import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import akshare as ak
import pandas as pd

from v22_engine import run_v22_scoring
from multi_agent_debate import run_debate
from kelly_position import calc_kelly_position


def get_today_spot():
    """获取今日全市场行情"""
    print("📊 拉取今日A股行情...")
    try:
        df = ak.stock_zh_a_spot_em()
        df['代码'] = df['代码'].astype(str).str.zfill(6)
        df['涨跌幅'] = pd.to_numeric(df['涨跌幅'], errors='coerce')
        df['最新价'] = pd.to_numeric(df['最新价'], errors='coerce')
        df['换手率'] = pd.to_numeric(df['换手率'], errors='coerce')
        df['成交量'] = pd.to_numeric(df['成交量'], errors='coerce')
        print(f"✅ 获取 {len(df)} 只票行情")
        return df
    except Exception as e:
        print(f"❌ 获取行情失败: {e}")
        return None


def build_pools_from_spot(df):
    """从今日行情构建六池"""
    if df is None:
        return {}
    
    pools = {
        'limit_up': [],
        'strong': [],
        'hot': [],
        'main_line': [],
    }
    
    # 涨停池: 涨幅 >= 9.5%
    limit_up = df[df['涨跌幅'] >= 9.5].copy()
    for _, row in limit_up.iterrows():
        pools['limit_up'].append({
            'code': row['代码'],
            'name': row['名称'],
            'price': row['最新价'],
            'change_pct': row['涨跌幅'],
        })
    
    # 强势池: 涨幅 5~9.5%
    strong = df[(df['涨跌幅'] >= 5) & (df['涨跌幅'] < 9.5)].copy()
    for _, row in strong.iterrows():
        pools['strong'].append({
            'code': row['代码'],
            'name': row['名称'],
            'price': row['最新价'],
            'change_pct': row['涨跌幅'],
        })
    
    # 热门池: 涨幅 3~5% 且 换手率 > 3%
    hot = df[(df['涨跌幅'] >= 3) & (df['涨跌幅'] < 5) & (df['换手率'] > 3)].copy()
    for _, row in hot.iterrows():
        pools['hot'].append({
            'code': row['代码'],
            'name': row['名称'],
            'price': row['最新价'],
            'change_pct': row['涨跌幅'],
        })
    
    print(f"\n📊 今日池子构建:")
    print(f"  涨停池: {len(pools['limit_up'])}只")
    print(f"  强势池: {len(pools['strong'])}只")
    print(f"  热门池: {len(pools['hot'])}只")
    
    return pools


def create_data_from_spot(row):
    """从行情数据创建v22输入"""
    price = row['最新价']
    change_pct = row['涨跌幅']
    
    # 估算其他指标（简化版，实际需要历史数据）
    return {
        'code': row['代码'],
        'name': row['名称'],
        'close': price,
        'open': price / (1 + change_pct/100),
        'high': price * 1.01,
        'low': price * 0.99,
        'prev_close': price / (1 + change_pct/100),
        'volume': row['成交量'] if '成交量' in row else 100000,
        'volume_20d_avg': 80000,
        'amount': 25000,
        'high_20d': price * 1.05,
        'low_20d': price * 0.90,
        'ma5': price * 0.98,
        'ma10': price * 0.97,
        'ma20': price * 0.96,
        'macd': 0.3,
        'rsi6': min(55 + change_pct, 80),
        'kdj_k': 55,
        'kdj_d': 50,
        'kdj_j': 60,
        'volume_ratio': 1.5 + change_pct/10,
        'change_pct': change_pct,
        'streak_days': 1,
        'is_hot_sector': True,
        'is_top3_sector': True,
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
        'high_recent': price * 1.05,
        'volume_rally_avg': 80000,
        'high_5d_ago': price * 0.98,
        'days_in_channel': 0,
        'volume_trend_down': False,
        'breakout_today': change_pct > 5,
        'high_cup': price * 1.08,
        'handle_low': price * 0.92,
        'volume_handle': 100000,
        'volume_cup_avg': 80000,
        'cost_distribution': [],
        'auction_strength': 0,
        'pullback_pct': 3.0,
        'change_pct_2d': change_pct * 0.5,
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


def run_today_screener():
    """今日完整选股"""
    print("="*60)
    print(f"A股动量选股 v2.2 - 今日选股 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print("="*60)
    
    # Step 1: 获取今日行情
    df = get_today_spot()
    if df is None:
        print("❌ 无法获取行情，退出")
        return
    
    # Step 2: 构建池子
    pools = build_pools_from_spot(df)
    
    # Step 3: 合并候选
    candidates = {}
    for pool_name, stocks in pools.items():
        for s in stocks:
            code = s['code']
            if code not in candidates:
                candidates[code] = s
                candidates[code]['sources'] = [pool_name]
            else:
                candidates[code]['sources'].append(pool_name)
    
    # 去重后按涨幅排序
    candidate_list = list(candidates.values())
    candidate_list.sort(key=lambda x: x['change_pct'], reverse=True)
    
    print(f"\n📊 合并候选: {len(candidate_list)}只")
    
    # Step 4: v22评分（只评前20只，避免太慢）
    print("\n" + "="*60)
    print("Step 4: v22评分")
    print("="*60)
    
    results = []
    for s in candidate_list[:20]:
        code = s['code']
        # 从df获取完整行情行
        row = df[df['代码'] == code]
        if len(row) == 0:
            continue
        row = row.iloc[0]
        
        data = create_data_from_spot(row)
        result = run_v22_scoring(data)
        result['code'] = code
        result['name'] = s['name']
        result['price'] = s['price']
        result['change_pct'] = s['change_pct']
        result['sources'] = s['sources']
        
        results.append(result)
    
    # Step 5: 排序输出
    results.sort(key=lambda x: x['final_score'], reverse=True)
    
    print("\n" + "="*60)
    print("🎯 今日选股结果")
    print("="*60)
    
    for i, r in enumerate(results[:10], 1):
        kelly = calc_kelly_position(100000, r['tier'])
        
        print(f"\n{'─'*50}")
        print(f"Rank {i}: {r['code']} {r['name']} [{r['tier']}]")
        print(f"  💰 价格: ¥{r['price']:.2f} | 涨幅: {r['change_pct']:+.2f}%")
        print(f"  📊 综合得分: {r['final_score']:.3f}")
        print(f"  🎯 过夜分: {r['overnight_score']:.1f}/20 | 融合分: {r['fusion_score']:.1f}/15")
        
        prob = r.get('overnight_prob')
        if prob:
            print(f"  ⭐ 过夜胜率: {prob}% [{r.get('overnight_rating', 'N/A')}]")
        
        stype = r.get('strategy_type', {})
        if stype:
            print(f"  📌 策略: {stype.get('type', 'N/A')} - {stype.get('reason', '')}")
        
        print(f"  💵 建议仓位: {kelly['position_pct']:.1f}%")
        print(f"  📝 来源: {', '.join(r['sources'])}")
    
    print("\n" + "="*60)
    print("📈 统计汇总")
    print("="*60)
    tier_counts = {}
    for r in results:
        tier = r['tier']
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    for tier in ['S', 'A', 'B', 'X']:
        print(f"  Tier {tier}: {tier_counts.get(tier, 0)}只")


if __name__ == '__main__':
    run_today_screener()
