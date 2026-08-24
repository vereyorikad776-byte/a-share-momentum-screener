#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 五维择时模型
估值/资金/技术/情绪/基本面 → bull/震荡/bear
"""

import numpy as np
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class TimingResult:
    """择时结果"""
    score: float            # 综合评分 0-100
    environment: str        # bull/震荡/bear
    position_suggest: float # 建议仓位 0-1
    details: Dict           # 各维度评分


class FiveDimensionTiming:
    """五维择时模型"""
    
    def __init__(self):
        self.weights = {
            'valuation': 0.20,
            'capital': 0.25,
            'technical': 0.25,
            'sentiment': 0.20,
            'fundamental': 0.10
        }
    
    def evaluate(self, market_data: Dict = None) -> TimingResult:
        """
        五维择时评估
        
        Args:
            market_data: 市场数据，如果为None则使用默认值/模拟数据
            
        Returns:
            TimingResult
        """
        if market_data is None:
            market_data = self._get_default_data()
        
        # 各维度评分
        valuation_score = self._score_valuation(market_data)
        capital_score = self._score_capital(market_data)
        technical_score = self._score_technical(market_data)
        sentiment_score = self._score_sentiment(market_data)
        fundamental_score = self._score_fundamental(market_data)
        
        # 综合评分
        total = (
            valuation_score * self.weights['valuation'] +
            capital_score * self.weights['capital'] +
            technical_score * self.weights['technical'] +
            sentiment_score * self.weights['sentiment'] +
            fundamental_score * self.weights['fundamental']
        )
        
        # 判定环境
        env, position = self._determine_environment(total)
        
        return TimingResult(
            score=total,
            environment=env,
            position_suggest=position,
            details={
                'valuation': valuation_score,
                'capital': capital_score,
                'technical': technical_score,
                'sentiment': sentiment_score,
                'fundamental': fundamental_score
            }
        )
    
    def _get_default_data(self) -> Dict:
        """获取默认/模拟数据"""
        # 实际使用时需要从数据源获取
        return {
            # 估值维度
            'pe_percentile': 50,      # PE历史分位
            'erp': 3.0,               # 风险溢价
            
            # 资金维度
            'margin_change_5d': 0,    # 融资余额5日变化
            'north_flow_5d': 0,       # 北向5日流入(亿)
            'fund_issuance': 100,     # 基金发行量(亿/月)
            
            # 技术维度
            'ma_trend': 'flat',       # 均线趋势
            'volume_trend': 'flat',   # 成交量趋势
            'macd_status': 'neutral', # MACD状态
            
            # 情绪维度
            'advance_decline_ratio': 1.0,  # 涨跌比
            'limit_up_count': 50,     # 涨停数
            '炸板率': 0.3,             # 炸板率
            'panic_index': 25,        # 恐慌指数
            
            # 基本面
            'pmi': 50,                # PMI
            'credit_growth': 10,      # 社融增速
            'interest_rate_trend': 'stable'  # 利率趋势
        }
    
    def _score_valuation(self, data: Dict) -> float:
        """估值维度评分"""
        score = 0
        
        # PE分位（50分）
        pe = data.get('pe_percentile', 50)
        if pe < 20:
            score += 50
        elif pe < 30:
            score += 40
        elif pe < 50:
            score += 30
        elif pe < 70:
            score += 20
        else:
            score += 10
        
        # 风险溢价（50分）
        erp = data.get('erp', 3.0)
        if erp > 5:
            score += 50
        elif erp > 4:
            score += 40
        elif erp > 3:
            score += 30
        elif erp > 2:
            score += 20
        else:
            score += 10
        
        return score
    
    def _score_capital(self, data: Dict) -> float:
        """资金维度评分"""
        score = 0
        
        # 融资余额（35分）
        margin = data.get('margin_change_5d', 0)
        if margin > 3:
            score += 35
        elif margin > 0:
            score += 25
        elif margin > -3:
            score += 15
        else:
            score += 5
        
        # 北向资金（35分）
        north = data.get('north_flow_5d', 0)
        if north > 100:
            score += 35
        elif north > 50:
            score += 28
        elif north > 0:
            score += 20
        elif north > -50:
            score += 10
        else:
            score += 5
        
        # 基金发行（30分）
        fund = data.get('fund_issuance', 100)
        if fund > 300:
            score += 30
        elif fund > 200:
            score += 25
        elif fund > 100:
            score += 20
        elif fund > 50:
            score += 10
        else:
            score += 5
        
        return score
    
    def _score_technical(self, data: Dict) -> float:
        """技术维度评分"""
        score = 0
        
        # 均线趋势（40分）
        ma = data.get('ma_trend', 'flat')
        if ma == 'bull':
            score += 40
        elif ma == 'bullish':
            score += 30
        elif ma == 'flat':
            score += 20
        elif ma == 'bearish':
            score += 10
        else:
            score += 0
        
        # 成交量（30分）
        vol = data.get('volume_trend', 'flat')
        if vol == 'increase':
            score += 30
        elif vol == 'stable':
            score += 20
        else:
            score += 10
        
        # MACD（30分）
        macd = data.get('macd_status', 'neutral')
        if macd == 'strong_bull':
            score += 30
        elif macd == 'bull':
            score += 25
        elif macd == 'neutral':
            score += 15
        elif macd == 'bear':
            score += 5
        else:
            score += 0
        
        return score
    
    def _score_sentiment(self, data: Dict) -> float:
        """情绪维度评分"""
        score = 0
        
        # 涨跌比（35分）
        ad = data.get('advance_decline_ratio', 1.0)
        if ad > 1.5:
            score += 35
        elif ad > 1.2:
            score += 28
        elif ad > 1.0:
            score += 20
        elif ad > 0.8:
            score += 12
        else:
            score += 5
        
        # 涨停数/炸板率（35分）
        limit_up = data.get('limit_up_count', 50)
        炸板率 = data.get('炸板率', 0.3)
        
        if limit_up > 100 and 炸板率 < 0.2:
            score += 35
        elif limit_up > 50 and 炸板率 < 0.3:
            score += 25
        elif limit_up > 30:
            score += 15
        else:
            score += 5
        
        # 恐慌指数（30分）- 反向指标
        panic = data.get('panic_index', 25)
        if panic > 40:  # 极度恐惧，机会
            score += 30
        elif panic > 30:
            score += 25
        elif panic > 20:
            score += 15
        elif panic > 15:
            score += 10
        else:  # 贪婪
            score += 5
        
        return score
    
    def _score_fundamental(self, data: Dict) -> float:
        """基本面维度评分"""
        score = 0
        
        # PMI（50分）
        pmi = data.get('pmi', 50)
        if pmi > 52:
            score += 50
        elif pmi > 50:
            score += 40
        elif pmi > 48:
            score += 25
        else:
            score += 10
        
        # 社融增速（30分）
        credit = data.get('credit_growth', 10)
        if credit > 12:
            score += 30
        elif credit > 10:
            score += 25
        elif credit > 8:
            score += 15
        else:
            score += 5
        
        # 利率趋势（20分）
        rate = data.get('interest_rate_trend', 'stable')
        if rate == 'down':
            score += 20
        elif rate == 'stable':
            score += 15
        else:
            score += 5
        
        return score
    
    def _determine_environment(self, score: float) -> tuple:
        """根据综合评分判定市场环境"""
        if score >= 80:
            return "bull", 0.75
        elif score >= 60:
            return "震荡偏强", 0.55
        elif score >= 45:
            return "震荡", 0.35
        elif score >= 30:
            return "震荡偏弱", 0.25
        else:
            return "bear", 0.10


# 全局实例
timing = FiveDimensionTiming()


def get_market_timing(market_data: Dict = None) -> TimingResult:
    """便捷函数：获取市场择时"""
    return timing.evaluate(market_data)


if __name__ == "__main__":
    # 测试
    result = get_market_timing()
    print(f"\n五维择时结果:")
    print(f"  综合评分: {result.score:.1f}")
    print(f"  市场环境: {result.environment}")
    print(f"  建议仓位: {result.position_suggest*100:.0f}%")
    print(f"  各维度评分:")
    for dim, score in result.details.items():
        print(f"    {dim}: {score:.1f}")
