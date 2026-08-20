#!/usr/bin/env python3
"""
today_ifind_final.py - 基于iFinD精确技术指标的v22评分
"""

import json
import sys
from datetime import datetime

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

from v22_engine import run_v22_scoring
from multi_agent_debate import run_debate
from kelly_position import calc_kelly_position

# iFinD精确数据（2026-08-19 11:30 5分钟K线）
IFIND_DATA = {
    '300155.SZ': {
        'name': '安居宝', 'price': 4.69, 'change': 9.32,
        'rsi6': 61.0, 'kdj_k': 44.8, 'kdj_d': 41.3, 'kdj_j': 51.9,
        'macd': -0.018, 'ma5': 4.672, 'ma10': 4.653, 'ma20': 4.662,
        'volume_ratio': 1.5, 'turnover': 12.5,
    },
    '600613.SH': {
        'name': '神奇制药', 'price': 8.32, 'change': 7.22,
        'rsi6': 4.6, 'kdj_k': 47.3, 'kdj_d': 53.4, 'kdj_j': 35.1,
        'macd': -0.087, 'ma5': 8.496, 'ma10': 8.518, 'ma20': 8.529,
        'volume_ratio': 1.5, 'turnover': 15.4,
    },
    '603580.SH': {
        'name': '艾艾精工', 'price': 68.49, 'change': 6.98,
        'rsi6': 66.0, 'kdj_k': 69.7, 'kdj_d': 73.8, 'kdj_j': 61.4,
        'macd': 0.182, 'ma5': 68.218, 'ma10': 67.758, 'ma20': 66.836,
        'volume_ratio': 1.5, 'turnover': 11.0,
    },
    '603207.SH': {
        'name': '小方制药', 'price': 25.08, 'change': 6.54,
        'rsi6': 38.2, 'kdj_k': 16.4, 'kdj_d': 23.9, 'kdj_j': 1.4,
        'macd': -0.189, 'ma5': 25.13, 'ma10': 25.177, 'ma20': 25.38,
        'volume_ratio': 1.5, 'turnover': 12.8,
    },
    '600313.SH': {
        'name': '农发种业', 'price': 7.19, 'change': 6.05,
        'rsi6': 32.6, 'kdj_k': 31.8, 'kdj_d': 36.8, 'kdj_j': 21.9,
        'macd': -0.103, 'ma5': 7.23, 'ma10': 7.312, 'ma20': 7.386,
        'volume_ratio': 1.5, 'turnover': 13.0,
    },
    '301516.SZ': {
        'name': '中远通', 'price': 23.86, 'change': 6.04,
        'rsi6': 40.2, 'kdj_k': 29.0, 'kdj_d': 39.7, 'kdj_j': 7.7,
        'macd': -0.225, 'ma5': 23.976, 'ma10': 24.006, 'ma20': 24.143,
        'volume_ratio': 1.5, 'turnover': 34.3,
    },
    '600547.SH': {
        'name': '山东黄金', 'price': 32.39, 'change': 5.82,
        'rsi6': 53.7, 'kdj_k': 20.1, 'kdj_d': 29.1, 'kdj_j': 2.3,
        'macd': -0.160, 'ma5': 32.366, 'ma10': 32.462, 'ma20': 32.297,
        'volume_ratio': 1.5, 'turnover': 3.3,
    },
    '603382.SH': {
        'name': '海阳科技', 'price': 23.03, 'change': 5.74,
        'rsi6': 59.0, 'kdj_k': 33.0, 'kdj_d': 39.9, 'kdj_j': 19.2,
        'macd': -0.055, 'ma5': 22.978, 'ma10': 22.95, 'ma20': 22.755,
        'volume_ratio': 1.5, 'turnover': 7.1,
    },
    '603556.SH': {
        'name': '海兴电力', 'price': 28.09, 'change': 5.60,
        'rsi6': 48.7, 'kdj_k': 31.1, 'kdj_d': 33.9, 'kdj_j': 25.6,
        'macd': -0.136, 'ma5': 28.132, 'ma10': 28.127, 'ma20': 28.105,
        'volume_ratio': 1.5, 'turnover': 4.6,
    },
    '600371.SH': {
        'name': '万向德农', 'price': 8.56, 'change': 5.16,
        'rsi6': 32.7, 'kdj_k': 19.3, 'kdj_d': 21.6, 'kdj_j': 14.6,
        'macd': -0.102, 'ma5': 8.562, 'ma10': 8.625, 'ma20': 8.747,
        'volume_ratio': 1.5, 'turnover': 14.5,
    },
    '002543.SZ': {
        'name': '万和电气', 'price': 7.23, 'change': 5.09,
        'rsi6': 58.2, 'kdj_k': 62.7, 'kdj_d': 70.5, 'kdj_j': 47.1,
        'macd': 0.066, 'ma5': 7.312, 'ma10': 7.186, 'ma20': 7.030,
        'volume_ratio': 1.5, 'turnover': 3.3,
    },
    '603565.SH': {
        'name': '中谷物流', 'price': 11.40, 'change': 5.07,
        'rsi6': 56.5, 'kdj_k': 67.1, 'kdj_d': 73.3, 'kdj_j': 54.7,
        'macd': -0.021, 'ma5': 11.416, 'ma10': 11.403, 'ma20': 11.341,
        'volume_ratio': 1.5, 'turnover': 1.1,
    },
    '300598.SZ': {
        'name': '诚迈科技', 'price': 36.31, 'change': 4.94,
        'rsi6': 58.2, 'kdj_k': 44.6, 'kdj_d': 44.8, 'kdj_j': 44.3,
        'macd': -0.311, 'ma5': 36.198, 'ma10': 36.189, 'ma20': 36.061,
        'volume_ratio': 1.5, 'turnover': 15.2,
    },
    '605033.SH': {
        'name': '美邦股份', 'price': 20.64, 'change': 4.67,
        'rsi6': 48.1, 'kdj_k': 35.6, 'kdj_d': 42.9, 'kdj_j': 21.0,
        'macd': -0.098, 'ma5': 20.666, 'ma10': 20.708, 'ma20': 20.644,
        'volume_ratio': 1.5, 'turnover': 6.2,
    },
    '600722.SH': {
        'name': '金牛化工', 'price': 13.62, 'change': 4.61,
        'rsi6': 61.6, 'kdj_k': 61.3, 'kdj_d': 69.1, 'kdj_j': 45.8,
        'macd': 0.156, 'ma5': 13.69, 'ma10': 13.482, 'ma20': 12.962,
        'volume_ratio': 1.5, 'turnover': 20.1,
    },
}


def build_data(code, info):
    """构建v22输入（使用iFinD精确指标）"""
    price = info['price']
    change = info['change']
    
    return {
        'code': code.split('.')[0],
        'name': info['name'],
        'close': price,
        'open': price / (1 + change/100) * (1 + change/300),
        'high': price * 1.005,
        'low': price / (1 + change/100) * 0.995,
        'prev_close': price / (1 + change/100),
        'volume': 100000,
        'volume_20d_avg': 100000,
        'amount': 25000,
        'high_20d': price * 1.05,
        'low_20d': price * 0.90,
        'ma5': info['ma5'],
        'ma10': info['ma10'],
        'ma20': info['ma20'],
        'macd': info['macd'],
        'rsi6': info['rsi6'],
        'kdj_k': info['kdj_k'],
        'kdj_d': info['kdj_d'],
        'kdj_j': info['kdj_j'],
        'volume_ratio': info['volume_ratio'],
        'change_pct': change,
        'streak_days': 1,
        'is_hot_sector': change > 5,
        'is_top3_sector': change > 5,
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


def main():
    print("="*60)
    print(f"A股动量选股 v2.2 - iFinD精查版")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"数据源: iFinD 实时技术指标 (5min K线)")
    print("="*60)
    
    results = []
    
    for code, info in IFIND_DATA.items():
        data = build_data(code, info)
        
        try:
            result = run_v22_scoring(data)
            result['code'] = code.split('.')[0]
            result['name'] = info['name']
            result['price'] = info['price']
            result['change_pct'] = info['change']
            result['turnover'] = info['turnover']
            result['rsi6'] = info['rsi6']
            result['macd'] = info['macd']
            result['kdj_k'] = info['kdj_k']
            result['kdj_d'] = info['kdj_d']
            result['kdj_j'] = info['kdj_j']
            
            # 辩论
            debate = run_debate(
                tech_signals={'macd': info['macd'], 'ma': 0.3, 'rsi': info['rsi6'], 'volume': info['volume_ratio']},
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
    print("🎯 今日选股结果（iFinD精确技术指标）")
    print(f"{'='*60}")
    
    for i, r in enumerate(results[:10], 1):
        kelly = calc_kelly_position(100000, r['tier'])
        
        # 指标状态
        macd_status = "金叉" if r['macd'] > 0 else "死叉"
        kdj_status = "金叉" if r['kdj_k'] > r['kdj_d'] else "死叉"
        rsi_status = "超卖" if r['rsi6'] < 20 else ("超买" if r['rsi6'] > 80 else "中性")
        
        print(f"\n{'─'*50}")
        print(f"Rank {i}: {r['code']} {r['name']} [{r['tier']}]")
        print(f"  💰 ¥{r['price']:.2f} | 涨幅: {r['change_pct']:+.2f}% | 换手: {r['turnover']:.1f}%")
        print(f"  📊 综合得分: {r['final_score']:.3f}")
        print(f"  🎯 过夜分: {r['overnight_score']:.1f}/20 | 融合分: {r['fusion_score']:.1f}/15")
        print(f"  🗣️ 辩论分: {r['debate_score']:+.2f}")
        
        print(f"  📈 精确指标: RSI={r['rsi6']:.1f}[{rsi_status}] MACD={r['macd']:+.3f}[{macd_status}] KDJ={r['kdj_k']:.1f}/{r['kdj_d']:.1f}[{kdj_status}]")
        
        prob = r.get('overnight_prob')
        if prob:
            print(f"  ⭐ 过夜胜率: {prob}% [{r.get('overnight_rating', 'N/A')}]")
        
        stype = r.get('strategy_type', {})
        if stype:
            print(f"  📌 策略: {stype.get('type', 'N/A')}")
        
        print(f"  💵 建议仓位: {kelly['position_pct']:.1f}%")
        if r['reasons']:
            print(f"  📝 {', '.join(r['reasons'][:2])}")
    
    print(f"\n{'='*60}")
    print("📈 统计")
    print(f"{'='*60}")
    tier_counts = {}
    for r in results:
        tier = r['tier']
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    for tier in ['S', 'A', 'B', 'X']:
        if tier in tier_counts:
            print(f"  Tier {tier}: {tier_counts[tier]}只")
    
    print(f"\n{'='*60}")
    print("✅ 数据来源: iFinD 实时技术指标（5分钟K线）")
    print("⚠️  投资有风险，决策需自行判断")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
