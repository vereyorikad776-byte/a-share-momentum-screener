#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mootdx（通达信TCP）数据源适配器
⚠️ 需要通达信终端环境，在云服务器上可能无法连接
本地Windows + 通达信客户端时可用

特性：
- 极速行情（27ms阿里云节点）
- 五档盘口数据
- 分笔成交（tick）
- 1/5/15/30/60分钟K线
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class MootdxConfig:
    """Mootdx配置"""
    server: tuple = ()  # (host, port)，空则自动选择
    timeout: int = 5


class MootdxAdapter:
    """Mootdx/通达信数据适配器"""
    
    def __init__(self, config: Optional[MootdxConfig] = None):
        self.config = config or MootdxConfig()
        self._client = None
        self._cache = {}
        self._cache_ttl = 30  # 实时行情缓存30秒
        self._connected = False
    
    def _get_client(self):
        """获取或创建连接"""
        if self._client is not None:
            return self._client
        
        try:
            from mootdx.quotes import Quotes
            if self.config.server:
                self._client = Quotes.factory(
                    market='std',
                    server=self.config.server,
                    timeout=self.config.timeout
                )
            else:
                self._client = Quotes.factory(
                    market='std',
                    timeout=self.config.timeout
                )
            self._connected = True
            return self._client
        except Exception as e:
            print(f"  Mootdx连接失败: {e}")
            return None
    
    def is_available(self) -> bool:
        """检查是否可用"""
        try:
            import mootdx
            return True
        except:
            return False
    
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected and self._client is not None
    
    def _cache_get(self, key: str):
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None
    
    def _cache_set(self, key: str, data):
        self._cache[key] = (data, time.time())
    
    def get_realtime_quote(self, code: str) -> Optional[Dict]:
        """获取实时行情"""
        cache_key = f"mdx_quote_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        client = self._get_client()
        if not client:
            return None
        
        try:
            df = client.quotes(symbol=code)
            if df is None or df.empty:
                return None
            
            row = df.iloc[0]
            data = {
                'code': code,
                'source': 'mootdx',
                'price': float(row.get('price', 0)),
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'pre_close': float(row.get('last_close', 0)),
                'volume': int(row.get('vol', 0)),
                'amount': float(row.get('amount', 0)),
                'change_pct': float(row.get('change', 0)),
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            
            self._cache_set(cache_key, data)
            return data
            
        except Exception as e:
            print(f"  Mootdx行情失败: {e}")
            return None
    
    def get_bidask(self, code: str) -> Optional[Dict]:
        """
        获取五档盘口
        返回: bid1-5/ask1-5 + 挂单量
        """
        client = self._get_client()
        if not client:
            return None
        
        try:
            df = client.bars(symbol=code)  # mootdx用bars获取盘口
            if df is None or df.empty:
                return None
            
            # 提取五档数据
            data = {'code': code, 'source': 'mootdx'}
            
            for i in range(1, 6):
                data[f'bid{i}'] = float(df.get(f'bid{i}', [0])[0]) if f'bid{i}' in df.columns else 0
                data[f'bid_vol{i}'] = int(df.get(f'bid_vol{i}', [0])[0]) if f'bid_vol{i}' in df.columns else 0
                data[f'ask{i}'] = float(df.get(f'ask{i}', [0])[0]) if f'ask{i}' in df.columns else 0
                data[f'ask_vol{i}'] = int(df.get(f'ask_vol{i}', [0])[0]) if f'ask_vol{i}' in df.columns else 0
            
            # 计算盘口压力
            total_bid_vol = sum(data.get(f'bid_vol{i}', 0) for i in range(1, 6))
            total_ask_vol = sum(data.get(f'ask_vol{i}', 0) for i in range(1, 6))
            
            if total_ask_vol > 0:
                data['bid_ask_ratio'] = round(total_bid_vol / total_ask_vol, 2)
            else:
                data['bid_ask_ratio'] = 1.0
            
            return data
            
        except Exception as e:
            print(f"  Mootdx盘口失败: {e}")
            return None
    
    def get_kline(self, code: str, period: str = 'day', count: int = 60) -> List[Dict]:
        """
        获取K线
        period: day/week/month/1min/5min/15min/30min/60min
        """
        cache_key = f"mdx_kline_{code}_{period}_{count}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        client = self._get_client()
        if not client:
            return []
        
        try:
            # 周期映射
            freq_map = {
                '1min': 8, '5min': 0, '15min': 1,
                '30min': 2, '60min': 3, 'day': 9,
                'week': 5, 'month': 6
            }
            freq = freq_map.get(period, 9)
            
            df = client.k(symbol=code, frequency=freq, offset=count)
            if df is None or df.empty:
                return []
            
            klines = []
            for _, row in df.iterrows():
                klines.append({
                    'date': str(row.get('date', '')),
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': int(row.get('vol', 0)),
                    'amount': float(row.get('amount', 0)),
                })
            
            self._cache_set(cache_key, klines)
            return klines
            
        except Exception as e:
            print(f"  Mootdx K线失败: {e}")
            return []
    
    def close(self):
        """关闭连接"""
        if self._client:
            try:
                self._client.close()
            except:
                pass
            self._client = None
            self._connected = False


# 便捷函数
_adapter = None

def get_mootdx_adapter() -> MootdxAdapter:
    global _adapter
    if _adapter is None:
        _adapter = MootdxAdapter()
    return _adapter

def get_realtime_quote(code: str) -> Optional[Dict]:
    return get_mootdx_adapter().get_realtime_quote(code)

def get_bidask(code: str) -> Optional[Dict]:
    return get_mootdx_adapter().get_bidask(code)

def is_mootdx_available() -> bool:
    return get_mootdx_adapter().is_available()


def get_market_depth_score(code: str) -> float:
    """
    基于五档盘口计算市场深度评分
    bid_ask_ratio > 1.2: 买盘强
    bid_ask_ratio < 0.8: 卖盘强
    """
    adapter = get_mootdx_adapter()
    bidask = adapter.get_bidask(code)
    
    if not bidask:
        return 0.5  # 中性
    
    ratio = bidask.get('bid_ask_ratio', 1.0)
    
    # 映射到 0-10 分
    if ratio > 2.0:
        return 10.0
    elif ratio > 1.5:
        return 8.0
    elif ratio > 1.2:
        return 6.0
    elif ratio > 0.8:
        return 5.0
    elif ratio > 0.5:
        return 3.0
    else:
        return 1.0


if __name__ == "__main__":
    adapter = MootdxAdapter()
    print("Mootdx 测试...")
    print(f"库可用: {adapter.is_available()}")
    
    print("\n实时行情 (000001):")
    quote = adapter.get_realtime_quote('000001')
    if quote:
        print(f"  ¥{quote['price']} ({quote['change_pct']:+.2f}%)")
    else:
        print("  获取失败（需要通达信环境）")
    
    print("\n五档盘口:")
    bidask = adapter.get_bidask('000001')
    if bidask:
        print(f"  买1: {bidask.get('bid1')} x {bidask.get('bid_vol1')}")
        print(f"  卖1: {bidask.get('ask1')} x {bidask.get('ask_vol1')}")
        print(f"  买卖比: {bidask.get('bid_ask_ratio')}")
    else:
        print("  获取失败")
    
    adapter.close()
