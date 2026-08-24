#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 选股筛股主入口
筛选/排行/预设/策略/标签/事件/ETF/策略判定/经典战法扫描
"""

import sys
import argparse
import json
from typing import Dict, List, Optional

from data_gateway import get_quote
from scoring_engine_v3_1 import batch_score
from strategy_classifier import classify_strategy
from classic_strategies import scan_classic_strategies
from five_dimension_timing import get_market_timing


class StockScreener:
    """选股筛股器"""
    
    def __init__(self):
        self.watchlist = []  # 自选股列表
        
    def filter(self, conditions: List[Dict], logic: str = "AND") -> List[Dict]:
        """
        条件筛选
        
        Args:
            conditions: 条件列表 [{"field": "total_score", "op": ">=", "value": 65}]
            logic: AND/OR
            
        Returns:
            符合条件的股票列表
        """
        # 实际实现需要遍历全市场股票
        # 简化版：假设有一个股票池
        print("条件筛选功能需要接入全市场股票数据")
        return []
    
    def preset(self, strategy_name: str) -> List[Dict]:
        """
        预设策略选股
        
        Args:
            strategy_name: 策略名称 momentum/value/growth/dividend
            
        Returns:
            选股结果
        """
        presets = {
            'momentum': {'min_score': 60, 'sort_by': 'capital_score'},
            'value': {'min_score': 60, 'sort_by': 'value_score'},
            'growth': {'min_score': 55, 'sort_by': 'finance_score'},
            'dividend': {'min_score': 50, 'sort_by': 'value_score'},
            'low_risk': {'min_score': 60, 'sort_by': 'risk_score'}
        }
        
        preset = presets.get(strategy_name)
        if not preset:
            print(f"未知预设策略: {strategy_name}")
            return []
        
        print(f"预设策略 [{strategy_name}] 选股需要接入全市场数据")
        return []
    
    def ranking(self, field: str = "total", top: int = 20) -> List[Dict]:
        """
        排行榜
        
        Args:
            field: 排序字段 total/value/finance/capital/risk
            top: 前N名
            
        Returns:
            排名列表
        """
        print(f"{field} 排行榜需要接入全市场数据")
        return []
    
    def classify(self, code: str, market_env: str = "震荡") -> Dict:
        """
        策略类型判定
        
        Args:
            code: 股票代码
            market_env: 市场环境
            
        Returns:
            判定结果
        """
        result = classify_strategy(code, market_env)
        return {
            'code': result.code,
            'name': result.name,
            'strategy_type': result.strategy_type,
            'overnight_score': result.overnight_score,
            'swing_score': result.swing_score,
            'position_pct': result.position_pct,
            'reason': result.reason,
            'exclusions': result.exclusions
        }
    
    def classic_signals(self, code: str) -> List[Dict]:
        """
        经典战法扫描
        
        Args:
            code: 股票代码
            
        Returns:
            战法信号列表
        """
        signals = scan_classic_strategies(code)
        return [
            {
                'name': s.name,
                'triggered': s.triggered,
                'strength': s.strength,
                'entry': s.entry,
                'stop_loss': s.stop_loss,
                'target': s.target,
                'holding_days': s.holding_days,
                'reason': s.reason
            }
            for s in signals
        ]
    
    def add_watchlist(self, code: str):
        """添加自选股"""
        if code not in self.watchlist:
            self.watchlist.append(code)
            print(f"已添加 {code} 到自选股")
        else:
            print(f"{code} 已在自选股中")
    
    def remove_watchlist(self, code: str):
        """移除自选股"""
        if code in self.watchlist:
            self.watchlist.remove(code)
            print(f"已移除 {code}")
        else:
            print(f"{code} 不在自选股中")
    
    def get_watchlist(self) -> List[str]:
        """获取自选股列表"""
        return self.watchlist


# 全局实例
screener = StockScreener()


def main():
    parser = argparse.ArgumentParser(description='A股量化交易系统 - 选股筛股')
    subparsers = parser.add_subparsers(dest='command', help='子命令')
    
    # filter 条件筛选
    filter_parser = subparsers.add_parser('filter', help='条件筛选')
    filter_parser.add_argument('conditions', help='条件JSON')
    filter_parser.add_argument('logic', choices=['AND', 'OR'], default='AND')
    
    # preset 预设策略
    preset_parser = subparsers.add_parser('preset', help='预设策略')
    preset_parser.add_argument('name', choices=['momentum', 'value', 'growth', 'dividend', 'low_risk'])
    
    # ranking 排行
    ranking_parser = subparsers.add_parser('ranking', help='排行榜')
    ranking_parser.add_argument('field', choices=['total', 'value', 'finance', 'capital', 'risk'])
    ranking_parser.add_argument('top', type=int, default=20)
    
    # classify 策略判定
    classify_parser = subparsers.add_parser('classify', help='策略类型判定')
    classify_parser.add_argument('code', help='股票代码')
    classify_parser.add_argument('env', choices=['bull', '震荡', 'bear'], default='震荡')
    
    # classic 经典战法
    classic_parser = subparsers.add_parser('classic', help='经典战法扫描')
    classic_parser.add_argument('code', help='股票代码')
    
    # watchlist 自选股
    wl_parser = subparsers.add_parser('watchlist', help='自选股管理')
    wl_parser.add_argument('action', choices=['add', 'remove', 'list'])
    wl_parser.add_argument('code', nargs='?', help='股票代码')
    
    args = parser.parse_args()
    
    if args.command == 'filter':
        conditions = json.loads(args.conditions)
        results = screener.filter(conditions, args.logic)
        print(f"筛选结果: {len(results)} 只")
        
    elif args.command == 'preset':
        results = screener.preset(args.name)
        print(f"预设策略 [{args.name}] 结果: {len(results)} 只")
        
    elif args.command == 'ranking':
        results = screener.ranking(args.field, args.top)
        print(f"{args.field} 排行前{args.top}:")
        
    elif args.command == 'classify':
        result = screener.classify(args.code, args.env)
        print(f"\n{result['name']}({result['code']}) 策略判定:")
        print(f"  类型: {result['strategy_type']}")
        print(f"  过夜评分: {result['overnight_score']}/20")
        print(f"  波段评分: {result['swing_score']}/15")
        print(f"  建议仓位: {result['position_pct']*100:.1f}%")
        print(f"  理由: {result['reason']}")
        
    elif args.command == 'classic':
        signals = screener.classic_signals(args.code)
        print(f"\n扫描到 {len(signals)} 个战法信号:")
        for i, s in enumerate(signals, 1):
            print(f"  {i}. [{s['name']}] 强度:{s['strength']*100:.0f}%")
            print(f"     入场:{s['entry']:.2f} 止损:{s['stop_loss']:.2f} 目标:{s['target']:.2f}")
            
    elif args.command == 'watchlist':
        if args.action == 'add' and args.code:
            screener.add_watchlist(args.code)
        elif args.action == 'remove' and args.code:
            screener.remove_watchlist(args.code)
        elif args.action == 'list':
            wl = screener.get_watchlist()
            print(f"自选股 ({len(wl)} 只): {', '.join(wl)}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
