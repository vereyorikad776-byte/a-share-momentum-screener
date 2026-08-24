#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 四层框架评分引擎 v4.0
新增: 腾讯全字段行情 + 北向资金 + 融资融券 + 资金流向 + 龙虎榜
"""

import json
import numpy as np
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
    data_sources: List[str] # 数据来源列表


class ScoringEngineV40:
    """四层框架评分引擎 v4.0 - 全栈数据源增强"""
    
    def __init__(self):
        self.value_weight = 30
        self.finance_weight = 20
        self.capital_weight = 25
        self.risk_weight = 25
        self._cache = {}
    
    def score(self, code: str, market_env: str = "震荡") -> ScoreResult:
        """对股票进行四层框架评分"""
        # 获取基础数据
        quote = get_quote(code)
        klines = get_kline(code, "day", 60)
        
        if not quote:
            return ScoreResult(code=code, name="未知", value_score=0, finance_score=0,
                             capital_score=0, risk_score=0, total_score=0, grade="D",
                             details={}, data_sources=[])
        
        # 获取腾讯全字段行情
        tencent_data = self._get_tencent_data(code)
        
        # 获取北向资金
        northbound = self._get_northbound_data()
        
        # 获取融资融券
        margin = self._get_margin_data(code)
        
        # 获取资金流向
        fund_flow = self._get_fund_flow(code)
        
        # 获取龙虎榜
        dragon_tiger = self._get_dragon_tiger(code)
        
        # 四层评分
        value_details = self._score_value(code, quote, klines, tencent_data)
        finance_details = self._score_finance(code, quote)
        capital_details = self._score_capital_v4(code, quote, tencent_data, northbound, margin, fund_flow, dragon_tiger)
        risk_details = self._score_risk_v4(code, quote, klines, dragon_tiger)
        
        # 计算总分
        total = value_details['total'] + finance_details['total'] + capital_details['total'] + risk_details['total']
        grade = self._get_grade(total)
        
        # 收集数据来源
        sources = list(set(
            value_details.get('sources', []) +
            finance_details.get('sources', []) +
            capital_details.get('sources', []) +
            risk_details.get('sources', [])
        ))
        
        return ScoreResult(
            code=code, name=quote.name,
            value_score=value_details['total'],
            finance_score=finance_details['total'],
            capital_score=capital_details['total'],
            risk_score=risk_details['total'],
            total_score=total, grade=grade,
            details={'value': value_details, 'finance': finance_details,
                    'capital': capital_details, 'risk': risk_details},
            data_sources=sources
        )
    
    # ============ 数据获取 ============
    
    def _get_tencent_data(self, code: str) -> Dict:
        """获取腾讯全字段行情"""
        try:
            from stock_data_skill_adapter import tencent_quote
            data = tencent_quote([code])
            return data.get(code, {})
        except Exception:
            return {}
    
    def _get_northbound_data(self) -> Dict:
        """获取北向资金"""
        try:
            from stock_data_skill_adapter import hsgt_summary
            return hsgt_summary()
        except Exception:
            return {}
    
    def _get_margin_data(self, code: str) -> Dict:
        """获取融资融券"""
        try:
            from stock_data_skill_adapter import margin_summary
            return margin_summary(code)
        except Exception:
            return {}
    
    def _get_fund_flow(self, code: str) -> List[Dict]:
        """获取资金流向"""
        try:
            from stock_data_skill_adapter import fund_flow_daily
            return fund_flow_daily(code, days=5)
        except Exception:
            return []
    
    def _get_dragon_tiger(self, code: str) -> Dict:
        """获取龙虎榜"""
        try:
            from stock_data_skill_adapter import dragon_tiger_board
            return dragon_tiger_board(code, look_back=30)
        except Exception:
            return {}
    
    # ============ 价值评分（30分）- 增强版 ============
    
    def _score_value(self, code: str, quote, klines, tencent_data: Dict) -> Dict:
        """价值维度评分 - 使用腾讯PE/PB/市值"""
        score = 0
        details = {}
        sources = []
        
        # 优先用腾讯的PE/PB，更全
        pe = tencent_data.get('pe_ttm', 20)
        pb = tencent_data.get('pb', 2)
        mcap = tencent_data.get('mcap_yi', 100)
        
        if pe > 0:
            sources.append('tencent')
        
        # PE分位（10分）
        if pe < 10:
            pe_score = 10
        elif pe < 15:
            pe_score = 8
        elif pe < 20:
            pe_score = 6
        elif pe < 30:
            pe_score = 3
        else:
            pe_score = 0
        score += pe_score
        details['pe'] = pe_score
        details['pe_value'] = pe
        
        # PB（5分）
        if pb < 1:
            pb_score = 5
        elif pb < 2:
            pb_score = 3
        elif pb < 3:
            pb_score = 1
        else:
            pb_score = 0
        score += pb_score
        details['pb'] = pb_score
        details['pb_value'] = pb
        
        # 市值空间（5分）
        if mcap < 100:
            cap_score = 5  # 小盘成长空间大
        elif mcap < 500:
            cap_score = 4
        elif mcap < 2000:
            cap_score = 3
        else:
            cap_score = 2
        score += cap_score
        details['market_cap'] = cap_score
        details['mcap_yi'] = mcap
        
        # 量比（5分）- 腾讯数据
        vol_ratio = tencent_data.get('vol_ratio', 1)
        if 1.5 <= vol_ratio <= 5:
            vr_score = 5  # 适度放量
        elif vol_ratio > 5:
            vr_score = 3  # 过度放量，可能是出货
        elif vol_ratio > 1:
            vr_score = 2
        else:
            vr_score = 0  # 无量
        score += vr_score
        details['vol_ratio'] = vr_score
        details['vol_ratio_value'] = vol_ratio
        
        # 振幅（5分）- 适中为好
        amplitude = tencent_data.get('amplitude_pct', 3)
        if 3 <= amplitude <= 7:
            amp_score = 5
        elif amplitude > 7:
            amp_score = 2  # 波动太大
        else:
            amp_score = 1  # 太 stagnant
        score += amp_score
        details['amplitude'] = amp_score
        
        details['total'] = min(score, 30)
        details['sources'] = sources
        return details
    
    # ============ 财务评分（20分）- 不变 ============
    
    def _get_financial_data(self, code: str) -> Dict:
        """获取财务数据，多源优先级：FTShare → tushare Pro → iFinD"""
        try:
            from ftshare_adapter import get_full_financial_profile
            data = get_full_financial_profile(code)
            if data and 'error' not in data:
                mapped = {
                    'source': 'ftshare',
                    'roe': data.get('roe'),
                    'revenue_growth': data.get('total_revenue_yoy'),
                    'profit_growth': data.get('net_profit_yoy'),
                    'eps': data.get('eps'),
                    'debt_ratio': data.get('debt_ratio'),
                    'operating_cashflow': data.get('operating_cashflow'),
                }
                return mapped
        except Exception:
            pass
        
        try:
            from tushare_adapter import get_tushare_adapter
            adapter = get_tushare_adapter()
            if adapter.is_pro_available():
                data = adapter.get_financial_data(code)
                if data and 'error' not in data:
                    return data
        except Exception:
            pass
        
        try:
            from ifind_adapter import get_financial_data
            data = get_financial_data(code)
            if data and data.get('source') != 'mock':
                return data
        except Exception:
            pass
        
        return {'source': 'default'}
    
    def _score_finance(self, code: str, quote) -> Dict:
        """财务维度评分（20分）"""
        score = 0
        details = {}
        
        fin_data = self._get_financial_data(code)
        sources = [fin_data.get('source', 'default')]
        
        # ROE（6分）
        roe = fin_data.get('roe', 10)
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
        details['roe_value'] = roe
        
        # 营收增长（4分）
        revenue_growth = fin_data.get('revenue_growth', 10)
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
        gross_margin = fin_data.get('gross_margin', 20)
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
        cashflow = fin_data.get('operating_cashflow', 0)
        if cashflow > 0:
            cf_score = 6
        elif cashflow == 0:
            cf_score = 3
        else:
            cf_score = 0
        score += cf_score
        details['cashflow'] = cf_score
        
        details['total'] = min(score, 20)
        details['sources'] = sources
        return details
    
    # ============ 资金评分 v4（25分）- 大幅增强 ============
    
    def _score_capital_v4(self, code, quote, tencent_data, northbound, margin, fund_flow, dragon_tiger) -> Dict:
        """资金维度评分 v4 - 多源资金数据"""
        score = 0
        details = {}
        sources = []
        
        # 1. 主力资金流向（8分）- 用东财资金流向
        if fund_flow and len(fund_flow) >= 2:
            latest = fund_flow[0]
            main_net = latest.get('main_net_yi', 0)
            sources.append('eastmoney_fundflow')
            
            if main_net > 1:
                main_score = 8  # 主力大幅流入
            elif main_net > 0.3:
                main_score = 6
            elif main_net > 0:
                main_score = 3
            elif main_net > -0.3:
                main_score = 1
            else:
                main_score = 0  # 主力流出
        else:
            # 退回到用涨跌幅估算
            change = quote.change_pct
            if change > 5:
                main_score = 6
            elif change > 2:
                main_score = 4
            elif change > 0:
                main_score = 2
            else:
                main_score = 0
        score += main_score
        details['main_flow'] = main_score
        details['main_net_yi'] = fund_flow[0].get('main_net_yi', 0) if fund_flow else None
        
        # 2. 北向资金（5分）- 新数据源
        if northbound:
            total_net = northbound.get('total_net', 0)
            sources.append('northbound')
            
            # 北向整体流入加分
            if total_net > 50:
                nb_score = 5  # 外资大幅流入
            elif total_net > 20:
                nb_score = 3
            elif total_net > 0:
                nb_score = 1
            else:
                nb_score = 0
        else:
            nb_score = 2  # 默认中性
        score += nb_score
        details['northbound'] = nb_score
        details['northbound_net'] = northbound.get('total_net', 0) if northbound else None
        
        # 3. 融资融券（4分）- 新数据源
        if margin and margin.get('rzye_yi', 0) > 0:
            sources.append('margin')
            rz_change = margin.get('rz_change', 0)
            
            if rz_change > 0.5:
                margin_score = 4  # 融资大增，杠杆资金看好
            elif rz_change > 0:
                margin_score = 2
            elif rz_change > -0.5:
                margin_score = 1
            else:
                margin_score = 0  # 融资偿还
        else:
            margin_score = 2
        score += margin_score
        details['margin'] = margin_score
        details['rz_ye'] = margin.get('rzye_yi', 0) if margin else None
        
        # 4. 龙虎榜（4分）- 新数据源
        if dragon_tiger:
            board_count = dragon_tiger.get('board_count', 0)
            has_institution = dragon_tiger.get('has_institution', False)
            sources.append('dragon_tiger')
            
            if has_institution:
                dt_score = 4  # 机构参与龙虎榜，强烈信号
            elif board_count >= 3:
                dt_score = 3  # 频繁上榜
            elif board_count >= 1:
                dt_score = 2  # 近期上过榜
            else:
                dt_score = 2  # 无记录，中性
        else:
            dt_score = 2
        score += dt_score
        details['dragon_tiger'] = dt_score
        details['dt_board_count'] = dragon_tiger.get('board_count', 0) if dragon_tiger else 0
        
        # 5. 换手率（4分）- 腾讯数据
        turnover = tencent_data.get('turnover_pct', 3)
        if 3 <= turnover <= 10:
            tr_score = 4  # 活跃但不过度
        elif 1 <= turnover < 3:
            tr_score = 2  # 偏冷清
        elif turnover > 15:
            tr_score = 1  # 过度换手，可能是出货
        else:
            tr_score = 0
        score += tr_score
        details['turnover'] = tr_score
        details['turnover_pct'] = turnover
        
        details['total'] = min(score, 25)
        details['sources'] = sources
        return details
    
    # ============ 风控评分 v4（25分）- 增强 ============
    
    def _score_risk_v4(self, code, quote, klines, dragon_tiger) -> Dict:
        """风控维度评分 v4"""
        score = 0
        details = {}
        sources = []
        
        # 1. 波动率（6分）
        if len(klines) >= 20:
            closes = [k.close for k in klines[-20:]]
            returns = np.diff(closes) / closes[:-1]
            volatility = np.std(returns) * np.sqrt(252) * 100
            
            if volatility < 30:
                vol_score = 6
            elif volatility < 40:
                vol_score = 4
            elif volatility < 50:
                vol_score = 2
            else:
                vol_score = 0
        else:
            vol_score = 3
        score += vol_score
        details['volatility'] = vol_score
        
        # 2. 最大回撤（6分）
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
        
        # 3. 龙虎榜风险（4分）- 频繁上榜可能意味着高波动
        if dragon_tiger:
            board_count = dragon_tiger.get('board_count', 0)
            if board_count >= 5:
                dt_risk = 1  # 频繁上榜，高风险
            elif board_count >= 2:
                dt_risk = 2
            else:
                dt_risk = 4  # 稳定，少上榜
        else:
            dt_risk = 3
        score += dt_risk
        details['dragon_tiger_risk'] = dt_risk
        
        # 4. 负债率（4分）
        fin_data = self._get_financial_data(code)
        debt_ratio = fin_data.get('debt_ratio') or 40
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
        
        # 5. 涨跌停风险（5分）
        change = quote.change_pct
        if abs(change) < 3:
            limit_score = 5  # 正常波动
        elif abs(change) < 7:
            limit_score = 3  # 较大波动
        elif abs(change) < 9.5:
            limit_score = 1  # 接近涨停/跌停
        else:
            limit_score = 0  # 涨停或跌停，风险极高
        score += limit_score
        details['price_movement'] = limit_score
        
        details['total'] = min(score, 25)
        details['sources'] = sources
        return details
    
    def _get_grade(self, total: float) -> str:
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


# 全局引擎
engine = ScoringEngineV40()


def score_stock(code: str, market_env: str = "震荡") -> ScoreResult:
    return engine.score(code, market_env)


if __name__ == "__main__":
    result = score_stock("000001")
    print(f"\n{result.name}({result.code}) 评分结果:")
    print(f"  价值: {result.value_score}/30")
    print(f"  财务: {result.finance_score}/20")
    print(f"  资金: {result.capital_score}/25")
    print(f"  风控: {result.risk_score}/25")
    print(f"  总分: {result.total_score}/100")
    print(f"  评级: {result.grade}")
    print(f"  数据来源: {', '.join(result.data_sources)}")
    
    # 资金详情
    capital = result.details.get('capital', {})
    print(f"\n  资金详情:")
    print(f"    主力净流入: {capital.get('main_net_yi', 'N/A')}亿")
    print(f"    北向资金: {capital.get('northbound_net', 'N/A')}亿")
    print(f"    融资余额: {capital.get('rz_ye', 'N/A')}亿")
    print(f"    龙虎榜次数: {capital.get('dt_board_count', 0)}")
    print(f"    换手率: {capital.get('turnover_pct', 'N/A')}%")
