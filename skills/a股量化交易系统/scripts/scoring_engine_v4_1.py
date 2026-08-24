#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 四层框架评分引擎 v4.1
使用 stock_data_skill_adapter_v2 (实测可用数据源)

已接入数据源:
- 腾讯财经: PE/PB/市值/换手率/量比/振幅
- 新浪A股: 实时行情+五档盘口
- 同花顺北向: 分钟级资金流向
- Baostock: 历史K线+复权
- 巨潮资讯: 公告(风控加分项)
- FTShare: 财务数据(ROE/负债率)
"""

import json
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from data_gateway import get_quote, get_kline


@dataclass
class ScoreResult:
    code: str
    name: str
    value_score: float
    finance_score: float
    capital_score: float
    risk_score: float
    total_score: float
    grade: str
    details: Dict
    data_sources: List[str]


class ScoringEngineV41:
    """四层框架评分引擎 v4.1"""
    
    def __init__(self):
        self.value_weight = 30
        self.finance_weight = 20
        self.capital_weight = 25
        self.risk_weight = 25
    
    def score(self, code: str, market_env: str = "震荡") -> ScoreResult:
        quote = get_quote(code)
        klines = get_kline(code, "day", 60)
        
        if not quote:
            return ScoreResult(code=code, name="未知", value_score=0, finance_score=0,
                             capital_score=0, risk_score=0, total_score=0, grade="D",
                             details={}, data_sources=[])
        
        # 获取多源数据
        tencent = self._get_tencent(code)
        sina = self._get_sina(code)
        northbound = self._get_northbound()
        baostock_k = self._get_baostock_kline(code)
        announcements = self._get_announcements(code)
        
        # 四层评分
        value_details = self._score_value(code, quote, tencent, sina)
        finance_details = self._score_finance(code, quote)
        capital_details = self._score_capital(code, quote, tencent, northbound)
        risk_details = self._score_risk(code, quote, klines, baostock_k, announcements)
        
        total = value_details['total'] + finance_details['total'] + capital_details['total'] + risk_details['total']
        grade = self._get_grade(total)
        
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
    
    def _get_tencent(self, code: str) -> Dict:
        try:
            from stock_data_skill_adapter_v2 import tencent_quote
            data = tencent_quote([code])
            return data.get(code, {})
        except Exception:
            return {}
    
    def _get_sina(self, code: str) -> Dict:
        try:
            from stock_data_skill_adapter_v2 import sina_quote
            data = sina_quote([code])
            return data.get(code, {})
        except Exception:
            return {}
    
    def _get_northbound(self) -> Dict:
        try:
            from stock_data_skill_adapter_v2 import hsgt_summary
            return hsgt_summary()
        except Exception:
            return {}
    
    def _get_baostock_kline(self, code: str):
        try:
            from stock_data_skill_adapter_v2 import baostock_kline
            if code.startswith(("6", "9")):
                bs_code = f"sh.{code}"
            elif code.startswith("8"):
                bs_code = f"sh.{code}"
            else:
                bs_code = f"sz.{code}"
            from datetime import datetime, timedelta
            end = datetime.now()
            start = end - timedelta(days=120)
            return baostock_kline(bs_code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        except Exception:
            return None
    
    def _get_announcements(self, code: str) -> List:
        try:
            from stock_data_skill_adapter_v2 import cninfo_announcements
            return cninfo_announcements(code, page_size=3)
        except Exception:
            return []
    
    def _get_financial_data(self, code: str) -> Dict:
        try:
            from ftshare_adapter import get_full_financial_profile
            data = get_full_financial_profile(code)
            if data and 'error' not in data:
                return {
                    'source': 'ftshare',
                    'roe': data.get('roe'),
                    'revenue_growth': data.get('total_revenue_yoy'),
                    'debt_ratio': data.get('debt_ratio'),
                    'eps': data.get('eps'),
                }
        except Exception:
            pass
        return {'source': 'default'}
    
    # ============ 价值评分（30分） ============
    
    def _score_value(self, code, quote, tencent, sina) -> Dict:
        score = 0
        details = {}
        sources = []
        
        # 优先腾讯PE/PB
        pe = tencent.get('pe_ttm', 0) or getattr(quote, 'pe', 20)
        pb = tencent.get('pb', 0) or getattr(quote, 'pb', 2)
        mcap = tencent.get('mcap_yi', 0) or getattr(quote, 'market_cap', 100)
        
        if tencent:
            sources.append('tencent')
        
        # PE（10分）
        if 0 < pe < 10:
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
        if 0 < pb < 1:
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
        
        # 市值（5分）
        if 0 < mcap < 100:
            cap_score = 5
        elif mcap < 500:
            cap_score = 4
        elif mcap < 2000:
            cap_score = 3
        else:
            cap_score = 2
        score += cap_score
        details['market_cap'] = cap_score
        
        # 量比（5分）
        vol_ratio = tencent.get('vol_ratio', 1)
        if 1.5 <= vol_ratio <= 5:
            vr_score = 5
        elif vol_ratio > 5:
            vr_score = 3
        elif vol_ratio > 1:
            vr_score = 2
        else:
            vr_score = 0
        score += vr_score
        details['vol_ratio'] = vr_score
        
        # 振幅（5分）
        amplitude = tencent.get('amplitude_pct', 3)
        if 3 <= amplitude <= 7:
            amp_score = 5
        elif amplitude > 7:
            amp_score = 2
        else:
            amp_score = 1
        score += amp_score
        details['amplitude'] = amp_score
        
        details['total'] = min(score, 30)
        details['sources'] = sources
        return details
    
    # ============ 财务评分（20分） ============
    
    def _score_finance(self, code, quote) -> Dict:
        score = 0
        details = {}
        
        fin_data = self._get_financial_data(code)
        sources = [fin_data.get('source', 'default')]
        
        roe = fin_data.get('roe') or 10
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
        
        rev_growth = fin_data.get('revenue_growth') or 10
        if rev_growth > 50:
            rev_score = 4
        elif rev_growth > 30:
            rev_score = 3
        elif rev_growth > 15:
            rev_score = 2
        elif rev_growth > 0:
            rev_score = 1
        else:
            rev_score = 0
        score += rev_score
        details['revenue_growth'] = rev_score
        
        # 负债率（4分）
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
        
        # 现金流（6分）
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
    
    # ============ 资金评分（25分） ============
    
    def _score_capital(self, code, quote, tencent, northbound) -> Dict:
        score = 0
        details = {}
        sources = []
        
        # 1. 主力资金（8分）- 用涨跌幅+量比综合判断
        change = quote.change_pct
        vol_ratio = tencent.get('vol_ratio', 1)
        
        if change > 5 and vol_ratio > 2:
            main_score = 8
        elif change > 3 and vol_ratio > 1.5:
            main_score = 6
        elif change > 0:
            main_score = 4
        elif change > -3:
            main_score = 1
        else:
            main_score = 0
        score += main_score
        details['main_flow'] = main_score
        
        # 2. 北向资金（5分）
        if northbound:
            total_net = northbound.get('total_net', 0)
            sources.append('northbound')
            if total_net > 100:
                nb_score = 5
            elif total_net > 50:
                nb_score = 4
            elif total_net > 20:
                nb_score = 3
            elif total_net > 0:
                nb_score = 1
            else:
                nb_score = 0
        else:
            nb_score = 2
        score += nb_score
        details['northbound'] = nb_score
        details['northbound_net'] = northbound.get('total_net', 0) if northbound else None
        
        # 3. 换手率（4分）
        turnover = tencent.get('turnover_pct', 3)
        if 3 <= turnover <= 10:
            tr_score = 4
        elif 1 <= turnover < 3:
            tr_score = 2
        elif turnover > 15:
            tr_score = 1
        else:
            tr_score = 0
        score += tr_score
        details['turnover'] = tr_score
        details['turnover_pct'] = turnover
        
        # 4. 量价配合（4分）
        price = quote.price
        last_close = quote.pre_close
        if price > last_close and vol_ratio > 1.5:
            pv_score = 4  # 价涨量增
        elif price > last_close:
            pv_score = 2
        elif vol_ratio > 2:
            pv_score = 1  # 放量下跌，危险
        else:
            pv_score = 2
        score += pv_score
        details['price_volume'] = pv_score
        
        # 5. 盘口压力（4分）- 新浪五档
        try:
            from stock_data_skill_adapter_v2 import sina_quote
            sina_data = sina_quote([code])
            sina = sina_data.get(code, {})
            bid_vol = sina.get('bid1_vol', 0) + sina.get('bid2_vol', 0) + sina.get('bid3_vol', 0)
            ask_vol = sina.get('ask1_vol', 0) + sina.get('ask2_vol', 0) + sina.get('ask3_vol', 0)
            if bid_vol > ask_vol * 1.5:
                depth_score = 4  # 买盘强
            elif bid_vol > ask_vol:
                depth_score = 3
            else:
                depth_score = 1
            sources.append('sina')
        except:
            depth_score = 2
        score += depth_score
        details['depth'] = depth_score
        
        details['total'] = min(score, 25)
        details['sources'] = sources
        return details
    
    # ============ 风控评分（25分） ============
    
    def _score_risk(self, code, quote, klines, baostock_k, announcements) -> Dict:
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
        
        # 2. 最大回撤（6分）- 用Baostock数据更准
        if baostock_k is not None and not baostock_k.empty and 'close' in baostock_k.columns:
            closes = baostock_k['close'].dropna().values
            if len(closes) >= 20:
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
                sources.append('baostock')
            else:
                dd_score = 3
        else:
            dd_score = 3
        score += dd_score
        details['max_drawdown'] = dd_score
        
        # 3. 信息披露质量（4分）- 巨潮公告
        if announcements:
            sources.append('cninfo')
            # 近期有年报/半年报披露 = 信息透明
            has_report = any('年度报告' in (a.get('announcementTitle', '') or '') or 
                           '半年度报告' in (a.get('announcementTitle', '') or '')
                           for a in announcements)
            if has_report:
                disclosure_score = 4
            else:
                disclosure_score = 2
        else:
            disclosure_score = 2
        score += disclosure_score
        details['disclosure'] = disclosure_score
        
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
            limit_score = 5
        elif abs(change) < 7:
            limit_score = 3
        elif abs(change) < 9.5:
            limit_score = 1
        else:
            limit_score = 0
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


engine = ScoringEngineV41()


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
    
    capital = result.details.get('capital', {})
    print(f"\n  资金详情:")
    print(f"    北向资金: {capital.get('northbound_net', 'N/A')}亿")
    print(f"    换手率: {capital.get('turnover_pct', 'N/A')}%")
    print(f"    盘口压力: {capital.get('depth', 'N/A')}/4")
    
    risk = result.details.get('risk', {})
    print(f"\n  风控详情:")
    print(f"    最大回撤评分: {risk.get('max_drawdown', 'N/A')}/6")
    print(f"    信息披露: {risk.get('disclosure', 'N/A')}/4")
