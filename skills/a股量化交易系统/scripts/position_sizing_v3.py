#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 凯利公式仓位计算
半凯利原则 + A股适配 + 硬性约束
"""

from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class PositionResult:
    """仓位计算结果"""
    kelly_raw: float        # 原始凯利
    half_kelly: float       # 半凯利
    after_env: float        # 环境调整后
    final_position: float   # 最终仓位
    cash_after: float       # 剩余现金比例
    risk_per_trade: float   # 单笔风险
    constraints_applied: list  # 应用的约束


class PositionSizing:
    """仓位管理器"""
    
    def __init__(self):
        self.single_limit = 0.20      # 单票上限20%
        self.cash_min = 0.30          # 现金保底30%
        self.total_limits = {
            'bull': 0.80,
            '震荡偏强': 0.60,
            '震荡': 0.40,
            '震荡偏弱': 0.30,
            'bear': 0.20
        }
        self.grade_multipliers = {
            'S': 1.2, 'A': 1.0, 'B': 0.6, 'C': 0.3, 'D': 0
        }
    
    def calculate(self, win_rate: float, profit_loss_ratio: float,
                  market_env: str, score_grade: str,
                  current_cash_ratio: float = 1.0) -> PositionResult:
        """
        计算最优仓位
        
        Args:
            win_rate: 历史胜率 0-1
            profit_loss_ratio: 盈亏比
            market_env: 市场环境
            score_grade: 评分等级 S/A/B/C/D
            current_cash_ratio: 当前现金比例
            
        Returns:
            PositionResult
        """
        constraints = []
        
        # Step 1: 基础凯利
        if win_rate <= 0 or profit_loss_ratio <= 0:
            kelly = 0
        else:
            kelly = (win_rate * profit_loss_ratio - (1 - win_rate)) / profit_loss_ratio
            kelly = max(0, min(1, kelly))
        
        # Step 2: 半凯利（A股适配）
        half_kelly = kelly * 0.5
        
        # Step 3: 趋势调整
        env_mult = self._get_env_multiplier(market_env)
        adjusted = half_kelly * env_mult
        
        # Step 4: 等级倍率
        grade_mult = self.grade_multipliers.get(score_grade, 0)
        final = adjusted * grade_mult
        
        # Step 5: 硬性约束
        # 单票上限
        if final > self.single_limit:
            final = self.single_limit
            constraints.append(f"单票上限{self.single_limit*100:.0f}%")
        
        # 总仓位上限
        total_limit = self.total_limits.get(market_env, 0.40)
        if final > total_limit:
            final = total_limit
            constraints.append(f"总仓位上限{total_limit*100:.0f}%")
        
        # 现金保底
        if current_cash_ratio - final < self.cash_min:
            final = current_cash_ratio - self.cash_min
            constraints.append(f"现金保底{self.cash_min*100:.0f}%")
        
        final = max(0, final)
        
        # 风险计算（假设止损5%）
        risk = final * 0.05
        
        return PositionResult(
            kelly_raw=kelly,
            half_kelly=half_kelly,
            after_env=adjusted,
            final_position=final,
            cash_after=current_cash_ratio - final,
            risk_per_trade=risk,
            constraints_applied=constraints
        )
    
    def _get_env_multiplier(self, env: str) -> float:
        """获取环境调整系数"""
        multipliers = {
            'bull': 1.0,
            '震荡偏强': 0.8,
            '震荡': 0.6,
            '震荡偏弱': 0.4,
            'bear': 0.2
        }
        return multipliers.get(env, 0.6)
    
    def suggest_by_strategy(self, strategy_name: str, market_env: str,
                           score_grade: str, current_cash: float = 1.0) -> PositionResult:
        """
        根据战法建议仓位
        
        Args:
            strategy_name: 战法名称
            market_env: 市场环境
            score_grade: 评分等级
            current_cash: 当前现金比例
        """
        # 各战法默认参数
        strategy_params = {
            '龙头首阴': {'win_rate': 0.55, 'pl_ratio': 2.5},
            '龙回头': {'win_rate': 0.50, 'pl_ratio': 3.0},
            '均线多头': {'win_rate': 0.60, 'pl_ratio': 2.0},
            '箱体突破': {'win_rate': 0.45, 'pl_ratio': 4.0},
            '量价齐升': {'win_rate': 0.55, 'pl_ratio': 2.5},
            '缩量回踩': {'win_rate': 0.58, 'pl_ratio': 2.0},
            '戴维斯双击': {'win_rate': 0.65, 'pl_ratio': 3.0}
        }
        
        params = strategy_params.get(strategy_name, {'win_rate': 0.50, 'pl_ratio': 2.0})
        
        return self.calculate(
            win_rate=params['win_rate'],
            profit_loss_ratio=params['pl_ratio'],
            market_env=market_env,
            score_grade=score_grade,
            current_cash_ratio=current_cash
        )


# 全局实例
sizer = PositionSizing()


def calculate_position(win_rate: float, profit_loss_ratio: float,
                      market_env: str, score_grade: str,
                      current_cash: float = 1.0) -> PositionResult:
    """便捷函数：计算仓位"""
    return sizer.calculate(win_rate, profit_loss_ratio, market_env, score_grade, current_cash)


def suggest_position(strategy: str, market_env: str, score_grade: str, current_cash: float = 1.0) -> PositionResult:
    """便捷函数：按战法建议仓位"""
    return sizer.suggest_by_strategy(strategy, market_env, score_grade, current_cash)


if __name__ == "__main__":
    # 测试
    result = calculate_position(0.55, 2.5, "bull", "A")
    print(f"\n仓位计算结果:")
    print(f"  原始凯利: {result.kelly_raw*100:.1f}%")
    print(f"  半凯利: {result.half_kelly*100:.1f}%")
    print(f"  环境调整后: {result.after_env*100:.1f}%")
    print(f"  最终仓位: {result.final_position*100:.1f}%")
    print(f"  剩余现金: {result.cash_after*100:.1f}%")
    print(f"  单笔风险: {result.risk_per_trade*100:.2f}%")
    if result.constraints_applied:
        print(f"  应用约束: {', '.join(result.constraints_applied)}")
