#!/usr/bin/env python3
"""
today_realtime_v22.py - 基于已获取的实时数据跑v22评分
不再拉全市场，直接用强势股+涨停股数据
"""

import json
import sys
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import akshare as ak
import pandas as pd

from v22_engine import run_v22_scoring
from multi_agent_debate import run_debate
from kelly_position import calc_kelly_position


def get_today_data():
    """获取今日强势股和涨停股（轻量接口）"""
    print("📊 拉取今日强势股...")
    df_strong = ak.stock_zt_pool_strong_em(date='20260819')
    df_strong['代码'] = df_strong['代码'].astype(str).str.zfill(6)
    
    print("📊 拉取今日涨停股...")
    df_limit = ak.stock_zt_pool_em(date='20260819')
    df_limit['代码'] = df_limit['代码'].astype(str).str.zfill(6)
    
    # 合并
    df_all = pd.concat([df_strong, df_limit], ignore_index=True)
    df_all = df_all.drop_duplicates(subset=['代码'])
    
    # 排除688科创板和创业板（300开头保留，688排除）
    df_all = df_all[~df_all['代码'].str.startswith('688')]
    df_all = df_all[~df_all['代码'].str.startswith('8')]
    df_all = df_all[~df_all['代码'].str.startswith('4')]
    
    # 转换数值
    for col in ['最新价', '涨跌幅', '换手率', '量比']:
        if col in df_all.columns:
            df_all[col] = pd.to_numeric(df_all[col], errors='coerce')
    
    print(f"✅ 合计 {len(df_all)} 只候选（已去重+过滤）")
    return df_all


def run_v22_on_candidates(df):
    """对候选票跑v22评分"""
    
    # 筛选涨幅3-9%的可买入票（已涨停的标记出来）
    df['可买入'] = (df['涨跌幅'] >= 3) & (df['涨跌幅'] < 9.5)
    df['已涨停'] = df['涨跌幅'] >= 9.5
    
    # 优先处理可买入的，再处理涨停的
    df_sorted = df.sort_values(['可买入', '涨跌幅'], ascending=[False, False])
    
    print(f"\n🎯 可买入（涨幅3-9%）: {df['可买入'].sum()}只")
    print(f"🎯 已涨停（涨幅≥9.5%）: {df['已涨停'].sum()}只")
    
    results = []
    
    for _, row in df_sorted.head(30).iterrows():
        code = row['代码']
        name = row['名称']
        price = row['最新价']
        change = row['涨跌幅']
        turnover = row.get('换手率', 0)
        vol_ratio = row.get('量比', 1.5)
        
        # 根据涨幅估算技术指标
        rsi = min(45 + change * 2, 90)
        macd = 0.2 + change / 50
        volume_ratio = vol_ratio if pd.notna(vol_ratio) else 1.5
        
        data = {
            'code': code,
            'name': name,
            'close': price,
            'open': price / (1 + change/100) * (1 + change/300),
            'high': price * 1.005,
            'low': price / (1 + change/100) * 0.995,
            'prev_close': price / (1 + change/100),
            'volume': 100000 * volume_ratio,
            'volume_20d_avg': 100000,
            'amount': 25000 * volume_ratio,
            'high_20d': price * 1.06,
            'low_20d': price * 0.88,
            'ma5': price * 0.985,
            'ma10': price * 0.975,
            'ma20': price * 0.965,
            'macd': macd,
            'rsi6': rsi,
            'kdj_k': min(50 + change, 90),
            'kdj_d': min(45 + change * 0.8, 85),
            'kdj_j': min(55 + change * 1.2, 95),
            'volume_ratio': volume_ratio,
            'change_pct': change,
            'streak_days': 1,
            'is_hot_sector': change > 5,
            'is_top3_sector': change > 6,
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
            'date': '20260819',
            'high_recent': price * 1.05,
            'volume_rally_avg': 100000,
            'high_5d_ago': price * 0.97,
            'days_in_channel': 0,
            'volume_trend_down': False,
            'breakout_today': change > 5,
            'high_cup': price * 1.08,
            'handle_low': price * 0.92,
            'volume_handle': 100000,
            'volume_cup_avg': 100000,
            'cost_distribution': [],
            'auction_strength': 0,
            'pullback_pct': 3.0,
            'change_pct_2d': change * 0.5,
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
            result['name'] = name
            result['price'] = price
            result['change_pct'] = change
            result['turnover'] = turnover
            result['volume_ratio'] = volume_ratio
            result['can_buy'] = change < 9.5
            
            # 辩论
            debate = run_debate(
                tech_signals={'macd': macd, 'ma': 0.3, 'rsi': rsi, 'volume': volume_ratio},
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
    
    return results


def main():
    print("="*60)
    print(f"A股动量选股 v2.2 - 今日实时选股")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("="*60)
    
    # 获取数据
    df = get_today_data()
    if df is None or len(df) == 0:
        print("❌ 无法获取数据")
        return
    
    # 显示今日强势股Top 15
    print(f"\n📊 今日强势股Top 15:")
    print(df[['代码','名称','最新价','涨跌幅']].head(15).to_string(index=False))
    
    # v22评分
    print(f"\n{'='*60}")
    print("🔄 v22评分 + 七维辩论...")
    print(f"{'='*60}")
    
    results = run_v22_on_candidates(df)
    
    # 排序：可买入的优先，然后按分数
    results.sort(key=lambda x: (not x.get('can_buy', True), -x['final_score']))
    
    # 输出
    print(f"\n{'='*60}")
    print("🎯 今日选股结果")
    print(f"{'='*60}")
    print(f"📅 数据: 2026-08-19 实时 | 候选池: 强势股+涨停股")
    
    buyable_results = [r for r in results if r.get('can_buy', True)]
    limit_results = [r for r in results if not r.get('can_buy', True)]
    
    # 可买入推荐
    if buyable_results:
        print(f"\n{'─'*50}")
        print(f"✅ 可买入推荐（涨幅3-9%，未涨停）")
        print(f"{'─'*50}")
        
        for i, r in enumerate(buyable_results[:8], 1):
            kelly = calc_kelly_position(100000, r['tier'])
            
            print(f"\nRank {i}: {r['code']} {r['name']} [{r['tier']}]")
            print(f"  💰 ¥{r['price']:.2f} | 涨幅: {r['change_pct']:+.2f}% | 换手: {r['turnover']:.1f}%")
            print(f"  📊 得分: {r['final_score']:.3f} | 过夜: {r['overnight_score']:.1f}/20 | 融合: {r['fusion_score']:.1f}/15")
            print(f"  🗣️ 辩论: {r['debate_score']:+.2f}")
            
            prob = r.get('overnight_prob')
            if prob:
                print(f"  ⭐ 过夜胜率: {prob}% [{r.get('overnight_rating', 'N/A')}]")
            
            stype = r.get('strategy_type', {})
            if stype:
                print(f"  📌 策略: {stype.get('type', 'N/A')}")
            
            print(f"  💵 建议仓位: {kelly['position_pct']:.1f}%")
            if r['reasons']:
                print(f"  📝 {', '.join(r['reasons'][:2])}")
    
    # 涨停观察
    if limit_results:
        print(f"\n{'─'*50}")
        print(f"⛔ 已涨停（观察，等开板）")
        print(f"{'─'*50}")
        
        for i, r in enumerate(limit_results[:5], 1):
            print(f"\n观察 {i}: {r['code']} {r['name']} [{r['tier']}]")
            print(f"  💰 ¥{r['price']:.2f} | 涨幅: {r['change_pct']:+.2f}% ⛔")
            print(f"  📊 得分: {r['final_score']:.3f} | 过夜: {r['overnight_score']:.1f}/20")
    
    # 统计
    print(f"\n{'='*60}")
    print("📈 统计")
    print(f"{'='*60}")
    print(f"  可买入候选: {len(buyable_results)}只")
    print(f"  已涨停候选: {len(limit_results)}只")
    
    tier_counts = {}
    for r in results:
        tier = r['tier']
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    for tier in ['S', 'A', 'B', 'X']:
        if tier in tier_counts:
            print(f"  Tier {tier}: {tier_counts[tier]}只")
    
    print(f"\n{'='*60}")
    print("⚠️  风险提示")
    print(f"{'='*60}")
    print("  • 以上基于实时行情估算，非精确技术指标")
    print("  • 涨停票需等开板后才能买入")
    print("  • 建议结合iFinD精确数据二次确认")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
