#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iFinD 数据源适配器
支持两种模式：
1. 本地iFinD终端模式（Windows本地终端提供API服务）
2. HTTP API模式（直接调用iFinD云端接口）

使用前需配置：~/.openclaw/.env 或环境变量
"""

import os
import json
import requests
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class iFinDConfig:
    """iFinD配置"""
    mode: str           # 'terminal' | 'http' | 'mock'
    username: str
    password: str
    host: str = "127.0.0.1"
    port: int = 10080   # iFinD终端默认端口
    token: str = ""     # HTTP API模式用的token


class iFinDAdapter:
    """
    iFinD数据适配器
    
    由于iFinD终端是Windows软件，Linux服务器无法直接安装。
    提供三种接入方案：
    """
    
    def __init__(self, config: Optional[iFinDConfig] = None):
        self.config = config or self._load_config()
        self.mock_mode = self.config.mode == 'mock'
        self._token = None
        
    def _load_config(self) -> iFinDConfig:
        """从环境变量或配置文件加载"""
        # 优先环境变量
        mode = os.getenv('IFIND_MODE', 'mock')
        username = os.getenv('IFIND_USER', '')
        password = os.getenv('IFIND_PASS', '')
        host = os.getenv('IFIND_HOST', '127.0.0.1')
        port = int(os.getenv('IFIND_PORT', '10080'))
        token = os.getenv('IFIND_TOKEN', '')
        
        # 其次配置文件
        env_file = os.path.expanduser('~/.openclaw/.env')
        if os.path.exists(env_file):
            with open(env_file) as f:
                for line in f:
                    if '=' in line and not line.startswith('#'):
                        key, val = line.strip().split('=', 1)
                        if key == 'IFIND_MODE':
                            mode = val
                        elif key == 'IFIND_USER':
                            username = val
                        elif key == 'IFIND_PASS':
                            password = val
                        elif key == 'IFIND_HOST':
                            host = val
                        elif key == 'IFIND_PORT':
                            port = int(val)
                        elif key == 'IFIND_TOKEN':
                            token = val
        
        return iFinDConfig(mode=mode, username=username, password=password,
                          host=host, port=port, token=token)
    
    def is_available(self) -> bool:
        """检查iFinD是否可用"""
        if self.mock_mode:
            return True
        
        try:
            if self.config.mode == 'terminal':
                # 检查iFinD终端API服务是否可达
                resp = requests.get(f"http://{self.config.host}:{self.config.port}/api/v1/status",
                                   timeout=3)
                return resp.status_code == 200
            elif self.config.mode == 'http':
                # 检查HTTP API
                return bool(self.config.token)
        except Exception:
            pass
        
        return False
    
    def get_financial_data(self, code: str) -> Dict:
        """
        获取详细财务数据
        
        返回：
        - ROE / ROA / 毛利率 / 净利率
        - 营收增长 / 净利润增长
        - 现金流 / 自由现金流
        - 资产负债率 / 有息负债
        """
        if self.mock_mode:
            return self._mock_financial(code)
        
        # 实际iFinD调用
        return self._call_ifind('financial', {'code': code})
    
    def get_institution_holdings(self, code: str) -> Dict:
        """
        获取机构持仓数据
        
        返回：
        - 基金持仓比例
        - 机构数量变化
        - 北向资金持股
        - 龙虎榜数据
        """
        if self.mock_mode:
            return self._mock_institution(code)
        
        return self._call_ifind('institution', {'code': code})
    
    def get_north_flow(self, code: str, days: int = 30) -> List[Dict]:
        """
        获取北向资金流向
        
        返回每日北向资金流入/流出明细
        """
        if self.mock_mode:
            return self._mock_north_flow(code, days)
        
        return self._call_ifind('north_flow', {'code': code, 'days': days})
    
    def get_sector_data(self, sector: str) -> Dict:
        """
        获取行业数据
        
        返回：
        - 行业规模及增速
        - 竞争格局
        - 政策环境
        """
        if self.mock_mode:
            return self._mock_sector(sector)
        
        return self._call_ifind('sector', {'sector': sector})
    
    def get_quote(self, code: str) -> Optional[Dict]:
        """
        获取实时行情（iFinD增强版）
        返回比腾讯更完整的字段
        """
        if self.mock_mode:
            return None  # 让网关 fallback 到腾讯
        
        try:
            data = self._call_ifind('quote', {'code': code})
            if data and 'price' in data:
                return data
        except Exception as e:
            print(f"iFinD行情获取失败: {e}")
        
        return None
    
    def get_kline_ifind(self, code: str, period: str = "day", count: int = 60) -> List[Dict]:
        """
        获取K线数据（iFinD版，数据更全）
        """
        if self.mock_mode:
            return []
        
        try:
            return self._call_ifind('kline', {
                'code': code,
                'period': period,
                'count': count
            })
        except Exception as e:
            print(f"iFinD K线获取失败: {e}")
            return []
    
    def get_sector_ranking(self, sector: str, metric: str = "roe") -> List[Dict]:
        """
        获取行业内股票排名
        """
        if self.mock_mode:
            return []
        
        try:
            return self._call_ifind('sector_ranking', {
                'sector': sector,
                'metric': metric
            })
        except Exception as e:
            print(f"iFinD行业排名获取失败: {e}")
            return []
    
    def get_estimates(self, code: str) -> Dict:
        """
        获取机构一致预期
        """
        if self.mock_mode:
            return {}
        
        try:
            return self._call_ifind('estimates', {'code': code})
        except Exception as e:
            print(f"iFinD一致预期获取失败: {e}")
            return {}
    
    def get_announcements(self, code: str, days: int = 30) -> List[Dict]:
        """
        获取公司公告
        """
        if self.mock_mode:
            return []
        
        try:
            return self._call_ifind('announcements', {
                'code': code,
                'days': days
            })
        except Exception as e:
            print(f"iFinD公告获取失败: {e}")
            return []
    
    def _call_ifind(self, endpoint: str, params: Dict):
        """调用iFinD API"""
        if self.config.mode == 'terminal':
            url = f"http://{self.config.host}:{self.config.port}/api/v1/{endpoint}"
            resp = requests.post(url, json=params, timeout=30)
            return resp.json()
        elif self.config.mode == 'http':
            # iFinD HTTP API调用
            headers = {'Authorization': f'Bearer {self.config.token}'}
            url = f"https://api.ifind.com/v1/{endpoint}"
            resp = requests.post(url, json=params, headers=headers, timeout=30)
            return resp.json()
        else:
            raise RuntimeError(f"Unknown mode: {self.config.mode}")
    
    # Mock 数据（用于测试/未配置时）
    def _mock_financial(self, code: str) -> Dict:
        return {
            'code': code,
            'roe': 12.5,
            'roa': 8.3,
            'gross_margin': 35.2,
            'net_margin': 15.8,
            'revenue_growth': 22.1,
            'profit_growth': 18.5,
            'operating_cashflow': 1250000000,
            'free_cashflow': 850000000,
            'debt_ratio': 42.3,
            'interest_debt': 3200000000,
            'source': 'mock'
        }
    
    def _mock_institution(self, code: str) -> Dict:
        return {
            'code': code,
            'fund_holding_pct': 8.5,
            'institution_count': 45,
            'institution_change': +3,
            'north_holding_pct': 2.1,
            'source': 'mock'
        }
    
    def _mock_north_flow(self, code: str, days: int) -> List[Dict]:
        import random
        from datetime import datetime, timedelta
        
        results = []
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            results.append({
                'date': date,
                'inflow': round(random.uniform(-5000, 8000), 2),
                'outflow': round(random.uniform(0, 5000), 2),
                'net': round(random.uniform(-3000, 5000), 2),
                'source': 'mock'
            })
        return results
    
    def _mock_sector(self, sector: str) -> Dict:
        return {
            'sector': sector,
            'size': 5000,
            'growth': 15.2,
            'cr5': 35.0,
            'policy': 'support',
            'source': 'mock'
        }


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


def get_institution_holdings(code: str) -> Dict:
    return get_ifind_adapter().get_institution_holdings(code)


if __name__ == "__main__":
    adapter = iFinDAdapter()
    
    print(f"iFinD 模式: {adapter.config.mode}")
    print(f"可用状态: {adapter.is_available()}")
    
    if adapter.is_available():
        print("\n测试获取财务数据:")
        data = adapter.get_financial_data("000983")
        print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("\niFinD 未配置，当前使用Mock模式")
        print("请配置环境变量或 ~/.openclaw/.env:")
        print("  IFIND_MODE=terminal|http|mock")
        print("  IFIND_USER=你的用户名")
        print("  IFIND_PASS=你的密码")
        print("  IFIND_HOST=127.0.0.1 (终端模式)")
        print("  IFIND_PORT=10080 (终端模式)")
        print("  IFIND_TOKEN=你的API Token (HTTP模式)")
