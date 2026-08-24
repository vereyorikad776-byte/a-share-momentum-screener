#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iFinD 数据源适配器 v2.0
通过 MCP 协议调用 iFinD 数据服务
"""

import os
import sys
import json
import time
from typing import Dict, List, Optional
from dataclasses import dataclass

# 尝试导入 MCP call 模块
# MCP skill 在 workspace/skills/ifind-finance-data 中
_WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
IFIND_SKILL_DIR = os.path.join(_WORKSPACE, 'skills', 'ifind-finance-data')
sys.path.insert(0, IFIND_SKILL_DIR)

try:
    import call as ifind_call
    MCP_AVAILABLE = True
except Exception as e:
    print(f"  [debug] MCP import failed: {e}")
    MCP_AVAILABLE = False


@dataclass
class iFinDConfig:
    """iFinD配置"""
    mode: str = 'mcp'  # 'mcp' | 'mock'


class iFinDAdapter:
    """iFinD数据适配器 v2.0 - MCP模式"""
    
    def __init__(self, config: Optional[iFinDConfig] = None):
        self.config = config or iFinDConfig()
        self.mock_mode = self.config.mode == 'mock' or not MCP_AVAILABLE
        self._cache = {}
        self._cache_ttl = 300  # 5分钟缓存
        
    def is_available(self) -> bool:
        """检查iFinD是否可用"""
        if self.mock_mode:
            return True
        return MCP_AVAILABLE
    
    def _cache_get(self, key: str):
        """获取缓存"""
        if key in self._cache:
            data, ts = self._cache[key]
            if time.time() - ts < self._cache_ttl:
                return data
        return None
    
    def _cache_set(self, key: str, data):
        """设置缓存"""
        self._cache[key] = (data, time.time())
    
    def _call_mcp(self, server_type: str, tool_name: str, params: dict) -> Optional[dict]:
        """调用iFinD MCP工具"""
        if not MCP_AVAILABLE:
            return None
        
        try:
            result = ifind_call.call(server_type, tool_name, params)
            if result.get('ok'):
                return result.get('data', {})
            else:
                print(f"  iFinD MCP调用失败: {result.get('error')}")
                return None
        except Exception as e:
            print(f"  iFinD MCP异常: {e}")
            return None
    
    def _extract_content(self, mcp_response: dict) -> str:
        """从MCP响应中提取文本内容"""
        if not mcp_response:
            return ""
        
        result = mcp_response.get('result', {})
        content = result.get('content', [])
        
        for item in content:
            if item.get('type') == 'text':
                return item.get('text', '')
        
        return str(result)
    
    def get_financial_data(self, code: str) -> Dict:
        """
        获取详细财务数据
        ROE / ROA / 毛利率 / 净利率 / 营收增长 / 现金流 / 资产负债率
        """
        cache_key = f"fin_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        if self.mock_mode:
            data = self._mock_financial(code)
            self._cache_set(cache_key, data)
            return data
        
        # 通过MCP获取
        name = self._get_stock_name(code)
        query = f"{name}({code})最近一期的ROE、ROA、毛利率、净利率、营收同比增长率、净利润增长率、经营活动现金流、资产负债率"
        
        resp = self._call_mcp('stock', 'get_stock_financials', {'query': query})
        text = self._extract_content(resp)
        
        # 解析返回的文本（简化解析）
        data = self._parse_financial_text(text, code)
        data['raw'] = text
        
        self._cache_set(cache_key, data)
        return data
    
    def get_stock_summary(self, code: str) -> Dict:
        """获取股票信息摘要"""
        cache_key = f"sum_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        if self.mock_mode:
            return self._mock_summary(code)
        
        name = self._get_stock_name(code)
        query = f"{name}({code})最新估值水平、近期行情走势、最新财务指标"
        
        resp = self._call_mcp('stock', 'get_stock_summary', {'query': query})
        text = self._extract_content(resp)
        
        data = {'code': code, 'raw': text}
        self._cache_set(cache_key, data)
        return data
    
    def get_stock_performance(self, code: str, days: int = 20) -> Dict:
        """获取历史行情和技术指标"""
        cache_key = f"perf_{code}_{days}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        if self.mock_mode:
            return self._mock_performance(code)
        
        name = self._get_stock_name(code)
        end = time.strftime('%Y%m%d')
        start = time.strftime('%Y%m%d', time.localtime(time.time() - days*86400))
        query = f"{name}({code}){start}-{end}的涨跌幅、换手率、MACD、KDJ、RSI"
        
        resp = self._call_mcp('stock', 'get_stock_performance', {'query': query})
        text = self._extract_content(resp)
        
        data = {'code': code, 'raw': text}
        self._cache_set(cache_key, data)
        return data
    
    def get_risk_indicators(self, code: str) -> Dict:
        """获取风险指标（beta、波动率、夏普比率）"""
        cache_key = f"risk_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        if self.mock_mode:
            return self._mock_risk(code)
        
        name = self._get_stock_name(code)
        query = f"{name}({code})过去1年的beta、年化波动率、夏普比率（以沪深300作为市场基准）"
        
        resp = self._call_mcp('stock', 'get_risk_indicators', {'query': query})
        text = self._extract_content(resp)
        
        data = {'code': code, 'raw': text}
        self._cache_set(cache_key, data)
        return data
    
    def get_shareholders(self, code: str) -> Dict:
        """获取股东结构数据"""
        cache_key = f"holder_{code}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached
        
        if self.mock_mode:
            return self._mock_shareholders(code)
        
        name = self._get_stock_name(code)
        query = f"{name}({code})流通股占比、前5大股东持股占比、机构持股信息"
        
        resp = self._call_mcp('stock', 'get_stock_shareholders', {'query': query})
        text = self._extract_content(resp)
        
        data = {'code': code, 'raw': text}
        self._cache_set(cache_key, data)
        return data
    
    def search_stocks(self, query: str) -> List[Dict]:
        """智能选股"""
        if self.mock_mode:
            return []
        
        resp = self._call_mcp('stock', 'search_stocks', {'query': query})
        text = self._extract_content(resp)
        
        # 尝试解析股票列表
        stocks = []
        # 简单解析：找股票代码格式
        import re
        codes = re.findall(r'(\d{6})', text)
        for c in set(codes):
            stocks.append({'code': c, 'source': 'ifind_search'})
        
        return stocks
    
    def _get_stock_name(self, code: str) -> str:
        """获取股票名称（简单映射，实际可查询）"""
        name_map = {
            '000001': '平安银行', '000002': '万科A', '000983': '山西焦煤',
            '600000': '浦发银行', '600519': '贵州茅台', '601318': '中国平安',
            '000858': '五粮液', '002594': '比亚迪', '300750': '宁德时代'
        }
        return name_map.get(code, code)
    
    def _parse_financial_text(self, text: str, code: str) -> Dict:
        """从财务文本中解析关键指标"""
        import re
        
        data = {'code': code, 'source': 'ifind_mcp'}
        
        # 尝试从JSON解析
        try:
            json_data = json.loads(text)
            inner = json_data.get('data', '{}')
            if isinstance(inner, str):
                inner = json.loads(inner)
            answer = inner.get('answer', '')
            
            # JSON转义后 \\n 是文字而非换行符，需先替换
            answer = answer.replace('\\n', '\n').replace('\\t', '\t')
            lines = [l.strip() for l in answer.strip().split('\n') if l.strip()]
            
            if len(lines) >= 3:
                # 严格按位置对应（保留空值）
                header_parts = lines[0].split('|')
                data_parts = lines[-1].split('|')  # 数据行是最后一行
                
                for i in range(len(header_parts)):
                    h = header_parts[i].strip()
                    if not h or h.startswith('---') or h == '证券代码' or h == '证券简称':
                        continue
                    if i < len(data_parts):
                        val_str = data_parts[i].strip()
                        if not val_str:
                            continue  # 空值跳过
                        
                        # ROE
                        if '净资产收益率ROE' in h or h == 'ROE':
                            try: data['roe'] = float(val_str)
                            except: pass
                        # ROA
                        elif '总资产净利率ROA' in h or h == 'ROA':
                            try: data['roa'] = float(val_str)
                            except: pass
                        # 毛利率
                        elif '毛利率' in h and '净利率' not in h:
                            try: data['gross_margin'] = float(val_str)
                            except: pass
                        # 净利率
                        elif '净利率' in h and '毛利率' not in h:
                            try: data['net_margin'] = float(val_str)
                            except: pass
                        # 资产负债率
                        elif '资产负债率' in h:
                            try: data['debt_ratio'] = float(val_str)
                            except: pass
                        # 营收增长
                        elif ('营业收入' in h or '营业总收入' in h) and '增长' in h:
                            try: data['revenue_growth'] = float(val_str)
                            except: pass
                        # 净利润增长
                        elif '净利润' in h and '增长' in h and '归属' not in h:
                            try: data['profit_growth'] = float(val_str)
                            except: pass
                        # 归属母公司净利润增长
                        elif '归属母公司' in h and '增长' in h:
                            try:
                                if data.get('profit_growth') is None:
                                    data['profit_growth'] = float(val_str)
                            except: pass
                        # 现金流量
                        elif '现金流量' in h or '现金流' in h:
                            try:
                                val_clean = val_str.replace('亿', 'e8').replace('万', 'e4').replace(',', '')
                                data['operating_cashflow'] = float(val_clean)
                            except: pass
                        
        except Exception as e:
            # Fallback: 正则匹配
            patterns = {
                'roe': r'净资产收益率ROE.*?([\d.]+)',
                'roa': r'总资产净利率ROA.*?([\d.]+)',
                'gross_margin': r'毛利率.*?([\d.]+)',
                'net_margin': r'净利率.*?([\d.]+)',
                'revenue_growth': r'营收.*增长.*?([\d.]+)',
                'profit_growth': r'净利润.*增长.*?([\d.]+)',
                'debt_ratio': r'资产负债率.*?([\d.]+)',
            }
            for key, pattern in patterns.items():
                match = re.search(pattern, text)
                if match:
                    try:
                        data[key] = float(match.group(1))
                    except:
                        pass
        
        return data
    
    # Mock 数据（降级用）
    def _mock_financial(self, code: str) -> Dict:
        return {
            'code': code, 'source': 'mock',
            'roe': 12.5, 'roa': 8.3, 'gross_margin': 35.2,
            'net_margin': 15.8, 'revenue_growth': 22.1,
            'profit_growth': 18.5, 'debt_ratio': 42.3
        }
    
    def _mock_summary(self, code: str) -> Dict:
        return {'code': code, 'source': 'mock', 'raw': 'mock summary'}
    
    def _mock_performance(self, code: str) -> Dict:
        return {'code': code, 'source': 'mock', 'raw': 'mock performance'}
    
    def _mock_risk(self, code: str) -> Dict:
        return {'code': code, 'source': 'mock', 'beta': 1.0, 'volatility': 0.25}
    
    def _mock_shareholders(self, code: str) -> Dict:
        return {'code': code, 'source': 'mock', 'fund_pct': 5.0}


# 便捷函数
_adapter = None

def get_ifind_adapter() -> iFinDAdapter:
    global _adapter
    if _adapter is None:
        _adapter = iFinDAdapter()
    return _adapter

def is_ifind_available() -> bool:
    return get_ifind_adapter().is_available()

def get_financial_data(code: str) -> Dict:
    return get_ifind_adapter().get_financial_data(code)

def get_stock_summary(code: str) -> Dict:
    return get_ifind_adapter().get_stock_summary(code)


if __name__ == "__main__":
    adapter = iFinDAdapter()
    print(f"iFinD MCP 可用: {adapter.is_available()}")
    print(f"MCP模块加载: {MCP_AVAILABLE}")
    
    if adapter.is_available() and not adapter.mock_mode:
        print("\n测试获取平安银行财务数据:")
        data = adapter.get_financial_data('000001')
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("\niFinD 未配置或MCP不可用，当前使用Mock模式")
