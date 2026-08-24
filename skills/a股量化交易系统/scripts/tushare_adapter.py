#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare 数据源适配器
旧版免费接口（实时行情可用，K线/财务需Pro版token）
"""

import time
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class TushareConfig:
    """Tushare配置"""
    token: str = ""  # Pro版token（可选）
    timeout: int = 10


class TushareAdapter:
    """Tushare数据适配器"""
    
    def __init__(self, config: Optional[TushareConfig] = None):
        self.config = config or TushareConfig()
        self._cache = {}
        self._cache_ttl = 60  # 实时行情缓存60秒
        self._pro = None
        
        # 尝试初始化Pro版
        if self.config.token:
            try:
                import tushare as ts
                ts.set_token(self.config.token)
                self._pro = ts.pro_api()
                print("  Tushare Pro 已初始化")
            except Exception as e:
                print(f"  Tushare Pro 初始化失败: {e}")
    
    def is_available(self) -> bool:
        """检查是否可用"""
        try:
            import tushare as ts
            return True
        except:
            return False
    
    def is_pro_available(self) -> bool:
        """检查Pro版是否可用"""
        return self._pro is not None
    
    def _cache_get(self, key: str):
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None
    
    def _cache_set(self, key: str, data):
        self._cache[key] = (data, time.time())
    
    def get_realtime_quote(self, code: str) -> Optional[Dict]:
        """
        获取实时行情（旧版免费接口）
        返回: 价格/涨跌幅/成交量/买卖盘
        """
        cache_key = f"ts_quote_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        try:
            import tushare as ts
            df = ts.get_realtime_quotes(code)
            if df.empty:
                return None
            
            row = df.iloc[0]
            data = {
                'code': code,
                'source': 'tushare',
                'name': row.get('name', ''),
                'price': float(row.get('price', 0)),
                'pre_close': float(row.get('pre_close', 0)),
                'open': float(row.get('open', 0)),
                'high': float(row.get('high', 0)),
                'low': float(row.get('low', 0)),
                'volume': int(float(row.get('volume', 0))),
                'amount': float(row.get('amount', 0)),
                'bid1': float(row.get('bid', 0)),
                'ask1': float(row.get('ask', 0)),
                'bid_vol1': int(float(row.get('b1_v', 0))),
                'ask_vol1': int(float(row.get('a1_v', 0))),
                'change_pct': 0.0,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            }
            
            # 计算涨跌幅
            if data['pre_close'] > 0:
                data['change_pct'] = (data['price'] - data['pre_close']) / data['pre_close'] * 100
            
            self._cache_set(cache_key, data)
            return data
            
        except Exception as e:
            print(f"  Tushare实时行情失败: {e}")
            return None
    
    def get_kline(self, code: str, period: str = 'day', count: int = 60) -> List[Dict]:
        """
        获取K线数据
        旧版接口不稳定，优先用Pro版
        """
        if self._pro:
            return self._get_pro_kline(code, period, count)
        else:
            return self._get_free_kline(code, period, count)
    
    def _get_pro_kline(self, code: str, period: str, count: int) -> List[Dict]:
        """Pro版K线"""
        try:
            # Tushare Pro 需要标准代码格式
            if code.startswith('6'):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"
            
            df = self._pro.daily(ts_code=ts_code, limit=count)
            if df.empty:
                return []
            
            klines = []
            for _, row in df.iterrows():
                klines.append({
                    'date': row['trade_date'],
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['vol']),
                    'amount': float(row['amount']),
                })
            return klines
        except Exception as e:
            print(f"  Tushare Pro K线失败: {e}")
            return []
    
    def _get_free_kline(self, code: str, period: str, count: int) -> List[Dict]:
        """旧版免费K线"""
        try:
            import tushare as ts
            df = ts.get_hist_data(code)
            if df is None or df.empty:
                return []
            
            klines = []
            for date, row in df.head(count).iterrows():
                klines.append({
                    'date': date,
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row['volume']),
                    'amount': 0,  # 旧版无成交额
                })
            return klines
        except Exception as e:
            print(f"  Tushare旧版K线失败: {e}")
            return []
    
    def get_financial_data(self, code: str) -> Dict:
        """
        获取财务数据（需要Pro版token）
        """
        if not self._pro:
            return {'code': code, 'source': 'tushare', 'error': '需要Pro版token'}
        
        cache_key = f"ts_fin_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        try:
            if code.startswith('6'):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"
            
            # 获取最新财务指标
            df = self._pro.fina_indicator(ts_code=ts_code, limit=1)
            if df.empty:
                return {'code': code, 'source': 'tushare', 'error': 'no data'}
            
            row = df.iloc[0]
            data = {
                'code': code,
                'source': 'tushare_pro',
                'roe': float(row.get('roe', 0)),
                'gross_margin': float(row.get('grossprofit_margin', 0)),
                'net_margin': float(row.get('profit_dedt', 0)),  # 扣非净利润
                'debt_ratio': float(row.get('debt_to_assets', 0)),
                'revenue_growth': float(row.get('q_sales_yoy', 0)),
                'profit_growth': float(row.get('q_profit_yoy', 0)),
                'eps': float(row.get('eps', 0)),
            }
            
            self._cache_set(cache_key, data)
            return data
            
        except Exception as e:
            print(f"  Tushare财务数据失败: {e}")
            return {'code': code, 'source': 'tushare', 'error': str(e)}
    
    def get_stock_basic(self, code: str) -> Dict:
        """获取股票基本信息（Pro版）"""
        if not self._pro:
            return {'code': code, 'error': '需要Pro版token'}
        
        try:
            if code.startswith('6'):
                ts_code = f"{code}.SH"
            else:
                ts_code = f"{code}.SZ"
            
            df = self._pro.stock_basic(ts_code=ts_code)
            if df.empty:
                return {'code': code, 'error': 'not found'}
            
            row = df.iloc[0]
            return {
                'code': code,
                'name': row.get('name', ''),
                'industry': row.get('industry', ''),
                'area': row.get('area', ''),
                'market': row.get('market', ''),
                'list_date': row.get('list_date', ''),
            }
        except Exception as e:
            return {'code': code, 'error': str(e)}


# 便捷函数
_adapter = None

def get_tushare_adapter() -> TushareAdapter:
    global _adapter
    if _adapter is None:
        _adapter = TushareAdapter()
    return _adapter

def get_realtime_quote(code: str) -> Optional[Dict]:
    return get_tushare_adapter().get_realtime_quote(code)


def is_tushare_available() -> bool:
    return get_tushare_adapter().is_available()


def is_tushare_pro_available() -> bool:
    return get_tushare_adapter().is_pro_available()


if __name__ == "__main__":
    adapter = TushareAdapter()
    print("Tushare 测试...")
    print(f"可用: {adapter.is_available()}")
    
    print("\n实时行情 (000001):")
    quote = adapter.get_realtime_quote('000001')
    if quote:
        print(f"  {quote['name']} ¥{quote['price']} ({quote['change_pct']:+.2f}%)")
        print(f"  量: {quote['volume']}, 额: {quote['amount']:.0f}")
        print(f"  买1: {quote['bid1']} x {quote['bid_vol1']}")
        print(f"  卖1: {quote['ask1']} x {quote['ask_vol1']}")
    else:
        print("  获取失败")
