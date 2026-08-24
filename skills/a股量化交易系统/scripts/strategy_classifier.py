#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 策略类型判定
过夜/波段/观望 + 消息面硬排除
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from data_gateway import get_quote, get_kline
from scoring_engine_v3_1 import score_stock


@dataclass
class StrategyResult:
    """策略判定结果"""
    code: str
    name: str
    strategy_type: str      # 过夜/波段/两者皆可/观望
    overnight_score: float  # 过夜评分 0-20
    swing_score: float      # 波段评分 0-15
    position_pct: float     # 建议仓位 0-1
    reason: str             # 判定理由
    exclusions: List[str]   # 排除项
    signals: Dict           # 详细信号


class StrategyClassifier:
    """策略类型判定器"""
    
    def __init__(self):
        self.overnight_weights = {
            'volume': 0.25,      # 量能
            'chip': 0.20,        # 筹码
            'news': 0.20,        # 消息
            'tech': 0.20,        # 技术
            'liquidity': 0.15    # 流动性
        }
        self.swing_weights = {
            'trend': 0.25,       # 趋势
            'fundamental': 0.25, # 基本面
            'capital': 0.20,     # 资金
            'sector': 0.15,      # 行业
            'catalyst': 0.15     # 催化
        }
    
    def classify(self, code: str, market_env: str = "震荡") -> StrategyResult:
        """
        判定股票适合什么策略
        
        Args:
            code: 股票代码
            market_env: 市场环境
            
        Returns:
            StrategyResult
        """
        quote = get_quote(code)
        if not quote:
            return StrategyResult(code, "未知", "观望", 0, 0, 0, "无法获取数据", [], {})
        
        # Step 1: 消息面硬排除
        exclusions = self._check_exclusions(code)
        if exclusions:
            return StrategyResult(
                code=code,
                name=quote.name,
                strategy_type="观望",
                overnight_score=0,
                swing_score=0,
                position_pct=0,
                reason=f"硬排除: {', '.join(exclusions)}",
                exclusions=exclusions,
                signals={}
            )
        
        # Step 2: 评分
        score_result = score_stock(code, market_env)
        
        # Step 3: 过夜评分
        overnight_score = self._score_overnight(code, quote, market_env)
        
        # Step 4: 波段评分
        swing_score = self._score_swing(code, quote, score_result, market_env)
        
        # Step 5: 判定策略类型
        strategy_type, position_pct, reason = self._determine_strategy(
            overnight_score, swing_score, score_result.grade, market_env
        )
        
        return StrategyResult(
            code=code,
            name=quote.name,
            strategy_type=strategy_type,
            overnight_score=overnight_score,
            swing_score=swing_score,
            position_pct=position_pct,
            reason=reason,
            exclusions=[],
            signals={
                'total_score': score_result.total_score,
                'grade': score_result.grade,
                'overnight_details': self._get_overnight_details(code, quote),
                'swing_details': self._get_swing_details(code, quote, score_result)
            }
        )
    
    def _check_exclusions(self, code: str) -> List[str]:
        """消息面硬排除检查"""
        exclusions = []
        
        # 这里需要接入数据源检查以下信息：
        # 1. 是否有监管函/立案调查
        # 2. 是否业绩暴雷（预告下滑>50%）
        # 3. 是否有大额减持计划（>2%）
        # 4. 是否被ST/
        # 5. 是否有重大利空公告
        
        # 简化版：假设需要查询数据库或API
        # 实际使用时需要接入ifind/ftshare等数据源
        
        return exclusions  # 空列表表示无排除
    
    def _score_overnight(self, code: str, quote, market_env: str) -> float:
        """
        过夜评分 0-20分
        适合超短线，次日即出
        """
        score = 0
        
        # 量能（5分）
        change = quote.change_pct
        if change > 5:  # 放量大涨
            score += 5
        elif change > 2:
            score += 3
        elif change > 0:
            score += 1
        
        # 筹码（4分）
        # 简化：用换手率和价格位置判断
        turnover = getattr(quote, 'turnover_rate', 5)
        if 3 <= turnover <= 10:  # 活跃但不过度
            score += 4
        elif turnover > 10:
            score += 2  # 太活跃，可能出货
        
        # 消息（4分）
        # 简化：假设无重大消息
        score += 3  # 中性偏正面
        
        # 技术（4分）
        if change > 5:  # 强势突破
            score += 4
        elif change > 2:
            score += 2
        
        # 流动性（3分）
        volume = quote.volume
        if volume > 5000000:  # 成交量大，流动性好
            score += 3
        elif volume > 1000000:
            score += 2
        else:
            score += 1
        
        return min(20, score)
    
    def _score_swing(self, code: str, quote, score_result, market_env: str) -> float:
        """
        波段评分 0-15分
        适合持有5-15天
        """
        score = 0
        
        # 趋势（4分）
        if quote.change_pct > 5:  # 强势
            score += 4
        elif quote.change_pct > 0:
            score += 2
        
        # 基本面（4分）
        if score_result.grade in ['S', 'A']:  # 基本面好
            score += 4
        elif score_result.grade == 'B':
            score += 2
        
        # 资金（3分）
        if quote.change_pct > 3:  # 资金流入
            score += 3
        elif quote.change_pct > 0:
            score += 1
        
        # 行业（2分）
        # 简化：假设行业中性
        score += 1
        
        # 催化（2分）
        # 简化：假设有一定催化
        score += 1
        
        return min(15, score)
    
    def _determine_strategy(self, overnight: float, swing: float, 
                           grade: str, market_env: str) -> tuple:
        """
        判定最终策略类型
        
        Returns:
            (strategy_type, position_pct, reason)
        """
        # 评分阈值
        if overnight >= 15 and swing >= 10:
            return "两者皆可", self._get_position(grade, market_env, 0.8), \
                   "过夜和波段评分均优秀"
        elif overnight >= 12:
            return "过夜", self._get_position(grade, market_env, 0.6), \
                   "过夜评分优秀，适合超短线"
        elif swing >= 8:
            return "波段", self._get_position(grade, market_env, 0.7), \
                   "波段评分优秀，适合持股5-15天"
        elif overnight >= 8 or swing >= 5:
            return "观望", 0, \
                   "评分一般，建议观望等待更好时机"
        else:
            return "观望", 0, \
                   "评分不足，不符合入场条件"
    
    def _get_position(self, grade: str, market_env: str, base: float) -> float:
        """根据等级和环境计算仓位"""
        grade_map = {'S': 1.2, 'A': 1.0, 'B': 0.6, 'C': 0.3, 'D': 0}
        env_map = {'bull': 1.0, '震荡': 0.6, 'bear': 0.2}
        
        position = base * grade_map.get(grade, 0) * env_map.get(market_env, 0.6)
        return min(0.2, max(0, position))  # 单票不超过20%
    
    def _get_overnight_details(self, code: str, quote) -> Dict:
        """获取过夜评分详情"""
        return {
            'volume_score': min(5, quote.change_pct) if quote.change_pct > 0 else 0,
            'turnover': getattr(quote, 'turnover_rate', 5),
            'price_change': quote.change_pct
        }
    
    def _get_swing_details(self, code: str, quote, score_result) -> Dict:
        """获取波段评分详情"""
        return {
            'grade': score_result.grade,
            'total_score': score_result.total_score,
            'trend': 'up' if quote.change_pct > 0 else 'down'
        }


# 全局分类器
classifier = StrategyClassifier()


def classify_strategy(code: str, market_env: str = "震荡") -> StrategyResult:
    """便捷函数：策略判定"""
    return classifier.classify(code, market_env)


if __name__ == "__main__":
    # 测试
    result = classify_strategy("000983", "震荡")
    print(f"\n{result.name}({result.code}) 策略判定:")
    print(f"  策略类型: {result.strategy_type}")
    print(f"  过夜评分: {result.overnight_score}/20")
    print(f"  波段评分: {result.swing_score}/15")
    print(f"  建议仓位: {result.position_pct*100:.1f}%")
    print(f"  判定理由: {result.reason}")
