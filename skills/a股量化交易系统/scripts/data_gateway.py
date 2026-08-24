#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 统一数据网关
自动降级链：腾讯 → iFinD → Baostock → akshare
"""

import requests
import json
import time
from typing import Dict, List, Optional, Union
from dataclasses import dataclass
from enum import Enum

class DataSource(Enum):
    TENCENT = "tencent"
    IFIND = "ifind"
    BAOSTOCK = "baostock"
    AKSHARE = "akshare"
    FTSHARE = "ftshare"
    IWENCAI = "iwencai"

@dataclass
class StockQuote:
    """实时行情数据"""
    code: str
    name: str
    price: float
    change_pct: float
    volume: int
    turnover: float
    bid1: float
    ask1: float
    high: float
    low: float
    open: float
    pre_close: float
    timestamp: str
    source: str

@dataclass
class KLine:
    """K线数据"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float

class DataGateway:
    """统一数据网关"""
    
    def __init__(self):
        # 数据源优先级：免费先用，付费的iFinD放最后作为增强
        self.source_priority = [
            DataSource.TENCENT,    # 免费实时行情
            DataSource.BAOSTOCK,   # 免费历史数据
            DataSource.AKSHARE,    # 免费备用
            DataSource.IFIND       # 付费增强（最后兜底）
        ]
        self.cache = {}
        self.cache_ttl = 60  # 缓存60秒
        
    def _get_cache(self, key: str) -> Optional[dict]:
        """获取缓存"""
        if key in self.cache:
            data, ts = self.cache[key]
            if time.time() - ts < self.cache_ttl:
                return data
        return None
    
    def _set_cache(self, key: str, data: dict):
        """设置缓存"""
        self.cache[key] = (data, time.time())
    
    def get_realtime_quote(self, code: str) -> Optional[StockQuote]:
        """
        获取实时行情
        
        Args:
            code: 股票代码，如 "000983"
            
        Returns:
            StockQuote对象或None
        """
        cache_key = f"quote_{code}"
        cached = self._get_cache(cache_key)
        if cached:
            return StockQuote(**cached)
        
        # 尝试各数据源
        for source in self.source_priority:
            try:
                if source == DataSource.TENCENT:
                    quote = self._fetch_tencent(code)
                elif source == DataSource.IFIND:
                    quote = self._fetch_ifind(code)
                elif source == DataSource.BAOSTOCK:
                    quote = self._fetch_baostock(code)
                elif source == DataSource.AKSHARE:
                    quote = self._fetch_akshare(code)
                else:
                    continue
                    
                if quote:
                    self._set_cache(cache_key, quote.__dict__)
                    return quote
                    
            except Exception as e:
                print(f"数据源 {source.value} 获取失败: {e}")
                continue
                
        return None
    
    def _fetch_tencent(self, code: str) -> Optional[StockQuote]:
        """从腾讯财经获取实时行情"""
        # 沪深股票代码格式转换
        if code.startswith('6'):
            full_code = f"sh{code}"
        else:
            full_code = f"sz{code}"
            
        url = f"https://qt.gtimg.cn/q={full_code}"
        
        try:
            resp = requests.get(url, timeout=5)
            resp.encoding = 'gbk'
            data = resp.text
            
            # 解析腾讯返回的数据格式
            # 格式: v_sh600000="1~浦发银行~600000~..."
            parts = data.split('~')
            if len(parts) < 45:
                return None
                
            return StockQuote(
                code=code,
                name=parts[1],
                price=float(parts[3]),
                change_pct=float(parts[5]),
                volume=int(parts[6]),
                turnover=float(parts[7]),
                bid1=float(parts[9]),
                ask1=float(parts[19]),
                high=float(parts[33]),
                low=float(parts[34]),
                open=float(parts[5]),  # 需要调整
                pre_close=float(parts[4]),
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                source='tencent'
            )
        except Exception as e:
            print(f"腾讯数据获取失败: {e}")
            return None
    
    def _fetch_ifind(self, code: str) -> Optional[StockQuote]:
        """从iFinD获取（优先，数据最全）"""
        try:
            from ifind_adapter import get_ifind_adapter
            adapter = get_ifind_adapter()
            
            if not adapter.is_available():
                return None
            
            data = adapter.get_quote(code)
            if not data:
                return None
            
            return StockQuote(
                code=code,
                name=data.get('name', ''),
                price=float(data.get('price', 0)),
                change_pct=float(data.get('change_pct', 0)),
                volume=int(data.get('volume', 0)),
                turnover=float(data.get('turnover', 0)),
                bid1=float(data.get('bid1', 0)),
                ask1=float(data.get('ask1', 0)),
                high=float(data.get('high', 0)),
                low=float(data.get('low', 0)),
                open=float(data.get('open', 0)),
                pre_close=float(data.get('pre_close', 0)),
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                source='ifind'
            )
        except Exception as e:
            print(f"iFinD获取失败: {e}")
            return None
    
    def _fetch_baostock(self, code: str) -> Optional[StockQuote]:
        """从Baostock获取"""
        try:
            import baostock as bs
            
            # 登录
            bs.login()
            
            # 获取实时行情（baostock主要是历史数据，实时需其他方式）
            # 这里简化处理
            bs.logout()
            return None
        except:
            return None
    
    def _fetch_akshare(self, code: str) -> Optional[StockQuote]:
        """从akshare获取（备用）"""
        try:
            import akshare as ak
            
            # 获取实时行情
            df = ak.stock_zh_a_spot_em()
            row = df[df['代码'] == code]
            
            if row.empty:
                return None
                
            row = row.iloc[0]
            
            return StockQuote(
                code=code,
                name=row['名称'],
                price=float(row['最新价']),
                change_pct=float(row['涨跌幅']),
                volume=int(row['成交量']),
                turnover=float(row['成交额']),
                bid1=float(row.get('买一', 0)),
                ask1=float(row.get('卖一', 0)),
                high=float(row['最高']),
                low=float(row['最低']),
                open=float(row['今开']),
                pre_close=float(row['昨收']),
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                source='akshare'
            )
        except Exception as e:
            print(f"akshare获取失败: {e}")
            return None
    
    def get_kline(self, code: str, period: str = "day", count: int = 60) -> List[KLine]:
        """
        获取K线数据
        
        Args:
            code: 股票代码
            period: 周期 day/week/month
            count: 获取条数
            
        Returns:
            KLine列表
        """
        cache_key = f"kline_{code}_{period}_{count}"
        cached = self._get_cache(cache_key)
        if cached:
            return [KLine(**k) for k in cached]
        
        # 优先使用baostock获取历史K线
        try:
            import baostock as bs
            bs.login()
            
            if code.startswith('6'):
                full_code = f"sh.{code}"
            else:
                full_code = f"sz.{code}"
            
            rs = bs.query_history_k_data_plus(
                full_code,
                "date,open,high,low,close,volume,amount",
                start_date=(time.strftime('%Y-%m-%d', time.localtime(time.time()-count*86400))),
                end_date=time.strftime('%Y-%m-%d'),
                frequency=period[0] if period != "week" else "w",
                adjustflag="3"  # 复权
            )
            
            klines = []
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                klines.append(KLine(
                    date=row[0],
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=int(row[5]),
                    amount=float(row[6]) if row[6] else 0
                ))
            
            bs.logout()
            
            if klines:
                self._set_cache(cache_key, [k.__dict__ for k in klines])
                return klines
                
        except Exception as e:
            print(f"Baostock K线获取失败: {e}")
        
        # 备用：akshare
        try:
            import akshare as ak
            
            if period == "day":
                df = ak.stock_zh_a_hist(symbol=code, period="daily", start_date="20240101", adjust="qfq")
            elif period == "week":
                df = ak.stock_zh_a_hist(symbol=code, period="weekly", start_date="20240101", adjust="qfq")
            else:
                df = ak.stock_zh_a_hist(symbol=code, period="monthly", start_date="20240101", adjust="qfq")
            
            klines = []
            for _, row in df.tail(count).iterrows():
                klines.append(KLine(
                    date=row['日期'],
                    open=float(row['开盘']),
                    high=float(row['最高']),
                    low=float(row['最低']),
                    close=float(row['收盘']),
                    volume=int(row['成交量']),
                    amount=float(row['成交额'])
                ))
            
            if klines:
                self._set_cache(cache_key, [k.__dict__ for k in klines])
                return klines
                
        except Exception as e:
            print(f"akshare K线获取失败: {e}")
        
        return []
    
    def get_batch_quotes(self, codes: List[str]) -> Dict[str, StockQuote]:
        """批量获取实时行情"""
        results = {}
        for code in codes:
            quote = self.get_realtime_quote(code)
            if quote:
                results[code] = quote
        return results


# 全局单例
gateway = DataGateway()


def get_quote(code: str) -> Optional[StockQuote]:
    """便捷函数：获取单票实时行情"""
    return gateway.get_realtime_quote(code)


def get_kline(code: str, period: str = "day", count: int = 60) -> List[KLine]:
    """便捷函数：获取K线"""
    return gateway.get_kline(code, period, count)


if __name__ == "__main__":
    # 测试
    quote = get_quote("000983")
    if quote:
        print(f"{quote.name}({quote.code}): ¥{quote.price} {quote.change_pct:+.2f}%")
    else:
        print("获取失败")
