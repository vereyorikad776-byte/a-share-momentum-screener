#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 四层框架评分引擎
价值30/财务20/资金25/风控25
"""

import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from data_gateway import get_quote, get_kline


@dataclass
class ScoreResult:
    """评分结果"""
    code: str
    name: str
    value_score: float      # 价值 30分
    finance_score: float    # 财务 20分
    capital_score: float    # 资金 25分
    risk_score: float       # 风控 25分
    total_score: float      # 总分
    grade: str              # S/A/B/C/D
    details: Dict           # 详细评分


class ScoringEngineV31:
    """四层框架评分引擎 v3.1"""
    
    def __init__(self):
        self.value_weight = 30
        self.finance_weight = 20
        self.capital_weight = 25
        self.risk_weight = 25
    
    def score(self, code: str, market_env: str = "震荡") -> ScoreResult:
        """
        对股票进行四层框架评分
        
        Args:
            code: 股票代码
            market_env: 市场环境 bull/震荡/bear
            
        Returns:
            ScoreResult
        """
        # 获取基础数据
        quote = get_quote(code)
        klines = get_kline(code, "day", 60)
        
        if not quote:
            return ScoreResult(code=code, name="未知", value_score=0, finance_score=0,
                             capital_score=0, risk_score=0, total_score=0, grade="D", details={})
        
        # 四层评分
        value_details = self._score_value(code, quote, klines)
        finance_details = self._score_finance(code, quote)
        capital_details = self._score_capital(code, quote, klines)
        risk_details = self._score_risk(code, quote, klines)
        
        # 计算总分
        value_score = value_details['total']
        finance_score = finance_details['total']
        capital_score = capital_details['total']
        risk_score = risk_details['total']
        
        total = value_score + finance_score + capital_score + risk_score
        
        # 评级
        grade = self._get_grade(total)
        
        return ScoreResult(
            code=code,
            name=quote.name,
            value_score=value_score,
            finance_score=finance_score,
            capital_score=capital_score,
            risk_score=risk_score,
            total_score=total,
            grade=grade,
            details={
                'value': value_details,
                'finance': finance_details,
                'capital': capital_details,
                'risk': risk_details
            }
        )
    
    def _score_value(self, code: str, quote, klines) -> Dict:
        """价值维度评分（30分）- 优先使用iFinD财务数据"""
        score = 0
        details = {}
        
        # 尝试获取iFinD财务数据
        fin_data = self._get_financial_data(code)
        
        # PE分位（8分）
        pe = fin_data.get('pe', getattr(quote, 'pe', 20))
        if pe < 10:
            pe_score = 8
        elif pe < 15:
            pe_score = 6
        elif pe < 20:
            pe_score = 4
        elif pe < 30:
            pe_score = 2
        else:
            pe_score = 0
        score += pe_score
        details['pe'] = pe_score
        
        # PEG（6分）
        peg = fin_data.get('peg', getattr(quote, 'peg', 1.5))
        if peg < 0.8:
            peg_score = 6
        elif peg < 1.0:
            peg_score = 5
        elif peg < 1.2:
            peg_score = 4
        elif peg < 1.5:
            peg_score = 2
        else:
            peg_score = 0
        score += peg_score
        details['peg'] = peg_score
        
        # 股息率（4分）
        dividend = fin_data.get('dividend_yield', getattr(quote, 'dividend_yield', 0))
        if dividend > 5:
            div_score = 4
        elif dividend > 3:
            div_score = 3
        elif dividend > 2:
            div_score = 2
        elif dividend > 1:
            div_score = 1
        else:
            div_score = 0
        score += div_score
        details['dividend'] = div_score
        
        # 行业估值排名（6分）
        industry_rank = fin_data.get('industry_rank', 50)
        if industry_rank < 20:
            ir_score = 6
        elif industry_rank < 40:
            ir_score = 4
        elif industry_rank < 60:
            ir_score = 3
        else:
            ir_score = 1
        score += ir_score
        details['industry_rank'] = ir_score
        
        # 市值空间（6分）
        market_cap = getattr(quote, 'market_cap', fin_data.get('market_cap', 100))
        if market_cap < 50:
            cap_score = 6
        elif market_cap < 200:
            cap_score = 4
        elif market_cap < 1000:
            cap_score = 3
        else:
            cap_score = 2
        score += cap_score
        details['market_cap'] = cap_score
        
        details['total'] = score
        details['source'] = fin_data.get('source', 'default')
        return details
    
    def _get_financial_data(self, code: str) -> Dict:
        """获取财务数据，优先iFinD"""
        try:
            from ifind_adapter import get_financial_data
            data = get_financial_data(code)
            if data and data.get('source') != 'mock':
                return data
        except Exception:
            pass
        
        # 回退到默认值
        return {'source': 'default'}
    
    def _score_finance(self, code: str, quote) -> Dict:
        """财务维度评分（20分）- 优先使用iFinD财务数据"""
        score = 0
        details = {}
        
        fin_data = self._get_financial_data(code)
        
        # ROE（6分）
        roe = fin_data.get('roe', getattr(quote, 'roe', 10))
        if roe > 20:
            roe_score = 6
        elif roe > 15:
            roe_score = 5
        elif roe > 10:
            roe_score = 3
        elif roe > 5:
            roe_score = 1
        else:
            roe_score = 0
        score += roe_score
        details['roe'] = roe_score
        
        # 营收增长（4分）
        revenue_growth = fin_data.get('revenue_growth', getattr(quote, 'revenue_growth', 10))
        if revenue_growth > 50:
            rev_score = 4
        elif revenue_growth > 30:
            rev_score = 3
        elif revenue_growth > 15:
            rev_score = 2
        elif revenue_growth > 0:
            rev_score = 1
        else:
            rev_score = 0
        score += rev_score
        details['revenue_growth'] = rev_score
        
        # 毛利率（4分）
        gross_margin = fin_data.get('gross_margin', getattr(quote, 'gross_margin', 20))
        if gross_margin > 50:
            gm_score = 4
        elif gross_margin > 30:
            gm_score = 3
        elif gross_margin > 20:
            gm_score = 2
        elif gross_margin > 10:
            gm_score = 1
        else:
            gm_score = 0
        score += gm_score
        details['gross_margin'] = gm_score
        
        # 现金流质量（6分）
        cashflow_ratio = fin_data.get('cashflow_ratio', getattr(quote, 'cashflow_ratio', 0.8))
        if cashflow_ratio > 1.2:
            cf_score = 6
        elif cashflow_ratio > 0.8:
            cf_score = 4
        elif cashflow_ratio > 0.5:
            cf_score = 2
        else:
            cf_score = 0
        score += cf_score
        details['cashflow'] = cf_score
        
        details['total'] = score
        details['source'] = fin_data.get('source', 'default')
        return details
    
    def _score_capital(self, code: str, quote, klines) -> Dict:
        """资金维度评分（25分）"""
        score = 0
        details = {}
        
        # 主力净流入（8分）- 使用涨跌幅和成交量估算
        change = quote.change_pct
        volume = quote.volume
        
        if change > 5 and volume > 1000000:
            main_score = 8  # 放量大涨，主力流入
        elif change > 0:
            main_score = 5
        elif change > -3:
            main_score = 2
        else:
            main_score = 0
        score += main_score
        details['main_flow'] = main_score
        
        # 换手率（5分）
        turnover_rate = getattr(quote, 'turnover_rate', 3)
        if 3 <= turnover_rate <= 8:
            tr_score = 5
        elif 1 <= turnover_rate < 3:
            tr_score = 3
        elif turnover_rate > 15:
            tr_score = 1
        else:
            tr_score = 0
        score += tr_score
        details['turnover'] = tr_score
        
        # 北向资金（6分）- 简化
        details['north_flow'] = 3  # 默认中性
        score += 3
        
        # 大单比例（6分）- 简化
        if change > 3:
            big_order = 6
        elif change > 0:
            big_order = 4
        else:
            big_order = 1
        score += big_order
        details['big_order'] = big_order
        
        details['total'] = score
        return details
    
    def _score_risk(self, code: str, quote, klines) -> Dict:
        """风控维度评分（25分）"""
        score = 0
        details = {}
        
        # 波动率（6分）
        if len(klines) >= 20:
            closes = [k.close for k in klines[-20:]]
            import numpy as np
            returns = np.diff(closes) / closes[:-1]
            volatility = np.std(returns) * np.sqrt(252) * 100  # 年化波动率
            
            if volatility < 30:
                vol_score = 6
            elif volatility < 40:
                vol_score = 4
            elif volatility < 50:
                vol_score = 2
            else:
                vol_score = 0
        else:
            vol_score = 3  # 默认中等
        score += vol_score
        details['volatility'] = vol_score
        
        # 最大回撤（6分）
        if len(klines) >= 60:
            closes = [k.close for k in klines]
            max_dd = 0
            peak = closes[0]
            for c in closes:
                if c > peak:
                    peak = c
                dd = (peak - c) / peak * 100
                if dd > max_dd:
                    max_dd = dd
            
            if max_dd < 10:
                dd_score = 6
            elif max_dd < 15:
                dd_score = 4
            elif max_dd < 20:
                dd_score = 2
            else:
                dd_score = 0
        else:
            dd_score = 3
        score += dd_score
        details['max_drawdown'] = dd_score
        
        # 质押率（4分）
        pledge_ratio = getattr(quote, 'pledge_ratio', 0)
        if pledge_ratio == 0:
            pledge_score = 4
        elif pledge_ratio < 30:
            pledge_score = 3
        elif pledge_ratio < 50:
            pledge_score = 1
        else:
            pledge_score = 0
        score += pledge_score
        details['pledge'] = pledge_score
        
        # 负债率（4分）
        debt_ratio = getattr(quote, 'debt_ratio', 40)
        if debt_ratio < 30:
            debt_score = 4
        elif debt_ratio < 50:
            debt_score = 3
        elif debt_ratio < 70:
            debt_score = 1
        else:
            debt_score = 0
        score += debt_score
        details['debt'] = debt_score
        
        # 监管风险（5分）
        # 简化：假设无监管问题
        risk_score = 5
        score += risk_score
        details['regulatory'] = risk_score
        
        details['total'] = score
        return details
    
    def _get_grade(self, total: float) -> str:
        """根据总分评级"""
        if total >= 85:
            return "S"
        elif total >= 70:
            return "A"
        elif total >= 55:
            return "B"
        elif total >= 40:
            return "C"
        else:
            return "D"
    
    def batch_score(self, codes: List[str], market_env: str = "震荡") -> List[ScoreResult]:
        """批量评分"""
        results = []
        for code in codes:
            try:
                result = self.score(code, market_env)
                results.append(result)
            except Exception as e:
                print(f"评分失败 {code}: {e}")
        return sorted(results, key=lambda x: x.total_score, reverse=True)


# 全局引擎
engine = ScoringEngineV31()


def score_stock(code: str, market_env: str = "震荡") -> ScoreResult:
    """便捷函数：单票评分"""
    return engine.score(code, market_env)


def batch_score(codes: List[str], market_env: str = "震荡") -> List[ScoreResult]:
    """便捷函数：批量评分"""
    return engine.batch_score(codes, market_env)


if __name__ == "__main__":
    # 测试
    result = score_stock("000983")
    print(f"\n{result.name}({result.code}) 评分结果:")
    print(f"  价值: {result.value_score}/30")
    print(f"  财务: {result.finance_score}/20")
    print(f"  资金: {result.capital_score}/25")
    print(f"  风控: {result.risk_score}/25")
    print(f"  总分: {result.total_score}/100")
    print(f"  评级: {result.grade}")
