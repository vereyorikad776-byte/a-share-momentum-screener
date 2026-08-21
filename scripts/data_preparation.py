"""
data_preparation.py - 评分数据准备模块

从K线数据和外部数据源准备完整的评分所需字段
"""

import numpy as np
import pandas as pd


def calc_macd(close_series: pd.Series, fast=12, slow=26, signal=9):
    """计算MACD指标"""
    ema_fast = close_series.ewm(span=fast, adjust=False).mean()
    ema_slow = close_series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2
    return {
        'macd_dif': dif.iloc[-1],
        'macd_dea': dea.iloc[-1],
        'macd': macd.iloc[-1],
    }


def calc_rsi(close_series: pd.Series, period=6):
    """计算RSI"""
    delta = close_series.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]


def calc_kdj(high_series: pd.Series, low_series: pd.Series, close_series: pd.Series, n=9):
    """计算KDJ"""
    lowest_low = low_series.rolling(window=n).min()
    highest_high = high_series.rolling(window=n).max()
    rsv = (close_series - lowest_low) / (highest_high - lowest_low) * 100
    k = rsv.ewm(com=2, adjust=False).mean()
    d = k.ewm(com=2, adjust=False).mean()
    j = 3 * k - 2 * d
    return {
        'kdj_k': k.iloc[-1],
        'kdj_d': d.iloc[-1],
        'kdj_j': j.iloc[-1],
    }


def calc_streak(df: pd.DataFrame) -> int:
    """计算连涨天数（从最新一天往前数）"""
    changes = (df['close'].diff() > 0).astype(int)
    streak = 0
    for i in range(len(changes) - 1, 0, -1):
        if changes.iloc[i] == 1:
            streak += 1
        else:
            break
    return streak


def calc_volume_ratio(df: pd.DataFrame) -> float:
    """计算量比：当日成交量 / 前5日均量"""
    if len(df) < 6:
        return 1.0
    today_vol = df['volume'].iloc[-1]
    avg_5d = df['volume'].iloc[-6:-1].mean()
    return today_vol / avg_5d if avg_5d > 0 else 1.0


def prepare_scoring_data(code: str, name: str, df: pd.DataFrame) -> dict:
    """
    从K线DataFrame准备完整的评分数据
    
    返回包含所有v22_engine评分所需字段的字典
    """
    if df is None or len(df) < 30:
        return None
    
    df = df.copy()
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    
    # 基础价格数据
    close = float(latest['close'])
    open_price = float(latest['open'])
    high = float(latest['high'])
    low = float(latest['low'])
    volume = float(latest['volume'])
    amount = float(latest.get('amount', 0))
    prev_close = float(prev['close'])
    
    # 涨幅
    change_pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0
    
    # 均线
    ma5 = float(df['close'].rolling(5).mean().iloc[-1])
    ma10 = float(df['close'].rolling(10).mean().iloc[-1])
    ma20 = float(df['close'].rolling(20).mean().iloc[-1])
    ma60 = float(df['close'].rolling(60).mean().iloc[-1]) if len(df) >= 60 else ma20
    
    # 技术指标
    macd_dict = calc_macd(df['close'])
    rsi6 = calc_rsi(df['close'], 6)
    kdj_dict = calc_kdj(df['high'], df['low'], df['close'])
    
    # 20日高低点
    high_20d = float(df['high'].tail(20).max()) if len(df) >= 20 else high
    low_20d = float(df['low'].tail(20).min()) if len(df) >= 20 else low
    
    # 量比
    volume_ratio = calc_volume_ratio(df)
    
    # 连涨天数
    up_streak = calc_streak(df)
    
    # 5日累计涨幅
    if len(df) >= 6:
        close_5d_ago = float(df['close'].iloc[-6])
        change_5d = (close - close_5d_ago) / close_5d_ago * 100
    else:
        change_5d = change_pct
    
    # 振幅
    amplitude = (high - low) / open_price * 100 if open_price > 0 else 0
    
    # 距20日高点距离
    distance_to_high = (high_20d - close) / high_20d * 100 if high_20d > 0 else 100
    
    # 回调幅度（从近期高点）
    high_recent = float(df['high'].tail(10).max())
    pullback_pct = (high_recent - close) / high_recent * 100 if high_recent > 0 else 0
    
    data = {
        'code': code,
        'name': name,
        'close': close,
        'open': open_price,
        'high': high,
        'low': low,
        'volume': volume,
        'amount': amount,
        'prev_close': prev_close,
        'change_pct': change_pct,
        
        # 均线
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'ma60': ma60,
        
        # 技术指标
        'macd': macd_dict['macd'],
        'macd_dif': macd_dict['macd_dif'],
        'macd_dea': macd_dict['macd_dea'],
        'rsi6': rsi6,
        **kdj_dict,
        
        # 量能
        'volume_ratio': volume_ratio,
        'volume_20d_avg': float(df['volume'].tail(20).mean()),
        
        # 价格形态
        'high_20d': high_20d,
        'low_20d': low_20d,
        'high_recent': high_recent,
        'pullback_pct': pullback_pct,
        'distance_to_high': distance_to_high,
        'amplitude': amplitude,
        
        # 趋势
        'up_streak': up_streak,
        'change_5d': change_5d,
        'change_pct_5d': change_5d,
        'change_pct_2d': change_pct * 2,  # 简化：2日涨幅≈单日×2
        
        # 默认空值（后续从外部数据源填充）
        'institution_hold_pct': 0,
        'institution_hold_ratio': 0,
        'northbound_net_5d': 0,
        'main_force_net_5d': 0,
        'shareholder_change_pct': 0,
        'holder_change_pct': 0,
        'pe': 0,
        'pe_ttm': 0,
        'market_cap': 0,
        'profit_growth': 0,
        'beta': 1.0,
        'sector_return': 0,
        'index_change': 0,
        'retail_etf_flow': 0,
        
        # 默认False
        'in_hot_sector': False,
        'is_hot_sector': False,
        'has_limit_up_gene': False,
        'has_hammer': False,
        'has_engulfing': False,
        'has_major_bad_news': False,
        'is_news_blacklisted': False,
        'concept_clarified': False,
        'has_multi_concepts': False,
        'has_contract': False,
        'market_sentiment': 50,
        'total_position_pct': 0,
        'news_sentiment': 0,
        'notice_risk': 1,
        'earnings_impact': 0,
        'hot_relation': 0,
        'fundamental_score': 0,
        'sentiment_score': 0,
        'market_breadth': 0.5,
        'erp': 0.03,
        'margin_status': 0,
        'ma20_trend': 'neutral',
        'sector_change': 0,
        'concepts': [],
    }
    
    return data


def enrich_with_tencent(data: dict) -> dict:
    """从腾讯财经补充PE、市值、涨跌停等数据"""
    try:
        from enhanced_data_feed import tencent_quote
        quotes = tencent_quote([data['code']])
        if data['code'] in quotes:
            q = quotes[data['code']]
            data['pe'] = q.get('pe_ttm', 0) or 0
            data['pe_ttm'] = q.get('pe_ttm', 0) or 0
            data['market_cap'] = q.get('mcap_yi', 0) or 0
            data['change_pct'] = q.get('change_pct', data['change_pct'])
            data['high'] = max(data['high'], q.get('high', 0))
            data['low'] = min(data['low'], q.get('low', data['low'])) if q.get('low') else data['low']
    except Exception as e:
        pass
    return data
