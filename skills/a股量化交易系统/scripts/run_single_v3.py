#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 单票评分入口
完整诊断：评分 + 策略判定 + 战法扫描 + 仓位建议
"""

import sys
import argparse
from typing import Optional

from data_gateway import get_quote
from scoring_engine_v3_1 import score_stock
from strategy_classifier import classify_strategy
from classic_strategies import scan_classic_strategies
from five_dimension_timing import get_market_timing
from position_sizing_v3 import suggest_position


def analyze_stock(code: str, market_env: Optional[str] = None, deep: bool = False) -> dict:
    """
    对单只股票进行完整分析
    
    Args:
        code: 股票代码
        market_env: 市场环境，None则自动判断
        deep: 是否输出深度分析
        
    Returns:
        分析结果字典
    """
    # 1. 获取市场择时（如果未指定）
    if market_env is None:
        timing = get_market_timing()
        market_env = timing.environment
    
    # 2. 四层框架评分
    score_result = score_stock(code, market_env)
    
    # 3. 策略类型判定
    strategy_result = classify_strategy(code, market_env)
    
    # 4. 经典战法扫描
    classic_signals = scan_classic_strategies(code)
    
    # 5. 仓位计算（如果有战法信号）
    position_results = []
    for signal in classic_signals[:2]:  # 取前2个信号
        pos = suggest_position(signal.name, market_env, score_result.grade)
        position_results.append({
            'strategy': signal.name,
            'position': pos.final_position,
            'risk': pos.risk_per_trade
        })
    
    # 6. 组装结果
    result = {
        'code': code,
        'name': score_result.name,
        'market_env': market_env,
        'scoring': {
            'value': score_result.value_score,
            'finance': score_result.finance_score,
            'capital': score_result.capital_score,
            'risk': score_result.risk_score,
            'total': score_result.total_score,
            'grade': score_result.grade
        },
        'strategy': {
            'type': strategy_result.strategy_type,
            'overnight_score': strategy_result.overnight_score,
            'swing_score': strategy_result.swing_score,
            'position_pct': strategy_result.position_pct,
            'reason': strategy_result.reason
        },
        'classic_signals': [
            {
                'name': s.name,
                'strength': s.strength,
                'entry': s.entry,
                'stop_loss': s.stop_loss,
                'target': s.target,
                'holding_days': s.holding_days,
                'reason': s.reason
            }
            for s in classic_signals
        ],
        'position_suggestions': position_results
    }
    
    # 7. 深度分析（简化版）
    if deep:
        result['deep_analysis'] = generate_deep_analysis(code, score_result, strategy_result)
    
    return result


def generate_deep_analysis(code: str, score_result, strategy_result) -> dict:
    """生成深度分析（简化版）"""
    analysis = {
        'company_profile': '需要接入财务数据接口',
        'financial_health': {
            'roe': score_result.details.get('finance', {}).get('roe', 0),
            'revenue_growth': score_result.details.get('finance', {}).get('revenue_growth', 0),
            'cashflow': score_result.details.get('finance', {}).get('cashflow', 0)
        },
        'technical_analysis': '需要更多K线数据',
        'risk_assessment': {
            'volatility': score_result.details.get('risk', {}).get('volatility', 0),
            'max_drawdown': score_result.details.get('risk', {}).get('max_drawdown', 0),
            'pledge': score_result.details.get('risk', {}).get('pledge', 0)
        },
        'trading_plan': {
            'rating': score_result.grade,
            'strategy': strategy_result.strategy_type,
            'suggested_position': strategy_result.position_pct,
            'entry_zone': '参考经典战法信号',
            'stop_loss': '参考经典战法信号',
            'target': '参考经典战法信号'
        }
    }
    return analysis


def print_analysis(result: dict):
    """打印分析结果"""
    print(f"\n{'='*60}")
    print(f"  {result['name']}({result['code']}) 完整诊断报告")
    print(f"{'='*60}")
    
    print(f"\n【市场环境】{result['market_env']}")
    
    print(f"\n【四层框架评分】总分: {result['scoring']['total']:.1f}/100  等级: {result['scoring']['grade']}")
    print(f"  价值猎手: {result['scoring']['value']:.1f}/30")
    print(f"  财务透视: {result['scoring']['finance']:.1f}/20")
    print(f"  资金解码: {result['scoring']['capital']:.1f}/25")
    print(f"  全维风控: {result['scoring']['risk']:.1f}/25")
    
    print(f"\n【策略判定】{result['strategy']['type']}")
    print(f"  过夜评分: {result['strategy']['overnight_score']:.1f}/20")
    print(f"  波段评分: {result['strategy']['swing_score']:.1f}/15")
    print(f"  建议仓位: {result['strategy']['position_pct']*100:.1f}%")
    print(f"  判定理由: {result['strategy']['reason']}")
    
    if result['classic_signals']:
        print(f"\n【经典战法信号】发现 {len(result['classic_signals'])} 个:")
        for i, signal in enumerate(result['classic_signals'], 1):
            print(f"  {i}. {signal['name']} (强度: {signal['strength']*100:.0f}%)")
            print(f"     入场: {signal['entry']:.2f}  止损: {signal['stop_loss']:.2f}  目标: {signal['target']:.2f}")
            print(f"     持仓: {signal['holding_days']}天  理由: {signal['reason']}")
    else:
        print(f"\n【经典战法信号】暂无信号")
    
    if result['position_suggestions']:
        print(f"\n【仓位建议】")
        for pos in result['position_suggestions']:
            print(f"  {pos['strategy']}: {pos['position']*100:.1f}% (风险: {pos['risk']*100:.2f}%)")
    
    print(f"\n{'='*60}")


def main():
    parser = argparse.ArgumentParser(description='A股量化交易系统 - 单票分析')
    parser.add_argument('code', help='股票代码，如 000983')
    parser.add_argument('--env', choices=['bull', '震荡', 'bear'], help='市场环境')
    parser.add_argument('--deep', action='store_true', help='深度分析')
    
    args = parser.parse_args()
    
    result = analyze_stock(args.code, args.env, args.deep)
    print_analysis(result)


if __name__ == "__main__":
    main()
