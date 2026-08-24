#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 分层回测引擎
将股票按评分分5层，检验分层收益单调性
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class LayerResult:
    """分层结果"""
    layer: str              # S/A/B/C/D
    count: int              # 股票数量
    avg_return: float       # 平均收益
    cum_return: float       # 累计收益
    sharpe: float           # 夏普比率
    max_drawdown: float     # 最大回撤
    volatility: float       # 波动率
    win_rate: float         # 胜率


class LayeredBacktest:
    """分层回测器"""
    
    def __init__(self, n_layers: int = 5):
        self.n_layers = n_layers
        self.layer_names = ['S', 'A', 'B', 'C', 'D']
        
    def run(self, scores: pd.Series, 
            forward_returns: pd.Series,
            rebalance_freq: str = 'month') -> Dict:
        """
        分层回测
        
        Args:
            scores: 评分序列 (index=date, columns=stocks)
            forward_returns: 未来收益
            rebalance_freq: 调仓频率
            
        Returns:
            回测结果
        """
        # 对齐数据
        data = pd.concat([scores, forward_returns], axis=1).dropna()
        data.columns = ['score', 'returns']
        
        # 按评分分层
        data['layer'] = pd.qcut(data['score'], 
                               q=self.n_layers, 
                               labels=self.layer_names)
        
        # 统计各层
        results = []
        for name in self.layer_names:
            layer_data = data[data['layer'] == name]['returns']
            
            if len(layer_data) == 0:
                continue
            
            result = LayerResult(
                layer=name,
                count=len(layer_data),
                avg_return=layer_data.mean(),
                cum_return=(1 + layer_data).prod() - 1,
                sharpe=layer_data.mean() / layer_data.std() if layer_data.std() > 0 else 0,
                max_drawdown=self._max_drawdown(layer_data),
                volatility=layer_data.std(),
                win_rate=(layer_data > 0).mean()
            )
            results.append(result)
        
        # 检验单调性
        monotonic = self._test_monotonicity(results)
        
        # 多空组合（S层做多，D层做空）
        long_short = self._calculate_long_short(data)
        
        return {
            'layers': results,
            'monotonic': monotonic,
            'long_short': long_short,
            'summary': self._generate_summary(results, monotonic)
        }
    
    def _max_drawdown(self, returns: pd.Series) -> float:
        """计算最大回撤"""
        cum = (1 + returns).cumprod()
        peak = cum.expanding().max()
        drawdown = (cum - peak) / peak
        return drawdown.min()
    
    def _test_monotonicity(self, results: List[LayerResult]) -> Dict:
        """检验收益单调性"""
        returns = [r.avg_return for r in results]
        
        # 计算Spearman秩相关
        ranks = np.argsort(np.argsort(returns))  # 排名
        ideal_ranks = np.arange(len(returns))     # 理想排名
        
        corr = np.corrcoef(ranks, ideal_ranks)[0, 1]
        
        # 是否单调递减（S>A>B>C>D）
        is_monotonic = all(returns[i] >= returns[i+1] for i in range(len(returns)-1))
        
        return {
            'spearman_corr': corr,
            'is_monotonic': is_monotonic,
            's_minus_d': returns[0] - returns[-1] if len(returns) > 1 else 0
        }
    
    def _calculate_long_short(self, data: pd.DataFrame) -> Dict:
        """多空组合收益"""
        s_layer = data[data['layer'] == 'S']['returns']
        d_layer = data[data['layer'] == 'D']['returns']
        
        if len(s_layer) == 0 or len(d_layer) == 0:
            return {'return': 0, 'sharpe': 0}
        
        ls_returns = s_layer.mean() - d_layer.mean()
        ls_std = (s_layer - d_layer.reindex(s_layer.index).fillna(0)).std()
        
        return {
            'return': ls_returns,
            'sharpe': ls_returns / ls_std if ls_std > 0 else 0,
            's_return': s_layer.mean(),
            'd_return': d_layer.mean()
        }
    
    def _generate_summary(self, results: List[LayerResult], 
                         monotonic: Dict) -> str:
        """生成文字总结"""
        summary = []
        summary.append("分层回测结果")
        summary.append("=" * 50)
        
        for r in results:
            summary.append(
                f"{r.layer}层: 数量={r.count}, "
                f"平均收益={r.avg_return*100:.2f}%, "
                f"夏普={r.sharpe:.2f}, "
                f"回撤={r.max_drawdown*100:.2f}%"
            )
        
        summary.append("-" * 50)
        summary.append(f"单调性检验: {'通过' if monotonic['is_monotonic'] else '未通过'}")
        summary.append(f"Spearman相关: {monotonic['spearman_corr']:.3f}")
        summary.append(f"S-D多空收益: {monotonic['s_minus_d']*100:.2f}%")
        
        return "\n".join(summary)
    
    def print_report(self, report: Dict):
        """打印回测报告"""
        print(report['summary'])
        print()
        
        # 多空组合
        ls = report['long_short']
        print("多空组合:")
        print(f"  S层收益: {ls['s_return']*100:.2f}%")
        print(f"  D层收益: {ls['d_return']*100:.2f}%")
        print(f"  多空收益: {ls['return']*100:.2f}%")
        print(f"  多空夏普: {ls['sharpe']:.2f}")


# 便捷函数
backtest = LayeredBacktest()


def run_layered_backtest(scores: pd.Series, 
                        returns: pd.Series) -> Dict:
    """便捷函数：运行分层回测"""
    return backtest.run(scores, returns)


if __name__ == "__main__":
    # 测试
    np.random.seed(42)
    n = 1000
    
    # 模拟评分（S>A>B>C>D）
    scores = pd.Series(np.random.randn(n))
    # 让高分股票收益更高（模拟有效因子）
    returns = pd.Series(scores * 0.05 + np.random.randn(n) * 0.1)
    
    report = run_layered_backtest(scores, returns)
    backtest.print_report(report)
