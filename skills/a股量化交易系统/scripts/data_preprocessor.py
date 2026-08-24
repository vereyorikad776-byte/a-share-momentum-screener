#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 数据预处理引擎
去极值(MAD/3σ) → 中性化(行业/市值) → 标准化(Z-Score)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class DataPreprocessor:
    """数据预处理器"""
    
    def __init__(self, method: str = 'mad'):
        """
        Args:
            method: 去极值方法 mad/3sigma/percentile
        """
        self.method = method
    
    def process(self, df: pd.DataFrame, 
                factor_cols: List[str],
                industry_col: str = 'industry',
                market_cap_col: str = 'market_cap') -> pd.DataFrame:
        """
        完整预处理流程
        
        Args:
            df: 原始数据DataFrame
            factor_cols: 需要预处理的因子列
            industry_col: 行业列名
            market_cap_col: 市值列名
            
        Returns:
            预处理后的DataFrame
        """
        result = df.copy()
        
        for col in factor_cols:
            if col not in result.columns:
                continue
            
            # Step 1: 去极值
            result[col] = self._winsorize(result[col])
            
            # Step 2: 中性化（去除行业和市值影响）
            if industry_col in result.columns and market_cap_col in result.columns:
                result[col] = self._neutralize(result[col], 
                                               result[industry_col], 
                                               result[market_cap_col])
            
            # Step 3: 标准化
            result[col] = self._standardize(result[col])
        
        return result
    
    def _winsorize(self, series: pd.Series) -> pd.Series:
        """去极值"""
        if self.method == 'mad':
            return self._mad_winsorize(series)
        elif self.method == '3sigma':
            return self._sigma_winsorize(series)
        elif self.method == 'percentile':
            return self._percentile_winsorize(series)
        else:
            return series
    
    def _mad_winsorize(self, series: pd.Series, n: int = 3) -> pd.Series:
        """
        MAD去极值法（中位数绝对偏差）
        比3σ更稳健，不受极端值影响
        """
        median = series.median()
        mad = (series - median).abs().median()
        
        # MAD常数调整：1.4826 使MAD成为标准差的无偏估计
        upper = median + n * 1.4826 * mad
        lower = median - n * 1.4826 * mad
        
        return series.clip(lower, upper)
    
    def _sigma_winsorize(self, series: pd.Series, n: int = 3) -> pd.Series:
        """3σ去极值"""
        mean = series.mean()
        std = series.std()
        
        upper = mean + n * std
        lower = mean - n * std
        
        return series.clip(lower, upper)
    
    def _percentile_winsorize(self, series: pd.Series, 
                              lower_pct: float = 0.01,
                              upper_pct: float = 0.99) -> pd.Series:
        """百分位去极值"""
        lower = series.quantile(lower_pct)
        upper = series.quantile(upper_pct)
        
        return series.clip(lower, upper)
    
    def _neutralize(self, factor: pd.Series, 
                   industry: pd.Series,
                   market_cap: pd.Series) -> pd.Series:
        """
        中性化：去除行业和市值的影响
        
        方法：截面回归
        factor = β0 + β1*industry_dummy + β2*log(market_cap) + ε
        取残差 ε 作为中性化后的因子
        """
        # 准备数据
        data = pd.DataFrame({
            'factor': factor,
            'industry': industry,
            'log_cap': np.log(market_cap)
        }).dropna()
        
        if len(data) < 10:
            return factor
        
        # 行业虚拟变量
        industry_dummies = pd.get_dummies(data['industry'], prefix='ind')
        
        # 自变量：行业 + 市值
        X = pd.concat([industry_dummies, data['log_cap']], axis=1)
        X = sm.add_constant(X)  # 添加常数项
        
        # 回归
        y = data['factor']
        model = sm.OLS(y, X).fit()
        
        # 残差 = 因子 - 行业/市值解释的部分
        residual = y - model.fittedvalues
        
        # 放回原始索引
        result = pd.Series(index=factor.index, dtype=float)
        result.loc[residual.index] = residual.values
        result.fillna(factor, inplace=True)
        
        return result
    
    def _standardize(self, series: pd.Series, method: str = 'zscore') -> pd.Series:
        """
        标准化
        
        Args:
            method: zscore/minmax/rank
        """
        if method == 'zscore':
            mean = series.mean()
            std = series.std()
            if std > 0:
                return (series - mean) / std
            else:
                return series - mean
        
        elif method == 'minmax':
            min_val = series.min()
            max_val = series.max()
            if max_val > min_val:
                return (series - min_val) / (max_val - min_val)
            else:
                return pd.Series(0, index=series.index)
        
        elif method == 'rank':
            # 排序标准化到[0,1]
            return series.rank(pct=True)
        
        else:
            return series


# 需要statsmodels
import importlib
sm_spec = importlib.util.find_spec("statsmodels")
if sm_spec is None:
    print("警告: 未安装statsmodels，中性化功能将不可用")
    print("安装: pip install statsmodels")
    # 提供一个简化版中性化
    class DummySM:
        @staticmethod
        def add_constant(X):
            return X
        class OLS:
            def __init__(self, y, X):
                self.y = y
                self.X = X
            def fit(self):
                class Result:
                    fittedvalues = pd.Series(0, index=range(len(self.y)))
                return Result()
    sm = DummySM()
else:
    import statsmodels.api as sm


# 全局实例
preprocessor = DataPreprocessor()


def preprocess_factors(df: pd.DataFrame, factor_cols: List[str],
                       industry_col: str = 'industry',
                       market_cap_col: str = 'market_cap') -> pd.DataFrame:
    """便捷函数：预处理因子"""
    return preprocessor.process(df, factor_cols, industry_col, market_cap_col)


if __name__ == "__main__":
    # 测试
    np.random.seed(42)
    n = 1000
    
    df = pd.DataFrame({
        'code': [f'000{i:03d}' for i in range(n)],
        'PE': np.random.randn(n) * 10 + 20,
        'ROE': np.random.randn(n) * 5 + 10,
        'industry': np.random.choice(['银行', '科技', '消费', '医药'], n),
        'market_cap': np.random.lognormal(20, 1, n)
    })
    
    # 加入极端值
    df.loc[0, 'PE'] = 1000
    df.loc[1, 'PE'] = -100
    
    print("预处理前 PE 描述统计:")
    print(df['PE'].describe())
    
    processed = preprocess_factors(df, ['PE', 'ROE'])
    
    print("\n预处理后 PE 描述统计:")
    print(processed['PE'].describe())
