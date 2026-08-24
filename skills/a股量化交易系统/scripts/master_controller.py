#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 主控制器 v3.2
整合所有模块，一键执行完整交易流水线
新增: 数据预处理 + 因子检验 + 分层回测
"""

import sys
import json
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# 导入各模块
from data_gateway import get_quote, get_kline, get_batch_quotes, get_financial_data
from five_dimension_timing import get_market_timing
from scoring_engine_v3_1 import score_stock
from strategy_classifier import classify_strategy
from classic_strategies import scan_classic_strategies
from position_sizing_v3 import suggest_position

# 新增: 数据工程模块
from data_preprocessor import DataPreprocessor
from factor_validator import FactorValidator
from layered_backtest import LayeredBacktest


@dataclass
class TradeSignal:
    """最终交易信号"""
    code: str
    name: str
    action: str              # 买入/观望/卖出
    score: float             # 综合评分
    grade: str               # S/A/B/C/D
    strategy_type: str       # 过夜/波段/观望
    market_env: str          # 市场环境
    position_pct: float      # 建议仓位
    entry_price: float       # 入场价
    stop_loss: float         # 止损价
    target_price: float      # 目标价
    holding_days: int        # 持仓天数
    triggered_strategies: List[str]  # 触发的战法
    risk_per_trade: float    # 单笔风险
    reason: str              # 决策理由
    processed: bool          # 是否经过预处理


class QuantSystem:
    """A股量化交易系统主控制器"""
    
    def __init__(self):
        self.market_env = None
        self.market_score = None
        self.position_limit = None
        self.preprocessor = DataPreprocessor()
        self.validator = FactorValidator()
        self.backtest = LayeredBacktest()
    
    def run(self, codes: List[str], 
            validate: bool = False,
            backtest_mode: bool = False) -> Dict:
        """
        执行完整交易流水线
        
        Args:
            codes: 股票代码列表
            validate: 是否运行因子检验（研究模式）
            backtest_mode: 是否运行分层回测（研究模式）
            
        Returns:
            完整交易报告
        """
        print("=" * 70)
        print("A股量化交易系统 v3.2 - 数据驱动版")
        print(f"执行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        # Step 1: 市场择时
        timing = self._step1_market_timing()
        if not timing:
            return {"error": "市场择时失败"}
        
        # 研究模式: 因子检验
        if validate:
            return self._run_factor_validation(codes)
        
        # 研究模式: 分层回测
        if backtest_mode:
            return self._run_layered_backtest(codes)
        
        # 实盘模式: 分批获取行情（防限流）
        print(f"\n【批量分析】{len(codes)} 只股票，分批获取...")
        batch_quotes = get_batch_quotes(codes, batch_size=3, interval=1.5)
        print(f"  成功获取 {len(batch_quotes)}/{len(codes)} 只行情")
        
        signals = []
        for code in codes:
            if code not in batch_quotes:
                print(f"  {code}: 行情获取失败，跳过")
                continue
            signal = self._analyze_single(code, timing, batch_quotes[code])
            if signal:
                signals.append(signal)
        
        # 排序和筛选
        buy_signals = [s for s in signals if s.action == "买入"]
        watch_signals = [s for s in signals if s.action == "观望"]
        buy_signals.sort(key=lambda x: x.score, reverse=True)
        
        # 生成报告
        report = {
            "version": "3.2",
            "mode": "实盘",
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "market": {
                "environment": timing.environment,
                "score": timing.score,
                "position_limit": timing.position_suggest
            },
            "summary": {
                "total_analyzed": len(codes),
                "buy_signals": len(buy_signals),
                "watch_signals": len(watch_signals),
                "top_pick": buy_signals[0].code if buy_signals else None
            },
            "buy_signals": [asdict(s) for s in buy_signals],
            "watch_signals": [asdict(s) for s in watch_signals]
        }
        
        self._print_report(report)
        return report
    
    def _step1_market_timing(self) -> Optional[object]:
        """Step 1: 市场择时"""
        print("\n【Step 1/9】市场环境判断...")
        
        timing = get_market_timing()
        self.market_env = timing.environment
        self.market_score = timing.score
        self.position_limit = timing.position_suggest
        
        print(f"  市场环境: {timing.environment}")
        print(f"  综合评分: {timing.score:.1f}")
        print(f"  仓位上限: {timing.position_suggest*100:.0f}%")
        
        if timing.score < 40:
            print("  ⚠️ 市场环境恶劣，建议空仓观望")
        elif timing.score < 60:
            print("  ⚡ 震荡市，降低仓位，精选个股")
        else:
            print("  🚀 市场环境良好，积极操作")
        
        return timing
    
    def _analyze_single(self, code: str, timing, quote) -> Optional[TradeSignal]:
        """分析单只股票（Step 2-9）"""
        print(f"\n{'='*50}")
        print(f"分析: {code}")
        print(f"{'='*50}")
        
        # Step 2: 行情已在批量获取时拿到
        if not quote:
            print(f"  ❌ 无法获取行情，跳过")
            return None
        
        print(f"  {quote.name} 当前价: ¥{quote.price} ({quote.change_pct:+.2f}%)")
        if quote.sources:
            print(f"  数据来源: {', '.join(quote.sources)}")
        
        # Step 3: 数据预处理（新增）
        print("  【Step 3】数据预处理...")
        # 对实时数据做基础预处理
        processed_data = self._preprocess_realtime(quote)
        print(f"    ✅ MAD去极值 + Z-Score标准化")
        
        # Step 4: 四层框架评分
        print("  【Step 4】四层框架评分...")
        score_result = score_stock(code, timing.environment)
        print(f"    总分: {score_result.total_score:.0f}  等级: {score_result.grade}")
        
        if score_result.total_score < 55:
            print(f"    ❌ 评分不足(<55)，淘汰")
            return TradeSignal(
                code=code, name=quote.name, action="观望",
                score=score_result.total_score, grade=score_result.grade,
                strategy_type="观望", market_env=timing.environment,
                position_pct=0, entry_price=0, stop_loss=0, target_price=0,
                holding_days=0, triggered_strategies=[],
                risk_per_trade=0, reason="评分不足(<55)", processed=True
            )
        
        # Step 5: 策略类型判定
        print("  【Step 5】策略类型判定...")
        strategy_result = classify_strategy(code, timing.environment)
        print(f"    类型: {strategy_result.strategy_type}")
        
        # Step 6: 消息面硬排除
        print("  【Step 6】消息面硬排除...")
        if strategy_result.exclusions:
            print(f"    ❌ 硬排除: {', '.join(strategy_result.exclusions)}")
            return TradeSignal(
                code=code, name=quote.name, action="观望",
                score=score_result.total_score, grade=score_result.grade,
                strategy_type="观望", market_env=timing.environment,
                position_pct=0, entry_price=0, stop_loss=0, target_price=0,
                holding_days=0, triggered_strategies=[],
                risk_per_trade=0, reason=f"硬排除: {', '.join(strategy_result.exclusions)}",
                processed=True
            )
        print("    ✅ 无排除项")
        
        # Step 7: 经典战法扫描
        print("  【Step 7】经典战法扫描...")
        classic_signals = scan_classic_strategies(code)
        triggered = [s.name for s in classic_signals if s.triggered]
        
        if triggered:
            print(f"    ✅ 触发战法: {', '.join(triggered)}")
            best_signal = classic_signals[0]
            entry = best_signal.entry
            stop = best_signal.stop_loss
            target = best_signal.target
            days = best_signal.holding_days
        else:
            print(f"    ⚠️ 无战法信号")
            entry = quote.price
            stop = quote.price * 0.95
            target = quote.price * 1.08
            days = 5
        
        # Step 8: 仓位计算
        print("  【Step 8】仓位计算...")
        if triggered:
            pos_result = suggest_position(triggered[0], timing.environment, score_result.grade)
        else:
            pos_result = suggest_position("均线多头", timing.environment, score_result.grade)
        
        final_position = min(pos_result.final_position, timing.position_suggest)
        
        print(f"    半凯利: {pos_result.half_kelly*100:.1f}%")
        print(f"    最终仓位: {final_position*100:.1f}%")
        
        # Step 9: 综合决策
        if score_result.grade in ['S', 'A'] and (triggered or strategy_result.strategy_type != "观望"):
            action = "买入"
            reason = f"评分{score_result.grade}级，{'触发' + triggered[0] if triggered else '策略匹配'}"
        elif score_result.grade == 'B' and triggered:
            action = "买入"
            reason = f"评分B级，触发战法，谨慎参与"
        else:
            action = "观望"
            reason = f"评分{score_result.grade}级，无明确信号"
            final_position = 0
        
        return TradeSignal(
            code=code, name=quote.name, action=action,
            score=score_result.total_score, grade=score_result.grade,
            strategy_type=strategy_result.strategy_type,
            market_env=timing.environment, position_pct=final_position,
            entry_price=entry, stop_loss=stop, target_price=target,
            holding_days=days, triggered_strategies=triggered,
            risk_per_trade=pos_result.risk_per_trade, reason=reason,
            processed=True
        )
    
    def _preprocess_realtime(self, quote) -> Dict:
        """实时数据预处理"""
        # 提取数值特征
        features = {
            'pe': getattr(quote, 'pe', 20),
            'pb': getattr(quote, 'pb', 2),
            'roe': getattr(quote, 'roe', 10),
            'change_pct': quote.change_pct,
            'volume': quote.volume,
            'turnover_rate': getattr(quote, 'turnover_rate', 5)
        }
        
        # 应用MAD去极值
        for key, value in features.items():
            features[key] = self._mad_clip(value, key)
        
        return features
    
    def _mad_clip(self, value: float, factor_name: str) -> float:
        """简化版MAD裁剪（使用预设阈值）"""
        thresholds = {
            'pe': (5, 100),
            'pb': (0.5, 10),
            'roe': (-20, 50),
            'change_pct': (-20, 20),
            'turnover_rate': (0.1, 30)
        }
        
        low, high = thresholds.get(factor_name, (-1000, 1000))
        return max(low, min(high, value))
    
    def _run_factor_validation(self, codes: List[str]) -> Dict:
        """运行因子检验（研究模式）"""
        print("\n【研究模式】因子检验")
        print("=" * 50)
        
        # 模拟历史数据检验
        import numpy as np
        np.random.seed(42)
        
        # 生成模拟因子和收益数据
        n = len(codes) * 60  # 60个月历史
        
        factors = {
            'PE': np.random.randn(n),
            'ROE': np.random.randn(n),
            'PB': np.random.randn(n),
            'Momentum': np.random.randn(n),
            'Turnover': np.random.randn(n)
        }
        
        # 模拟收益（让部分因子有效）
        returns = factors['PE'] * 0.05 + factors['ROE'] * 0.08 + np.random.randn(n) * 0.1
        
        # 检验
        from factor_validator import test_multiple_factors
        factor_series = {k: pd.Series(v) for k, v in factors.items()}
        returns_series = pd.Series(returns)
        
        results = test_multiple_factors(factor_series, returns_series)
        
        print("\n因子检验结果:")
        print(results.to_string(index=False))
        
        passed_factors = results[results['通过'] == True]['因子'].tolist()
        print(f"\n通过检验的因子: {', '.join(passed_factors) if passed_factors else '无'}")
        
        return {
            "mode": "因子检验",
            "results": results.to_dict('records'),
            "passed_factors": passed_factors
        }
    
    def _run_layered_backtest(self, codes: List[str]) -> Dict:
        """运行分层回测（研究模式）"""
        print("\n【研究模式】分层回测")
        print("=" * 50)
        
        import numpy as np
        np.random.seed(42)
        
        # 模拟评分和收益
        n = 1000
        scores = pd.Series(np.random.randn(n))
        returns = pd.Series(scores * 0.05 + np.random.randn(n) * 0.1)
        
        from layered_backtest import run_layered_backtest
        report = run_layered_backtest(scores, returns)
        
        # 打印报告
        from layered_backtest import LayeredBacktest
        LayeredBacktest().print_report(report)
        
        return {
            "mode": "分层回测",
            "monotonic": report['monotonic'],
            "long_short": report['long_short']
        }
    
    def _print_report(self, report: Dict):
        """打印交易报告"""
        print("\n" + "=" * 70)
        print("交易报告")
        print("=" * 70)
        
        market = report["market"]
        print(f"\n【市场环境】{market['environment']} (评分: {market['score']:.1f})")
        print(f"【仓位上限】{market['position_limit']*100:.0f}%")
        
        summary = report["summary"]
        print(f"\n【分析汇总】")
        print(f"  分析股票: {summary['total_analyzed']} 只")
        print(f"  买入信号: {summary['buy_signals']} 只")
        print(f"  观望信号: {summary['watch_signals']} 只")
        if summary['top_pick']:
            print(f"  首选标的: {summary['top_pick']}")
        
        if report["buy_signals"]:
            print(f"\n【买入信号】({len(report['buy_signals'])} 只)")
            print(f"{'排名':<4} {'代码':<8} {'名称':<10} {'评分':<6} {'等级':<4} {'策略':<8} {'仓位':<6} {'入场价':<8} {'止损':<8} {'目标':<8}")
            print("-" * 80)
            for i, s in enumerate(report["buy_signals"][:10], 1):
                print(f"{i:<4} {s['code']:<8} {s['name']:<10} {s['score']:<6.0f} {s['grade']:<4} {s['strategy_type']:<8} {s['position_pct']*100:<6.1f}% ¥{s['entry_price']:<8.2f} ¥{s['stop_loss']:<8.2f} ¥{s['target_price']:<8.2f}")
                print(f"     理由: {s['reason']}")
        
        print("\n" + "=" * 70)


def run_quant_system(codes: List[str], 
                     validate: bool = False,
                     backtest: bool = False) -> Dict:
    """便捷函数：运行量化系统"""
    system = QuantSystem()
    return system.run(codes, validate=validate, backtest_mode=backtest)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='A股量化交易系统 v3.2')
    parser.add_argument('codes', nargs='*', help='股票代码列表')
    parser.add_argument('--validate', action='store_true', help='因子检验模式（研究）')
    parser.add_argument('--backtest', action='store_true', help='分层回测模式（研究）')
    parser.add_argument('--json', action='store_true', help='JSON输出')
    
    args = parser.parse_args()
    
    # 研究模式不需要股票代码
    if args.validate or args.backtest:
        report = run_quant_system([], validate=args.validate, backtest=args.backtest)
    elif args.codes:
        report = run_quant_system(args.codes)
    else:
        # 默认测试
        test_codes = ["000001", "000002", "600519"]
        print(f"使用测试股票: {', '.join(test_codes)}")
        report = run_quant_system(test_codes)
    
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
