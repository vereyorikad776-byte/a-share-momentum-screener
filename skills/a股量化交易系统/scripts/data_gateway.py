#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 统一数据网关 v2.0
多源并发 + 智能合并 + 分批限流

设计原则:
- 多数据源同时启用，不是线性降级
- 实时行情并发请求，取最快返回
- 财务数据多源合并，互补缺失字段
- 分批次扫描，避免限流拉黑
- iFinD付费放最后，作为兜底
"""

import requests
import json
import time
import concurrent.futures
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
import threading

class DataSource(Enum):
    """数据源枚举"""
    TUSHARE = "tushare"      # 实时行情（盘口）
    TENCENT = "tencent"      # 实时行情（速度快）
    MOOTDX = "mootdx"        # 通达信TCP（本地极速）
    BAOSTOCK = "baostock"    # 历史K线（专业）
    AKSHARE = "akshare"      # 备用行情（数据源多）
    FTSHARE = "ftshare"      # 财务数据（免费）
    TUSHARE_PRO = "tushare_pro"  # 财务/K线（需token）
    IFIND = "ifind"          # 深度数据（付费兜底）

# 数据源健康状态
@dataclass
class SourceHealth:
    """数据源健康状态"""
    source: DataSource
    available: bool = True
    last_success: float = 0
    last_fail: float = 0
    fail_count: int = 0
    avg_latency: float = 0
    total_calls: int = 0
    
    def record_success(self, latency: float):
        self.available = True
        self.last_success = time.time()
        self.fail_count = 0
        # 指数移动平均计算延迟
        if self.total_calls == 0:
            self.avg_latency = latency
        else:
            self.avg_latency = 0.7 * self.avg_latency + 0.3 * latency
        self.total_calls += 1
    
    def record_fail(self):
        self.fail_count += 1
        self.last_fail = time.time()
        if self.fail_count >= 3:
            self.available = False
    
    def is_healthy(self) -> bool:
        """检查是否健康（失败3次后冷却60秒）"""
        if self.available:
            return True
        # 冷却期后重试
        if time.time() - self.last_fail > 60:
            self.available = True
            self.fail_count = 0
            return True
        return False


@dataclass
class StockQuote:
    """实时行情数据"""
    code: str
    name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    turnover: float = 0.0
    bid1: float = 0.0
    ask1: float = 0.0
    bid_vol1: int = 0
    ask_vol1: int = 0
    high: float = 0.0
    low: float = 0.0
    open: float = 0.0
    pre_close: float = 0.0
    timestamp: str = ""
    sources: List[str] = field(default_factory=list)  # 哪些数据源提供了数据

    def merge(self, other: 'StockQuote'):
        """合并另一个Quote的数据（补全缺失字段）"""
        if other.name and not self.name:
            self.name = other.name
        if other.price and not self.price:
            self.price = other.price
        if other.change_pct and not self.change_pct:
            self.change_pct = other.change_pct
        if other.volume and not self.volume:
            self.volume = other.volume
        if other.turnover and not self.turnover:
            self.turnover = other.turnover
        # 盘口数据优先（tushare有盘口）
        if other.bid1 and (not self.bid1 or 'tushare' in other.sources):
            self.bid1 = other.bid1
            self.bid_vol1 = other.bid_vol1
        if other.ask1 and (not self.ask1 or 'tushare' in other.sources):
            self.ask1 = other.ask1
            self.ask_vol1 = other.ask_vol1
        # 记录来源
        for s in other.sources:
            if s not in self.sources:
                self.sources.append(s)


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


@dataclass
class FinancialData:
    """财务数据（多源合并）"""
    code: str
    # 盈利能力
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None
    net_margin: Optional[float] = None
    eps: Optional[float] = None
    # 成长性
    revenue_growth: Optional[float] = None
    profit_growth: Optional[float] = None
    # 偿债能力
    debt_ratio: Optional[float] = None
    # 现金流
    operating_cashflow: Optional[float] = None
    # 来源追踪
    field_sources: Dict[str, str] = field(default_factory=dict)
    
    def merge(self, other: 'FinancialData'):
        """合并另一个财务数据（按字段补全）"""
        for field_name in ['roe', 'roa', 'gross_margin', 'net_margin', 
                           'eps', 'revenue_growth', 'profit_growth',
                           'debt_ratio', 'operating_cashflow']:
            other_val = getattr(other, field_name)
            if other_val is not None and getattr(self, field_name) is None:
                setattr(self, field_name, other_val)
                self.field_sources[field_name] = other.field_sources.get(field_name, 'unknown')


class DataGatewayV2:
    """
    统一数据网关 v2.0 - 多源并发架构
    """
    
    def __init__(self):
        # 数据源健康状态
        self.health = {s: SourceHealth(s) for s in DataSource}
        
        # 缓存
        self.cache = {}
        self.cache_ttl = 60
        self._cache_lock = threading.Lock()
        
        # 限流配置
        self.batch_size = 5          # 每批处理5只
        self.batch_interval = 2.0    # 批次间隔2秒
        self.source_interval = 0.5   # 同一数据源请求间隔0.5秒
        self._last_request = {}      # 记录每个数据源最后请求时间
        
        # 并发配置
        self.max_workers = 3         # 并发线程数
        self.request_timeout = 8     # 单请求超时8秒
        
    def _get_cache(self, key: str) -> Optional[dict]:
        with self._cache_lock:
            if key in self.cache:
                data, ts = self.cache[key]
                if time.time() - ts < self.cache_ttl:
                    return data
                del self.cache[key]
            return None
    
    def _set_cache(self, key: str, data: dict):
        with self._cache_lock:
            self.cache[key] = (data, time.time())
    
    def _rate_limit(self, source: DataSource):
        """限流：确保同一数据源请求间隔"""
        last = self._last_request.get(source, 0)
        elapsed = time.time() - last
        if elapsed < self.source_interval:
            time.sleep(self.source_interval - elapsed)
        self._last_request[source] = time.time()
    
    def _fetch_with_timeout(self, fetch_fn, source: DataSource) -> Optional[Dict]:
        """带超时和错误处理的请求"""
        if not self.health[source].is_healthy():
            return None
        
        start = time.time()
        try:
            self._rate_limit(source)
            result = fetch_fn()
            latency = time.time() - start
            if result:
                self.health[source].record_success(latency)
                return result
            else:
                self.health[source].record_fail()
                return None
        except Exception as e:
            self.health[source].record_fail()
            print(f"  [{source.value}] 请求失败: {e}")
            return None
    
    # ==================== 实时行情 ====================
    
    def get_realtime_quote(self, code: str) -> Optional[StockQuote]:
        """
        获取实时行情 - 多源并发请求，智能合并
        
        策略:
        1. 并发请求 tushare + 腾讯 + akshare
        2. 取最快返回的作为基础
        3. 用其他源补全缺失字段
        """
        cache_key = f"quote_v2_{code}"
        cached = self._get_cache(cache_key)
        if cached:
            return StockQuote(**cached)
        
        # 定义要并发请求的数据源
        fetchers = []
        
        # tushare（盘口数据最全）
        if self.health[DataSource.TUSHARE].is_healthy():
            fetchers.append((DataSource.TUSHARE, lambda: self._fetch_tushare(code)))
        
        # 腾讯（速度快）
        if self.health[DataSource.TENCENT].is_healthy():
            fetchers.append((DataSource.TENCENT, lambda: self._fetch_tencent(code)))
        
        # akshare（备用）
        if self.health[DataSource.AKSHARE].is_healthy():
            fetchers.append((DataSource.AKSHARE, lambda: self._fetch_akshare(code)))
        
        # 并发执行
        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_source = {
                executor.submit(self._fetch_with_timeout, fn, src): src 
                for src, fn in fetchers
            }
            for future in concurrent.futures.as_completed(future_to_source, timeout=self.request_timeout):
                src = future_to_source[future]
                try:
                    result = future.result()
                    if result:
                        results[src] = result
                except Exception:
                    pass
        
        if not results:
            return None
        
        # 智能合并：tushare优先（有盘口），腾讯补全名称和速度
        merged = None
        
        # 优先用tushare做基础（有盘口数据）
        if DataSource.TUSHARE in results:
            merged = results[DataSource.TUSHARE]
        # 其次用腾讯
        elif DataSource.TENCENT in results:
            merged = results[DataSource.TENCENT]
        # 最后用akshare
        elif DataSource.AKSHARE in results:
            merged = results[DataSource.AKSHARE]
        
        if not merged:
            return None
        
        # 用其他源补全缺失字段
        for src, quote in results.items():
            if src != DataSource.TUSHARE:  # tushare已经是基础了
                merged.merge(quote)
        
        self._set_cache(cache_key, merged.__dict__)
        return merged
    
    def _fetch_tushare(self, code: str) -> Optional[StockQuote]:
        """从tushare获取"""
        try:
            from tushare_adapter import get_tushare_adapter
            adapter = get_tushare_adapter()
            if not adapter.is_available():
                return None
            
            data = adapter.get_realtime_quote(code)
            if not data:
                return None
            
            return StockQuote(
                code=code,
                name=data.get('name', ''),
                price=float(data.get('price', 0)),
                change_pct=float(data.get('change_pct', 0)),
                volume=int(data.get('volume', 0)),
                turnover=float(data.get('amount', 0)),
                bid1=float(data.get('bid1', 0)),
                ask1=float(data.get('ask1', 0)),
                bid_vol1=int(data.get('bid_vol1', 0)),
                ask_vol1=int(data.get('ask_vol1', 0)),
                high=float(data.get('high', 0)),
                low=float(data.get('low', 0)),
                open=float(data.get('open', 0)),
                pre_close=float(data.get('pre_close', 0)),
                timestamp=data.get('timestamp', time.strftime('%Y-%m-%d %H:%M:%S')),
                sources=['tushare']
            )
        except Exception:
            return None
    
    def _fetch_tencent(self, code: str) -> Optional[StockQuote]:
        """从腾讯获取"""
        try:
            if code.startswith('6'):
                full_code = f"sh{code}"
            else:
                full_code = f"sz{code}"
            
            resp = requests.get(f"https://qt.gtimg.cn/q={full_code}", timeout=5)
            resp.encoding = 'gbk'
            parts = resp.text.split('~')
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
                open=float(parts[5]),
                pre_close=float(parts[4]),
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                sources=['tencent']
            )
        except Exception:
            return None
    
    def _fetch_akshare(self, code: str) -> Optional[StockQuote]:
        """从akshare获取"""
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            row = df[df['代码'] == code]
            if row.empty:
                return None
            
            r = row.iloc[0]
            return StockQuote(
                code=code,
                name=r['名称'],
                price=float(r['最新价']),
                change_pct=float(r['涨跌幅']),
                volume=int(r['成交量']),
                turnover=float(r['成交额']),
                high=float(r['最高']),
                low=float(r['最低']),
                open=float(r['今开']),
                pre_close=float(r['昨收']),
                timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
                sources=['akshare']
            )
        except Exception:
            return None
    
    # ==================== K线数据 ====================
    
    def get_kline(self, code: str, period: str = "day", count: int = 60) -> List[KLine]:
        """
        获取K线 - Baostock优先，akshare备用
        """
        cache_key = f"kline_v2_{code}_{period}_{count}"
        cached = self._get_cache(cache_key)
        if cached:
            return [KLine(**k) for k in cached]
        
        # 优先Baostock（专业历史数据）
        klines = self._fetch_baostock_kline(code, period, count)
        if klines:
            self._set_cache(cache_key, [k.__dict__ for k in klines])
            return klines
        
        # 备用akshare
        klines = self._fetch_akshare_kline(code, period, count)
        if klines:
            self._set_cache(cache_key, [k.__dict__ for k in klines])
            return klines
        
        return []
    
    def _fetch_baostock_kline(self, code, period, count):
        try:
            import baostock as bs
            bs.login()
            
            if code.startswith('6'):
                full_code = f"sh.{code}"
            else:
                full_code = f"sz.{code}"
            
            freq = period[0] if period != "week" else "w"
            start = time.strftime('%Y-%m-%d', time.localtime(time.time() - count * 86400))
            end = time.strftime('%Y-%m-%d')
            
            rs = bs.query_history_k_data_plus(
                full_code,
                "date,open,high,low,close,volume,amount",
                start_date=start, end_date=end,
                frequency=freq, adjustflag="3"
            )
            
            klines = []
            while (rs.error_code == '0') & rs.next():
                row = rs.get_row_data()
                klines.append(KLine(
                    date=row[0], open=float(row[1]), high=float(row[2]),
                    low=float(row[3]), close=float(row[4]),
                    volume=int(row[5]), amount=float(row[6]) if row[6] else 0
                ))
            bs.logout()
            return klines
        except Exception:
            return []
    
    def _fetch_akshare_kline(self, code, period, count):
        try:
            import akshare as ak
            period_map = {'day': 'daily', 'week': 'weekly', 'month': 'monthly'}
            df = ak.stock_zh_a_hist(symbol=code, period=period_map.get(period, 'daily'),
                                    start_date="20240101", adjust="qfq")
            klines = []
            for _, row in df.tail(count).iterrows():
                klines.append(KLine(
                    date=row['日期'], open=float(row['开盘']), high=float(row['最高']),
                    low=float(row['最低']), close=float(row['收盘']),
                    volume=int(row['成交量']), amount=float(row['成交额'])
                ))
            return klines
        except Exception:
            return []
    
    # ==================== 财务数据 ====================
    
    def get_financial_data(self, code: str) -> FinancialData:
        """
        获取财务数据 - 多源合并策略
        
        优先级:
        1. FTShare（免费，结构化JSON，最稳定）
        2. tushare Pro（需token）
        3. iFinD（付费兜底）
        """
        cache_key = f"fin_v2_{code}"
        cached = self._get_cache(cache_key)
        if cached:
            return FinancialData(**cached)
        
        merged = FinancialData(code=code)
        
        # 1. FTShare（免费优先）
        ft_data = self._fetch_ftshare_financial(code)
        if ft_data:
            merged.merge(ft_data)
        
        # 2. tushare Pro（如有token）
        if not merged.roe or not merged.debt_ratio:
            ts_data = self._fetch_tushare_financial(code)
            if ts_data:
                merged.merge(ts_data)
        
        # 3. iFinD（付费兜底）
        missing_fields = [f for f in ['roe', 'gross_margin', 'net_margin', 'debt_ratio'] 
                         if getattr(merged, f) is None]
        if missing_fields:
            ifind_data = self._fetch_ifind_financial(code)
            if ifind_data:
                merged.merge(ifind_data)
        
        self._set_cache(cache_key, {
            'code': merged.code,
            'roe': merged.roe, 'roa': merged.roa,
            'gross_margin': merged.gross_margin, 'net_margin': merged.net_margin,
            'eps': merged.eps,
            'revenue_growth': merged.revenue_growth, 'profit_growth': merged.profit_growth,
            'debt_ratio': merged.debt_ratio,
            'operating_cashflow': merged.operating_cashflow,
            'field_sources': merged.field_sources,
        })
        return merged
    
    def _fetch_ftshare_financial(self, code: str) -> Optional[FinancialData]:
        try:
            from ftshare_adapter import get_full_financial_profile
            data = get_full_financial_profile(code)
            if not data or 'error' in data:
                return None
            
            return FinancialData(
                code=code,
                roe=data.get('roe'),
                revenue_growth=data.get('total_revenue_yoy'),
                profit_growth=data.get('net_profit_yoy'),
                eps=data.get('eps'),
                debt_ratio=data.get('debt_ratio'),
                operating_cashflow=data.get('operating_cashflow'),
                field_sources={
                    'roe': 'ftshare', 'revenue_growth': 'ftshare',
                    'profit_growth': 'ftshare', 'eps': 'ftshare',
                    'debt_ratio': 'ftshare', 'operating_cashflow': 'ftshare'
                }
            )
        except Exception:
            return None
    
    def _fetch_tushare_financial(self, code: str) -> Optional[FinancialData]:
        try:
            from tushare_adapter import get_tushare_adapter
            adapter = get_tushare_adapter()
            if not adapter.is_pro_available():
                return None
            
            data = adapter.get_financial_data(code)
            if not data or 'error' in data:
                return None
            
            fd = FinancialData(code=code)
            fd.roe = data.get('roe')
            fd.gross_margin = data.get('gross_margin')
            fd.net_margin = data.get('net_margin')
            fd.debt_ratio = data.get('debt_ratio')
            fd.revenue_growth = data.get('revenue_growth')
            fd.profit_growth = data.get('profit_growth')
            fd.eps = data.get('eps')
            
            for f in ['roe', 'gross_margin', 'net_margin', 'debt_ratio', 
                      'revenue_growth', 'profit_growth', 'eps']:
                if getattr(fd, f) is not None:
                    fd.field_sources[f] = 'tushare_pro'
            return fd
        except Exception:
            return None
    
    def _fetch_ifind_financial(self, code: str) -> Optional[FinancialData]:
        try:
            from ifind_adapter import get_financial_data
            data = get_financial_data(code)
            if not data or data.get('source') == 'mock':
                return None
            
            fd = FinancialData(code=code)
            fd.roe = data.get('roe')
            fd.roa = data.get('roa')
            fd.gross_margin = data.get('gross_margin')
            fd.net_margin = data.get('net_margin')
            fd.debt_ratio = data.get('debt_ratio')
            fd.revenue_growth = data.get('revenue_growth')
            fd.profit_growth = data.get('profit_growth')
            fd.operating_cashflow = data.get('operating_cashflow')
            
            for f in ['roe', 'roa', 'gross_margin', 'net_margin', 'debt_ratio',
                      'revenue_growth', 'profit_growth', 'operating_cashflow']:
                if getattr(fd, f) is not None:
                    fd.field_sources[f] = 'ifind'
            return fd
        except Exception:
            return None
    
    # ==================== 批量接口 ====================
    
    def get_batch_quotes(self, codes: List[str], 
                         batch_size: int = None,
                         interval: float = None) -> Dict[str, StockQuote]:
        """
        分批获取实时行情（防限流）
        
        Args:
            codes: 股票代码列表
            batch_size: 每批数量（默认5只）
            interval: 批次间隔秒数（默认2秒）
        """
        batch_size = batch_size or self.batch_size
        interval = interval or self.batch_interval
        
        results = {}
        total = len(codes)
        
        for i in range(0, total, batch_size):
            batch = codes[i:i+batch_size]
            print(f"  批次 {i//batch_size + 1}/{(total-1)//batch_size + 1}: {batch}")
            
            # 并发获取这批
            for code in batch:
                quote = self.get_realtime_quote(code)
                if quote:
                    results[code] = quote
            
            # 批次间隔（最后一批不sleep）
            if i + batch_size < total:
                time.sleep(interval)
        
        return results
    
    def get_batch_financial(self, codes: List[str],
                            batch_size: int = None,
                            interval: float = None) -> Dict[str, FinancialData]:
        """分批获取财务数据"""
        batch_size = batch_size or self.batch_size
        interval = interval or self.batch_interval
        
        results = {}
        total = len(codes)
        
        for i in range(0, total, batch_size):
            batch = codes[i:i+batch_size]
            print(f"  财务批次 {i//batch_size + 1}/{(total-1)//batch_size + 1}: {batch}")
            
            for code in batch:
                fin = self.get_financial_data(code)
                results[code] = fin
            
            if i + batch_size < total:
                time.sleep(interval)
        
        return results
    
    def get_health_report(self) -> Dict:
        """获取数据源健康报告"""
        return {
            src.value: {
                'available': h.available,
                'healthy': h.is_healthy(),
                'avg_latency_ms': round(h.avg_latency * 1000, 1) if h.avg_latency else None,
                'total_calls': h.total_calls,
                'fail_count': h.fail_count,
            }
            for src, h in self.health.items()
        }


# 全局单例
gateway = DataGatewayV2()


def get_quote(code: str) -> Optional[StockQuote]:
    """便捷函数：获取单票实时行情"""
    return gateway.get_realtime_quote(code)


def get_kline(code: str, period: str = "day", count: int = 60) -> List[KLine]:
    """便捷函数：获取K线"""
    return gateway.get_kline(code, period, count)


def get_financial_data(code: str) -> FinancialData:
    """便捷函数：获取财务数据"""
    return gateway.get_financial_data(code)


def get_batch_quotes(codes: List[str], batch_size: int = 5, interval: float = 2.0) -> Dict[str, StockQuote]:
    """便捷函数：分批获取行情"""
    return gateway.get_batch_quotes(codes, batch_size, interval)


if __name__ == "__main__":
    print("=== 数据网关 v2.0 测试 ===\n")
    
    gw = DataGatewayV2()
    
    # 单票测试
    print("1. 单票实时行情（多源并发）:")
    quote = gw.get_realtime_quote('000001')
    if quote:
        print(f"   {quote.name}({quote.code}): ¥{quote.price} {quote.change_pct:+.2f}%")
        print(f"   盘口: 买{quote.bid1}x{quote.bid_vol1} 卖{quote.ask1}x{quote.ask_vol1}")
        print(f"   数据来源: {', '.join(quote.sources)}")
    
    # 财务数据测试
    print("\n2. 财务数据（多源合并）:")
    fin = gw.get_financial_data('000001')
    print(f"   ROE: {fin.roe}% (来源: {fin.field_sources.get('roe', '?')})")
    print(f"   营收增长: {fin.revenue_growth}% (来源: {fin.field_sources.get('revenue_growth', '?')})")
    print(f"   负债率: {fin.debt_ratio}% (来源: {fin.field_sources.get('debt_ratio', '?')})")
    
    # 分批测试
    print("\n3. 分批获取（模拟10只）:")
    test_codes = ['000001', '000002', '600000', '600519', '000858',
                  '002594', '300750', '000983', '601318', '000333']
    batch = gw.get_batch_quotes(test_codes[:5], batch_size=2, interval=1.0)
    print(f"   成功获取 {len(batch)}/5 只")
    
    # 健康报告
    print("\n4. 数据源健康报告:")
    health = gw.get_health_report()
    for src, status in health.items():
        if status['total_calls'] > 0:
            print(f"   {src}: 延迟{status['avg_latency_ms']}ms 调用{status['total_calls']}次 失败{status['fail_count']}次")
