#!/usr/bin/env python3
"""
v21_engine.py - v2.1兼容层

将v2.1的run_v21_pipeline映射到v2.2的run_v22_scoring
保留此文件以确保旧代码兼容
"""

from v22_engine import run_v22_scoring


def run_v21_pipeline(
    code=None, name=None, date=None,
    close=0, high=0, low=0, open_price=0, volume=0, prev_close=0,
    high_20d=0, low_20d=0, volume_20d_avg=0,
    macd_hist=0, ma5=0, ma10=0, ma20=0,
    rsi6=50, k=50, d=50, j=50, cci=0, roc=0,
    pe=50, roe=0, revenue_growth=0, market_cap=0,
    org_pct=0, northbound_5d=0, main_fund_5d=0, shareholder_change=0,
    sentiment_score=0, has_regulatory_risk=False,
    industry_cycle='stable', policy_tailwind=0, supply_demand='balanced', liquidity_env='neutral',
    volume_rally_avg=0, has_hammer_or_engulfing=False,
    high_5d_ago=0, days_in_channel=0, volume_trend_down=False, breakout_today=False,
    high_cup=0, handle_low=0, volume_handle=0, volume_cup_avg=0,
    streak_days=0,
    market_green=False, sector_green=False, trend_green=False,
    price_green=False, position_green=False,
    is_top3_sector=False, is_hot_sector=False, has_multi_concepts=False,
    rebound_count=1, friday_market_drop=False, ma20_trend='neutral',
    log=False, **kwargs
):
    """
    v2.1兼容接口 - 映射到v2.2评分引擎
    """
    data = {
        'code': code or '',
        'name': name or '',
        'date': date or '',
        'close': close,
        'high': high,
        'low': low,
        'open': open_price,
        'volume': volume,
        'prev_close': prev_close,
        'high_20d': high_20d,
        'low_20d': low_20d,
        'volume_20d_avg': volume_20d_avg,
        'macd': macd_hist,
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'rsi6': rsi6,
        'kdj_k': k,
        'kdj_d': d,
        'kdj_j': j,
        'cci': cci,
        'roc': roc,
        'pe': pe,
        'roe': roe,
        'revenue_growth': revenue_growth,
        'market_cap': market_cap,
        'org_pct': org_pct,
        'northbound_5d': northbound_5d,
        'main_fund_5d': main_fund_5d,
        'shareholder_change': shareholder_change,
        'sentiment_score': sentiment_score,
        'has_regulatory_risk': has_regulatory_risk,
        'industry_cycle': industry_cycle,
        'policy_tailwind': policy_tailwind,
        'supply_demand': supply_demand,
        'liquidity_env': liquidity_env,
        'volume_rally_avg': volume_rally_avg,
        'has_hammer_or_engulfing': has_hammer_or_engulfing,
        'high_5d_ago': high_5d_ago,
        'days_in_channel': days_in_channel,
        'volume_trend_down': volume_trend_down,
        'breakout_today': breakout_today,
        'high_cup': high_cup,
        'handle_low': handle_low,
        'volume_handle': volume_handle,
        'volume_cup_avg': volume_cup_avg,
        'streak_days': streak_days,
        'market_green': market_green,
        'sector_green': sector_green,
        'trend_green': trend_green,
        'price_green': price_green,
        'position_green': position_green,
        'is_top3_sector': is_top3_sector,
        'is_hot_sector': is_hot_sector,
        'has_multi_concepts': has_multi_concepts,
        'rebound_count': rebound_count,
        'friday_market_drop': friday_market_drop,
        'ma20_trend': ma20_trend,
    }
    
    # 合并kwargs中的额外参数
    data.update(kwargs)
    
    result = run_v22_scoring(data)
    
    # 转换为v2.1输出格式兼容
    return {
        'code': code,
        'name': name,
        'date': date,
        'tier': result.get('tier', 'X'),
        'final_score': result.get('final_score', 0),
        'pattern': result.get('pattern', 0),
        'pattern_name': result.get('pattern_name', ''),
        'overnight': result.get('overnight_score', 0),
        'fusion': result.get('fusion_score', 0),
        'debate': result.get('debate_score', 0),
        'market_context': result.get('market', 0),
        'tech': result.get('tech', 0),
        'sentiment': result.get('sentiment', 0),
        'fund': result.get('fund', 0),
        'fundamental': result.get('fundamental', 0),
        'news': result.get('news', 0),
        'f_score': result.get('f_score'),
        'z_score': result.get('z_score'),
        'z_zone': result.get('z_zone'),
        'quality_tag': result.get('quality_tag'),
        'market_mul': result.get('step_multiplier', 1.0),
        'cross_bonus': 0,
        'reasons': result.get('reasons', []),
        # v2.2新增字段
        'overnight_prob': result.get('overnight_prob'),
        'overnight_rating': result.get('overnight_rating'),
        'overnight_expected': result.get('overnight_expected'),
        'strategy_type': result.get('strategy_type', {}),
    }
