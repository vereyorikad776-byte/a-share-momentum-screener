#!/usr/bin/env python3
"""
sina_data_feed.py - 新浪行情数据接口

功能：
- 日K线数据获取（新浪财经）
- 5分钟K线数据获取
- 实时行情获取
- 作为 akshare / iFinD 的备选数据源

API来源：
- 日K: https://quotes.sina.cn/cn/api/quotes.php?symbol=sh600519&dataname=ohlc&volume=1&new_format=1&page=1&num=100
- 分钟K: http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
- 实时: https://hq.sinajs.cn/list=sh600519

用法：
    from sina_data_feed import get_daily_klines, get_minute_klines, get_realtime_quote
    
    df = get_daily_klines('600519')  # 日K
    df = get_minute_klines('600519', period=5)  # 5分钟K
    quote = get_realtime_quote('600519')  # 实时行情
"""

import requests
import pandas as pd
import json
from datetime import datetime, timedelta
from typing import Optional


def _get_sina_code(code: str) -> str:
    """转换股票代码为新浪格式"""
    code = str(code).zfill(6)
    if code.startswith('6'):
        return f'sh{code}'
    elif code.startswith('0') or code.startswith('3'):
        return f'sz{code}'
    return code


def get_daily_klines(code: str, num: int = 100) -> Optional[pd.DataFrame]:
    """
    获取日K线数据
    
    Args:
        code: 股票代码
        num: 获取天数
    
    Returns:
        DataFrame [date, open, high, low, close, volume] 或 None
    """
    sina_code = _get_sina_code(code)
    
    url = f"https://quotes.sina.cn/cn/api/quotes.php?symbol={sina_code}&dataname=ohlc&volume=1&new_format=1&page=1&num={num}"
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn'
        })
        response.encoding = 'utf-8'
        
        # 新浪返回格式可能是JSON数组或JSONP
        text = response.text.strip()
        if text.startswith('var '):
            text = text[text.find('['):text.rfind(']')+1]
        
        # 日K接口有时返回空
        if not text or text == 'null':
            return None
        
        # 尝试解析JSON
        data = json.loads(text)
        
        if not data or not isinstance(data, list):
            return None
        
        rows = []
        for item in data:
            if len(item) >= 6:
                rows.append({
                    'date': item[0],
                    'open': float(item[1]),
                    'high': float(item[2]),
                    'low': float(item[3]),
                    'close': float(item[4]),
                    'volume': int(item[5])
                })
        
        df = pd.DataFrame(rows)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        return df
        
    except Exception as e:
        print(f"⚠️ 新浪日K获取失败 {code}: {e}")
        return None


def get_minute_klines(code: str, period: int = 5, num: int = 240) -> Optional[pd.DataFrame]:
    """
    获取分钟K线数据
    
    Args:
        code: 股票代码
        period: 周期（5=5分钟, 15=15分钟, 30=30分钟, 60=60分钟）
        num: 获取条数
    
    Returns:
        DataFrame [datetime, open, high, low, close, volume] 或 None
    """
    sina_code = _get_sina_code(code)
    
    url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={sina_code}&scale={period}&ma=no&datalen={num}"
    
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.encoding = 'gbk'
        
        # 新浪返回JSON数组
        text = response.text
        if not text or text == 'null':
            return None
        
        data = json.loads(text)
        
        if not data:
            return None
        
        rows = []
        for item in data:
            rows.append({
                'datetime': item['day'],
                'open': float(item['open']),
                'high': float(item['high']),
                'low': float(item['low']),
                'close': float(item['close']),
                'volume': int(item['volume'])
            })
        
        df = pd.DataFrame(rows)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        
        return df
        
    except Exception as e:
        print(f"⚠️ 新浪分钟K获取失败 {code}: {e}")
        return None


def get_realtime_quote(code: str) -> Optional[dict]:
    """
    获取实时行情
    
    Args:
        code: 股票代码
    
    Returns:
        dict 或 None
    """
    sina_code = _get_sina_code(code)
    
    url = f"https://hq.sinajs.cn/list={sina_code}"
    
    try:
        response = requests.get(url, timeout=10, headers={
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.encoding = 'gbk'
        
        # 返回格式: var hq_str_sh600519="贵州茅台,1500.00,...";
        text = response.text
        
        if 'var hq_str_' not in text:
            return None
        
        # 提取数据
        start = text.find('"') + 1
        end = text.rfind('"')
        data_str = text[start:end]
        
        parts = data_str.split(',')
        if len(parts) < 33:
            return None
        
        return {
            'name': parts[0],
            'open': float(parts[1]),
            'close_yesterday': float(parts[2]),
            'price': float(parts[3]),
            'high': float(parts[4]),
            'low': float(parts[5]),
            'volume': int(parts[8]),
            'amount': float(parts[9]),
            'bid1': float(parts[11]),
            'ask1': float(parts[21]),
            'date': parts[30],
            'time': parts[31]
        }
        
    except Exception as e:
        print(f"⚠️ 新浪实时行情获取失败 {code}: {e}")
        return None


# 测试
if __name__ == '__main__':
    print("测试新浪数据接口...")
    
    # 测试日K
    print("\n1. 日K线 (600519 贵州茅台):")
    df = get_daily_klines('600519', num=5)
    if df is not None:
        print(df.to_string(index=False))
    
    # 测试分钟K
    print("\n2. 5分钟K线 (600519):")
    df = get_minute_klines('600519', period=5, num=3)
    if df is not None:
        print(df.to_string(index=False))
    
    # 测试实时行情
    print("\n3. 实时行情 (600519):")
    quote = get_realtime_quote('600519')
    if quote:
        print(f"  名称: {quote['name']}")
        print(f"  现价: {quote['price']}")
        print(f"  涨跌: {quote['price'] - quote['close_yesterday']:+.2f}")
        print(f"  时间: {quote['date']} {quote['time']}")
    
    print("\n测试完成")
