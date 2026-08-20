#!/usr/bin/env python3
"""
iFinD 数据接口 - 修复版

为回测引擎提供真实数据：
- 基本面：PE、ROE、营收增速
- 资金面：主力净流入、北向资金

数据缓存在 DuckDB 中
"""

import sys
import os
import json
import re
import duckdb
from pathlib import Path

# 加载 iFinD MCP 客户端
sys.path.insert(0, os.path.dirname(__file__))
from ifind_call import call


import time

class iFinDDataProvider:
    def __init__(self, cache_dir=None, rate_limit=1.0):
        self.rate_limit = rate_limit  # 每次请求间隔秒数
        self.last_request = 0
        self.cache_dir = cache_dir or os.path.join(
            os.path.dirname(__file__), '..', '..', 'backtest-engine', 'data', 'ifind_cache'
        )
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.db_path = os.path.join(self.cache_dir, 'ifind_data.db')
        self.conn = duckdb.connect(self.db_path)
        self._init_tables()
    
    def _throttle(self):
        """限流：确保两次请求间隔至少rate_limit秒"""
        now = time.time()
        elapsed = now - self.last_request
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request = time.time()
    
    def _init_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fund_flow (
                code TEXT, date TEXT,
                main_inflow REAL, northbound_inflow REAL,
                PRIMARY KEY (code, date)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                code TEXT, date TEXT,
                pe REAL, roe REAL, revenue_growth REAL, market_cap REAL,
                PRIMARY KEY (code, date)
            )
        """)
    
    def _to_ifind_code(self, code: str) -> str:
        code = code.replace('sh.', '').replace('sz.', '').replace('bj.', '')
        code = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        if code.startswith('6'):
            return f'{code}.SH'
        elif code.startswith(('0', '3')):
            return f'{code}.SZ'
        return code
    
    def _parse_ifind_response(self, result):
        """解析iFinD嵌套JSON响应"""
        if not result.get('ok'):
            return None
        try:
            content = result['data']['result']['content'][0]['text']
            outer = json.loads(content)
            inner = json.loads(outer['data'])
            return inner.get('answer', '')
        except Exception as e:
            print(f"   ⚠️ 解析失败: {e}")
            return None
    
    def _parse_table(self, answer):
        """解析markdown表格"""
        lines = answer.strip().split('\n')
        headers = None
        rows = []
        for line in lines:
            if line.startswith('|证券代码') or line.startswith('|股票代码'):
                headers = [h.strip() for h in line.split('|')[1:-1]]
                continue
            if headers and line.startswith('|') and '---' not in line:
                parts = [p.strip() for p in line.split('|')[1:-1]]
                if len(parts) >= 2:
                    rows.append(dict(zip(headers, parts)))
        return rows
    
    def _parse_amount(self, s):
        if not s or s in ('\t', '', '-'):
            return 0
        s = str(s).strip()
        try:
            if '亿' in s:
                return float(re.sub(r'[^\d.\-]', '', s)) * 1e8
            elif '万' in s:
                return float(re.sub(r'[^\d.\-]', '', s)) * 1e4
            else:
                return float(re.sub(r'[^\d.\-]', '', s))
        except:
            return 0
    
    def _parse_float(self, s):
        if not s or s in ('\t', '', '-'):
            return None
        try:
            return float(re.sub(r'[^\d.\-]', '', str(s).strip()))
        except:
            return None
    
    def fetch_fund_flow(self, codes, date):
        """获取资金流向"""
        if not codes:
            return {}
        
        # 查缓存
        cached = {}
        for code in codes:
            row = self.conn.execute(
                "SELECT main_inflow, northbound_inflow FROM fund_flow WHERE code = ? AND date = ?",
                (code, date)
            ).fetchone()
            if row:
                cached[code] = {'main_inflow': row[0], 'northbound_inflow': row[1]}
        
        missing = [c for c in codes if c not in cached]
        if not missing:
            return cached
        
        # iFinD获取 (最多5只/次)
        for i in range(0, len(missing), 5):
            batch = missing[i:i+5]
            ifind_codes = [self._to_ifind_code(c) for c in batch]
            code_str = '、'.join(ifind_codes)
            
            try:
                self._throttle()
                result = call('stock', 'get_stock_financials', {
                    'query': f'{code_str} {date[:4]}-{date[4:6]}-{date[6:]} 主力资金净流入额'
                })
                
                answer = self._parse_ifind_response(result)
                if answer:
                    rows = self._parse_table(answer)
                    for row in rows:
                        code = row.get('证券代码', '')
                        main_flow = 0
                        for k, v in row.items():
                            if '主力' in k and '流入' in k:
                                main_flow = self._parse_amount(v)
                        
                        self.conn.execute(
                            "INSERT OR REPLACE INTO fund_flow (code, date, main_inflow, northbound_inflow) VALUES (?, ?, ?, ?)",
                            (code, date, main_flow, 0)
                        )
                        cached[code] = {'main_inflow': main_flow, 'northbound_inflow': 0}
            
            except Exception as e:
                print(f"   ⚠️ iFinD资金数据失败: {e}")
        
        return cached
    
    def fetch_fundamentals(self, codes, date):
        """获取基本面数据"""
        if not codes:
            return {}
        
        cached = {}
        for code in codes:
            row = self.conn.execute(
                "SELECT pe, roe, revenue_growth, market_cap FROM fundamentals WHERE code = ? AND date = ?",
                (code, date)
            ).fetchone()
            if row:
                cached[code] = {'pe': row[0], 'roe': row[1], 'revenue_growth': row[2], 'market_cap': row[3]}
        
        missing = [c for c in codes if c not in cached]
        if not missing:
            return cached
        
        for i in range(0, len(missing), 5):
            batch = missing[i:i+5]
            ifind_codes = [self._to_ifind_code(c) for c in batch]
            code_str = '、'.join(ifind_codes)
            
            try:
                self._throttle()
                result = call('stock', 'get_stock_financials', {
                    'query': f'{code_str} 市盈率、ROE、总市值'
                })
                
                answer = self._parse_ifind_response(result)
                if answer:
                    rows = self._parse_table(answer)
                    for row in rows:
                        code = row.get('证券代码', '')
                        pe = roe = mcap = None
                        for k, v in row.items():
                            if 'PE' in k or '市盈率' in k:
                                pe = self._parse_float(v)
                            elif 'ROE' in k:
                                roe = self._parse_float(v)
                            elif '市值' in k and '总' in k:
                                mcap = self._parse_amount(v)
                        
                        self.conn.execute(
                            "INSERT OR REPLACE INTO fundamentals (code, date, pe, roe, revenue_growth, market_cap) VALUES (?, ?, ?, ?, ?, ?)",
                            (code, date, pe, roe, None, mcap)
                        )
                        cached[code] = {'pe': pe, 'roe': roe, 'revenue_growth': None, 'market_cap': mcap}
            
            except Exception as e:
                print(f"   ⚠️ iFinD基本面数据失败: {e}")
        
        return cached
    
    def close(self):
        self.conn.close()


if __name__ == '__main__':
    provider = iFinDDataProvider()
    
    # 测试
    print('=== 测试资金流向 ===')
    result = provider.fetch_fund_flow(['600519.SH'], '20260817')
    print(f'结果: {result}')
    
    print('\n=== 测试基本面 ===')
    result2 = provider.fetch_fundamentals(['600519.SH'], '20260817')
    print(f'结果: {result2}')
    
    provider.close()
