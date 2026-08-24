#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FTShare 数据源适配器
免费的 A股金融数据 MCP 服务
接口: https://market.ft.tech/gateway/mcp
"""

import requests
import json
import time
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class FTShareConfig:
    """FTShare配置"""
    base_url: str = "https://market.ft.tech/gateway/mcp"
    protocol_version: str = "2025-11-25"
    timeout: int = 30


class FTShareAdapter:
    """FTShare数据适配器 - MCP Streamable HTTP"""
    
    def __init__(self, config: Optional[FTShareConfig] = None):
        self.config = config or FTShareConfig()
        self._session_id: Optional[str] = None
        self._session_expires: float = 0
        self._cache = {}
        self._cache_ttl = 300
    
    def _parse_sse_json(self, text: str) -> Optional[dict]:
        """从 SSE 流中提取 JSON 数据"""
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('data:'):
                data = line[5:].strip()
                if data:
                    try:
                        return json.loads(data)
                    except:
                        pass
        return None
    
    def _ensure_session(self) -> bool:
        """确保 MCP session 有效"""
        if self._session_id and time.time() < self._session_expires:
            return True
        
        try:
            headers = {
                'Accept': 'application/json, text/event-stream',
                'Content-Type': 'application/json'
            }
            # initialize
            r = requests.post(self.config.base_url, json={
                'jsonrpc': '2.0', 'id': 1,
                'method': 'initialize',
                'params': {
                    'protocolVersion': self.config.protocol_version,
                    'capabilities': {},
                    'clientInfo': {'name': 'quant-trader', 'version': '1.0.0'}
                }
            }, headers=headers, timeout=self.config.timeout)
            
            self._session_id = r.headers.get('Mcp-Session-Id')
            if not self._session_id:
                return False
            
            # notifications/initialized
            h2 = {**headers, 'Mcp-Session-Id': self._session_id,
                  'MCP-Protocol-Version': self.config.protocol_version}
            requests.post(self.config.base_url,
                json={'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                headers=h2, timeout=10)
            
            self._session_expires = time.time() + 600  # 10分钟有效期
            return True
            
        except Exception as e:
            print(f"  FTShare session error: {e}")
            return False
    
    def _call_tool(self, tool_name: str, arguments: dict) -> Optional[dict]:
        """调用 FTShare MCP 工具"""
        if not self._ensure_session():
            return None
        
        try:
            headers = {
                'Accept': 'application/json, text/event-stream',
                'Content-Type': 'application/json',
                'Mcp-Session-Id': self._session_id,
                'MCP-Protocol-Version': self.config.protocol_version
            }
            r = requests.post(self.config.base_url, json={
                'jsonrpc': '2.0', 'id': int(time.time()),
                'method': 'tools/call',
                'params': {'name': tool_name, 'arguments': arguments}
            }, headers=headers, timeout=self.config.timeout)
            
            return self._parse_sse_json(r.text)
        except Exception as e:
            print(f"  FTShare call error: {e}")
            return None
    
    def _cache_get(self, key: str):
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None
    
    def _cache_set(self, key: str, data):
        self._cache[key] = (data, time.time())
    
    def _normalize_code(self, code: str) -> str:
        """标准化股票代码（添加后缀）"""
        if '.' in code:
            return code
        # 简单规则：6开头=上海，其他=深圳
        if code.startswith('6'):
            return f"{code}.SH"
        return f"{code}.SZ"
    
    def get_financial_data(self, code: str) -> Dict:
        """
        获取财务数据
        通过业绩快报 ft_earnings_reports_paginated
        """
        cache_key = f"ft_fin_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        full_code = self._normalize_code(code)
        
        resp = self._call_tool('ft_earnings_reports_paginated', {
            'stock_code': full_code,
            'page': 1,
            'page_size': 3
        })
        
        if not resp:
            return {'code': code, 'source': 'ftshare', 'error': 'request failed'}
        
        result = resp.get('result', {})
        sc = result.get('structuredContent', {})
        records = sc.get('data', [])
        
        if not records:
            return {'code': code, 'source': 'ftshare', 'error': 'no data'}
        
        # 取最新一期
        latest = records[0]
        
        data = {
            'code': code,
            'source': 'ftshare',
            'stock_code': latest.get('stock_code'),
            'stock_name': latest.get('stock_name'),
            'year': latest.get('year'),
            'report_type': latest.get('report_type_cn'),
            'publish_date': latest.get('publish_date'),
        }
        
        # 映射财务指标
        try:
            data['roe'] = float(latest.get('roe', 0))
        except: pass
        
        try:
            data['eps'] = float(latest.get('eps', 0))
        except: pass
        
        try:
            data['net_profit'] = float(latest.get('net_profit', 0))
        except: pass
        
        try:
            data['net_profit_yoy'] = float(latest.get('net_profit_yoy', 0))
        except: pass
        
        try:
            data['total_revenue'] = float(latest.get('total_revenue', 0))
        except: pass
        
        try:
            data['total_revenue_yoy'] = float(latest.get('total_revenue_yoy', 0))
        except: pass
        
        try:
            data['sh_netassets_ps'] = float(latest.get('sh_netassets_ps', 0))
        except: pass
        
        self._cache_set(cache_key, data)
        return data
    
    def get_balance_sheet(self, code: str) -> Dict:
        """获取资产负债表"""
        cache_key = f"ft_bal_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        full_code = self._normalize_code(code)
        resp = self._call_tool('ft_balance', {
            'stock_code': full_code,
            'page': 1,
            'page_size': 1
        })
        
        if not resp:
            return {'code': code, 'source': 'ftshare', 'error': 'request failed'}
        
        result = resp.get('result', {})
        sc = result.get('structuredContent', {})
        records = sc.get('data', [])
        
        if not records:
            return {'code': code, 'source': 'ftshare', 'error': 'no data'}
        
        data = {'code': code, 'source': 'ftshare'}
        latest = records[0]
        
        # 资产负债率 = 总负债 / 总资产
        try:
            total_liab = float(latest.get('total_liab', 0))
            total_assets = float(latest.get('total_assets', 0))
            if total_assets > 0:
                data['debt_ratio'] = round(total_liab / total_assets * 100, 2)
        except: pass
        
        self._cache_set(cache_key, data)
        return data
    
    def get_cashflow(self, code: str) -> Dict:
        """获取现金流量表"""
        cache_key = f"ft_cf_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        full_code = self._normalize_code(code)
        resp = self._call_tool('ft_cashflow', {
            'stock_code': full_code,
            'page': 1,
            'page_size': 1
        })
        
        if not resp:
            return {'code': code, 'source': 'ftshare', 'error': 'request failed'}
        
        result = resp.get('result', {})
        sc = result.get('structuredContent', {})
        records = sc.get('data', [])
        
        data = {'code': code, 'source': 'ftshare'}
        if records:
            latest = records[0]
            try:
                data['operating_cashflow'] = float(latest.get('net_cash_flows_oper_act', 0))
            except: pass
        
        self._cache_set(cache_key, data)
        return data
    
    def get_daily_ohlc(self, code: str, days: int = 20) -> List[Dict]:
        """获取历史K线"""
        cache_key = f"ft_ohlc_{code}_{days}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        full_code = self._normalize_code(code)
        resp = self._call_tool('daily_ohlc', {
            'symbol': full_code,
            'period': days
        })
        
        if not resp:
            return []
        
        result = resp.get('result', {})
        sc = result.get('structuredContent', {})
        records = sc.get('data', [])
        
        klines = []
        for r in records:
            klines.append({
                'date': r.get('date'),
                'open': r.get('open'),
                'high': r.get('high'),
                'low': r.get('low'),
                'close': r.get('close'),
                'volume': r.get('volume'),
                'amount': r.get('amount'),
            })
        
        self._cache_set(cache_key, klines)
        return klines


# 便捷函数
_adapter = None

def get_ftshare_adapter() -> FTShareAdapter:
    global _adapter
    if _adapter is None:
        _adapter = FTShareAdapter()
    return _adapter

def get_financial_data(code: str) -> Dict:
    return get_ftshare_adapter().get_financial_data(code)


def get_full_financial_profile(code: str) -> Dict:
    """
    获取完整财务画像（合并业绩快报 + 资产负债表 + 现金流量表）
    """
    adapter = get_ftshare_adapter()
    
    fin = adapter.get_financial_data(code)
    bal = adapter.get_balance_sheet(code)
    cf = adapter.get_cashflow(code)
    
    # 合并数据
    profile = {**fin}
    profile['debt_ratio'] = bal.get('debt_ratio')
    profile['operating_cashflow'] = cf.get('operating_cashflow')
    profile['data_sources'] = ['ft_earnings', 'ft_balance', 'ft_cashflow']
    
    return profile


if __name__ == "__main__":
    adapter = FTShareAdapter()
    print("测试 FTShare 数据源...")
    
    print("\n1. 平安银行财务数据:")
    data = adapter.get_financial_data('000001')
    print(f"  名称: {data.get('stock_name')}")
    print(f"  ROE: {data.get('roe')}%")
    print(f"  净利润增长: {data.get('net_profit_yoy')}%")
    print(f"  营收增长: {data.get('total_revenue_yoy')}%")
    print(f"  EPS: {data.get('eps')}")
    
    print("\n2. 资产负债表:")
    bal = adapter.get_balance_sheet('000001')
    print(f"  资产负债率: {bal.get('debt_ratio')}%")
    
    print("\n3. 完整画像:")
    profile = get_full_financial_profile('000001')
    print(json.dumps({k:v for k,v in profile.items() if k != 'raw'}, 
                     ensure_ascii=False, indent=2))
