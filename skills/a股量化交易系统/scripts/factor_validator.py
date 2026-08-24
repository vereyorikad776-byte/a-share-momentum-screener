#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 因子检验引擎
IC/IR检验 + 分层回测 + 衰减分析
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from scipy import stats


@dataclass
class FactorTestResult:
    """因子检验结果"""
    factor_name: str
    ic_mean: float          # IC均值
    ic_std: float           # IC标准差
    ic_ir: float            # IC_IR = IC均值/标准差
    ic_positive_ratio: float  # IC正比例
    rank_ic_mean: float     # Rank IC均值
    rank_ic_ir: float       # Rank IC_IR
    turnover: float         # 换手率
    long_short_return: float  # 多空组合收益
    long_short_sharpe: float  # 多空夏普
    t_stat: float           # t统计量
    p_value: float          # p值
    decay_half_life: int    # 衰减半衰期(月)
    passed: bool            # 是否通过检验


class FactorValidator:
    """因子检验器"""
    
    def __init__(self):
        # 检验阈值
        self.ic_threshold = 0.03        # |IC| > 0.03
        self.ic_ir_threshold = 0.5      # IC_IR > 0.5
        self.turnover_threshold = 0.5   # 换手率 < 50%
        self.t_stat_threshold = 2.0     # t统计量 > 2
        
    def test_factor(self, factor_values: pd.Series, 
                    forward_returns: pd.Series,
                    period: str = 'month') -> FactorTestResult:
        """
        单因子检验
        
        Args:
            factor_values: 因子值序列 (index=date, columns=stocks)
            forward_returns: 未来收益序列
            period: 检验周期 month/week
            
        Returns:
            FactorTestResult
        """
        # 对齐数据
        aligned = pd.concat([factor_values, forward_returns], axis=1).dropna()
        if len(aligned) < 30:
            return self._empty_result("数据不足")
        
        f = aligned.iloc[:, 0]
        r = aligned.iloc[:, 1]
        
        # 1. IC检验 (Pearson)
        ic = f.corr(r, method='pearson')
        
        # 2. Rank IC (Spearman)
        rank_ic = f.corr(r, method='spearman')
        
        # 3. 时间序列IC（滚动计算）
        # 简化：假设输入是截面数据
        ic_series = self._rolling_ic(factor_values, forward_returns)
        
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        ic_ir = ic_mean / ic_std if ic_std > 0 else 0
        ic_positive = (ic_series > 0).mean()
        
        # 4. t检验
        t_stat, p_value = stats.ttest_1samp(ic_series, 0)
        
        # 5. 多空组合
        ls_return, ls_sharpe = self._long_short_test(factor_values, forward_returns)
        
        # 6. 换手率
        turnover = self._calculate_turnover(factor_values)
        
        # 7. 衰减分析
        half_life = self._calculate_decay(ic_series)
        
        # 8. 是否通过
        passed = (
            abs(ic_mean) > self.ic_threshold and
            abs(ic_ir) > self.ic_ir_threshold and
            turnover < self.turnover_threshold and
            abs(t_stat) > self.t_stat_threshold
        )
        
        return FactorTestResult(
            factor_name=factor_values.name if hasattr(factor_values, 'name') else 'unknown',
            ic_mean=ic_mean,
            ic_std=ic_std,
            ic_ir=ic_ir,
            ic_positive_ratio=ic_positive,
            rank_ic_mean=rank_ic,
            rank_ic_ir=rank_ic / ic_std if ic_std > 0 else 0,
            turnover=turnover,
            long_short_return=ls_return,
            long_short_sharpe=ls_sharpe,
            t_stat=t_stat,
            p_value=p_value,
            decay_half_life=half_life,
            passed=passed
        )
    
    def _rolling_ic(self, factor: pd.Series, returns: pd.Series, 
                    window: int = 20) -> pd.Series:
        """滚动计算IC"""
        # 简化：按时间窗口计算截面IC
        data = pd.concat([factor, returns], axis=1)
        data.columns = ['factor', 'returns']
        
        ic_series = []
        for i in range(window, len(data)):
            window_data = data.iloc[i-window:i]
            ic = window_data['factor'].corr(window_data['returns'])
            ic_series.append(ic)
        
        return pd.Series(ic_series)
    
    def _long_short_test(self, factor: pd.Series, returns: pd.Series,
                        top_pct: float = 0.2, bottom_pct: float = 0.2) -> Tuple[float, float]:
        """多空组合检验"""
        data = pd.concat([factor, returns], axis=1).dropna()
        data.columns = ['factor', 'returns']
        
        # 按因子值分组
        n = len(data)
        top_n = int(n * top_pct)
        bottom_n = int(n * bottom_pct)
        
        data_sorted = data.sort_values('factor')
        long_portfolio = data_sorted.iloc[-top_n:]['returns']   # 多头：因子值高
        short_portfolio = data_sorted.iloc[:bottom_n]['returns']  # 空头：因子值低
        
        # 多空收益
        ls_returns = long_portfolio.mean() - short_portfolio.mean()
        ls_std = (long_portfolio - short_portfolio).std()
        ls_sharpe = ls_returns / ls_std if ls_std > 0 else 0
        
        return ls_returns, ls_sharpe
    
    def _calculate_turnover(self, factor: pd.Series) -> float:
        """计算换手率（因子值变化率）"""
        if len(factor) < 2:
            return 0
        
        # 因子值变化绝对值之和 / 总因子值
        turnover = factor.diff().abs().sum() / factor.abs().sum()
        return min(turnover, 1.0)
    
    def _calculate_decay(self, ic_series: pd.Series) -> int:
        """计算IC衰减半衰期"""
        if len(ic_series) < 10:
            return 0
        
        # 自相关衰减
        autocorrs = []
        for lag in range(1, min(13, len(ic_series)//2)):
            corr = ic_series.autocorr(lag=lag)
            if pd.isna(corr):
                break
            autocorrs.append(corr)
        
        # 找半衰期（自相关系数衰减到0.5）
        for i, ac in enumerate(autocorrs):
            if ac < 0.5:
                return i + 1
        
        return len(autocorrs)
    
    def _empty_result(self, reason: str) -> FactorTestResult:
        """空结果"""
        return FactorTestResult(
            factor_name='unknown', ic_mean=0, ic_std=0, ic_ir=0,
            ic_positive_ratio=0, rank_ic_mean=0, rank_ic_ir=0,
            turnover=0, long_short_return=0, long_short_sharpe=0,
            t_stat=0, p_value=1, decay_half_life=0, passed=False
        )
    
    def batch_test(self, factors: Dict[str, pd.Series], 
                   returns: pd.Series) -> pd.DataFrame:
        """
        批量因子检验
        
        Args:
            factors: {因子名: 因子值序列}
            returns: 未来收益序列
            
        Returns:
            检验结果DataFrame
        """
        results = []
        for name, factor in factors.items():
            print(f"检验因子: {name}...")
            result = self.test_factor(factor, returns)
            result.factor_name = name
            results.append(result)
        
        # 转为DataFrame
        df = pd.DataFrame([{
            '因子': r.factor_name,
            'IC均值': r.ic_mean,
            'IC_IR': r.ic_ir,
            'Rank_IC': r.rank_ic_mean,
            '正IC比例': r.ic_positive_ratio,
            '换手率': r.turnover,
            '多空收益': r.long_short_return,
            '多空夏普': r.long_short_sharpe,
            't统计量': r.t_stat,
            'p值': r.p_value,
            '半衰期': r.decay_half_life,
            '通过': r.passed
        } for r in results])
        
        return df.sort_values('IC_IR', ascending=False)


# 便捷函数
validator = FactorValidator()


def test_single_factor(factor: pd.Series, returns: pd.Series) -> FactorTestResult:
    """检验单因子"""
    return validator.test_factor(factor, returns)


def test_multiple_factors(factors: Dict[str, pd.Series], 
                          returns: pd.Series) -> pd.DataFrame:
    """批量检验"""
    return validator.batch_test(factors, returns)


if __name__ == "__main__":
    # 测试用例
    np.random.seed(42)
    n = 500
    
    # 模拟因子和收益
    factor_pe = pd.Series(np.random.randn(n), name='PE')
    factor_roe = pd.Series(np.random.randn(n), name='ROE')
    returns = pd.Series(np.random.randn(n) * 0.1 + factor_pe * 0.05, name='returns')
    
    # 检验
    factors = {'PE': factor_pe, 'ROE': factor_roe}
    results = test_multiple_factors(factors, returns)
    
    print("\n因子检验结果:")
    print(results.to_string(index=False))
