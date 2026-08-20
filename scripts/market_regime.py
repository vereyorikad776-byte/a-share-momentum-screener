#!/usr/bin/env python3
"""
market_regime.py - v2.2 市场环境判断

融合升级:
- 五维择时模型 (西蒙第2集): 估值/资金/技术/情绪/基本面
- 脆弱度三维风险 (西蒙第11集): 脆弱/恶化/冲击
- 连续风险调整仓位 (非满仓/空仓二选一)
"""

from typing import Tuple, List, Optional
from enum import Enum

class MarketRegime(Enum):
    STRONG_TREND = "STRONG_TREND"
    CHOP = "CHOP"
    ICE = "ICE"
    UNKNOWN = "UNKNOWN"

class MarketRegimeSignal:
    def __init__(self, regime: MarketRegime, adx: float = 0, confidence: float = 0):
        self.regime = regime
        self.adx = adx
        self.confidence = confidence

class MarketRegimeDetector:
    def detect(self, index_df) -> Optional[MarketRegimeSignal]:
        if len(index_df) < 40:
            return None
        adx = index_df['adx'].iloc[-1] if 'adx' in index_df.columns else 20
        close = index_df['close'].iloc[-1]
        ma20 = index_df['ma20'].iloc[-1] if 'ma20' in index_df.columns else close
        
        if adx > 25:
            regime = MarketRegime.STRONG_TREND
        elif adx < 15:
            regime = MarketRegime.ICE
        else:
            regime = MarketRegime.CHOP
        return MarketRegimeSignal(regime, adx=adx, confidence=0.6)

def calc_erp(pe: float, bond_yield: float = 0.025) -> float:
    """计算ERP股权风险溢价 = 1/PE - 国债收益率"""
    if pe <= 0:
        return 0
    return 1.0 / pe - bond_yield


def five_dimension_timing(
    pe: float = 15.0,
    bond_yield: float = 0.025,
    margin_amount: float = 0,        # 融资买入额变化率
    margin_bb_break: bool = False,   # 融资布林带突破
    index_bb_break: bool = False,    # 指数布林带突破
    breadth: float = 0.5,            # 市场广度 (上涨成交额占比)
    pcr: float = 1.0,                # 期权PCR (Put/Call Ratio)
    iv: float = 0.2,                 # 隐含波动率
    futures_position: float = 0,     # 期货持仓变化
    basis: float = 0,                # 期指基差
    cpi: float = 0,                  # CPI同比
    pmi: float = 50,                 # PMI
    epu: float = 0,                  # 经济政策不确定性指数
) -> Tuple[float, List[str]]:
    """
    五维择时模型 (西蒙第2集)
    
    每个维度输出 1(看多)/0(中性)/-1(看空)
    最后五维投票决定仓位
    
    返回: (仓位比例 0~1.0, 理由列表)
    """
    
    dimensions = {}
    reasons = []
    
    # 维度1: 估值 (ERP股权风险溢价)
    erp = calc_erp(pe, bond_yield)
    if erp > 0.03:
        dimensions['valuation'] = 1
        reasons.append(f"估值: ERP={erp:.3f} 高(看多)")
    elif erp < 0.01:
        dimensions['valuation'] = -1
        reasons.append(f"估值: ERP={erp:.3f} 低(看空)")
    else:
        dimensions['valuation'] = 0
        reasons.append(f"估值: ERP={erp:.3f} 中性")
    
    # 维度2: 资金 (融资+布林带)
    if margin_amount > 0.05 or margin_bb_break:  # 融资增长5%或突破
        dimensions['funding'] = 1
        reasons.append("资金: 融资放大/布林带突破(进攻)")
    elif margin_amount < -0.05:
        dimensions['funding'] = -1
        reasons.append("资金: 融资收缩(防守)")
    else:
        dimensions['funding'] = 0
        reasons.append("资金: 中性")
    
    # 维度3: 技术 (布林带+市场广度)
    if index_bb_break and breadth > 0.6:
        dimensions['technical'] = 1
        reasons.append("技术: 指数突破+广度好")
    elif not index_bb_break and breadth < 0.4:
        dimensions['technical'] = -1
        reasons.append("技术: 指数弱势+广度差")
    else:
        dimensions['technical'] = 0
        reasons.append("技术: 中性")
    
    # 维度4: 情绪 (期权PCR/IV/期货持仓/基差)
    # PCR高=恐慌=看多(反向), IV高=恐慌=看空
    sentiment_score = 0
    if pcr > 1.2: sentiment_score += 1  # PCR高=恐慌=看多
    elif pcr < 0.8: sentiment_score -= 1  # PCR低=贪婪=看空
    
    if iv > 0.3: sentiment_score -= 1  # IV高=恐慌
    elif iv < 0.15: sentiment_score += 0.5  # IV低=平静
    
    if futures_position > 0.1: sentiment_score += 0.5
    elif futures_position < -0.1: sentiment_score -= 0.5
    
    if basis < -0.01: sentiment_score += 0.5  # 贴水=看多
    elif basis > 0.01: sentiment_score -= 0.5  # 升水=看空
    
    if sentiment_score > 0.5:
        dimensions['sentiment'] = 1
        reasons.append("情绪: 恐慌/悲观(反向看多)")
    elif sentiment_score < -0.5:
        dimensions['sentiment'] = -1
        reasons.append("情绪: 贪婪/乐观(反向看空)")
    else:
        dimensions['sentiment'] = 0
        reasons.append("情绪: 中性")
    
    # 维度5: 基本面 (CPI/PMI/EPU)
    # 西蒙: 基本面"差到不能更差"时反向使用
    bad_count = sum([
        cpi < 0,      # 通缩
        pmi < 50,     # 收缩
        epu > 200,    # 高不确定性
    ])
    
    if bad_count >= 2:
        # 基本面差到极点 → 反向看多 (高赔率底部)
        dimensions['fundamental'] = 1
        reasons.append(f"基本面: {bad_count}个指标恶化→反向看多(高赔率底部)")
    elif bad_count == 0 and cpi > 2 and pmi > 52:
        dimensions['fundamental'] = -1
        reasons.append("基本面: 过热→谨慎")
    else:
        dimensions['fundamental'] = 0
        reasons.append("基本面: 中性")
    
    # 五维投票
    votes = list(dimensions.values())
    bullish = sum(1 for v in votes if v > 0)
    bearish = sum(1 for v in votes if v < 0)
    
    # 仓位决定
    if bullish >= 4:
        position = 1.0  # 满仓
        reasons.append("五维择时: 强烈看多 → 100%仓位")
    elif bullish >= 3:
        position = 0.7  # 70%
        reasons.append("五维择时: 看多 → 70%仓位")
    elif bearish >= 4:
        position = 0.0  # 空仓
        reasons.append("五维择时: 强烈看空 → 0%仓位")
    elif bearish >= 3:
        position = 0.3  # 30%
        reasons.append("五维择时: 看空 → 30%仓位")
    else:
        position = 0.5  # 中性50%
        reasons.append("五维择时: 中性 → 50%仓位")
    
    return position, reasons


def calc_risk_score(
    index_new_high: bool = False,
    rising_ratio: float = 0.5,      # 上涨股票比例
    breadth_trend: float = 0,       # 市场广度趋势
    limit_up_count: int = 50,       # 涨停家数
    limit_up_trend: float = 0,      # 涨停家数趋势
    external_shock: float = 0,      # 外部冲击 (0~1)
) -> Tuple[float, List[str]]:
    """
    脆弱度三维风险评分 (西蒙第11集: 7·17大跌事前分析)
    
    风险演化链: 脆弱 → 恶化 → 冲击
    
    返回: (风险分数 0~1.0, 理由列表)
    """
    
    reasons = []
    risk_score = 0.0
    
    # 1. 脆弱度 (Fragility)
    # 指数创新高但内部结构分化
    if index_new_high and rising_ratio < 0.3:
        risk_score += 0.3
        reasons.append(f"脆弱: 指数新高但仅{rising_ratio*100:.0f}%股票上涨")
    
    # 2. 恶化度 (Deterioration)
    # 市场广度持续恶化
    if breadth_trend < -0.05:
        risk_score += 0.25
        reasons.append(f"恶化: 市场广度持续下降({breadth_trend:+.1%})")
    
    if limit_up_trend < -10:
        risk_score += 0.15
        reasons.append(f"恶化: 涨停家数减少({limit_up_trend:+.0f}家)")
    
    # 3. 冲击度 (Shock)
    # 外部事件
    if external_shock > 0.5:
        risk_score += 0.3
        reasons.append(f"冲击: 外部事件风险高({external_shock:.1f})")
    
    # 连续风险调整
    # 不是非满仓即空仓，而是连续调整
    risk_score = min(1.0, risk_score)
    
    if risk_score > 0.7:
        reasons.append(f"风险评分: {risk_score:.2f} → 高度危险,大幅降仓")
    elif risk_score > 0.4:
        reasons.append(f"风险评分: {risk_score:.2f} → 中度风险,适度降仓")
    else:
        reasons.append(f"风险评分: {risk_score:.2f} → 正常")
    
    return risk_score, reasons


def get_market_regime(
    pe: float = 15.0,
    bond_yield: float = 0.025,
    ma20_trend: str = 'neutral',
    index_change: float = 0,
    timing_kwargs: dict = None,
    risk_kwargs: dict = None,
) -> dict:
    """
    综合市场环境判断
    
    融合:
    - 五维择时 (西蒙第2集)
    - 三维风险 (西蒙第11集)
    - 原有MA20趋势
    
    返回: {
        'position_limit': float,  # 仓位上限 0~1.0
        'market_context': float,  # 市场环境分 -0.15~+0.15
        'is_bull_market': bool,
        'is_bear_market': bool,
        'reasons': list,
    }
    """
    
    reasons = []
    
    # 五维择时
    timing_params = timing_kwargs or {}
    position_5d, reasons_5d = five_dimension_timing(pe=pe, bond_yield=bond_yield, **timing_params)
    reasons.extend(reasons_5d)
    
    # 三维风险
    risk_params = risk_kwargs or {}
    risk_score, reasons_risk = calc_risk_score(**risk_params)
    reasons.extend(reasons_risk)
    
    # 风险调整仓位
    # 风险高时, 仓位上限降低
    adjusted_position = position_5d * (1 - risk_score * 0.5)
    
    # MA20趋势调整
    if ma20_trend == 'up':
        adjusted_position = min(1.0, adjusted_position * 1.1)
        reasons.append("MA20趋势向上: 仓位+10%")
    elif ma20_trend == 'down':
        adjusted_position = max(0.0, adjusted_position * 0.8)
        reasons.append("MA20趋势向下: 仓位-20%")
    
    # 市场环境分映射到 -0.15~+0.15
    market_context = (adjusted_position - 0.5) * 0.3
    
    return {
        'position_limit': round(adjusted_position, 2),
        'market_context': round(market_context, 3),
        'is_bull_market': adjusted_position >= 0.7,
        'is_bear_market': adjusted_position <= 0.3,
        'risk_score': round(risk_score, 2),
        'reasons': reasons,
    }


if __name__ == '__main__':
    # 测试: 牛市场景
    print("=" * 60)
    print("场景1: 牛市")
    print("=" * 60)
    result = get_market_regime(
        pe=12.0,
        bond_yield=0.025,
        ma20_trend='up',
        index_change=1.5,
        timing_kwargs={
            'margin_amount': 0.08,
            'margin_bb_break': True,
            'index_bb_break': True,
            'breadth': 0.7,
            'pcr': 0.9,
            'iv': 0.18,
            'cpi': 1.5,
            'pmi': 52,
            'epu': 100,
        },
    )
    print(f"仓位上限: {result['position_limit']*100:.0f}%")
    print(f"市场环境: {result['market_context']:+.3f}")
    print(f"牛市: {result['is_bull_market']}, 熊市: {result['is_bear_market']}")
    print(f"风险评分: {result['risk_score']}")
    for r in result['reasons']:
        print(f"  - {r}")
    
    # 测试: 熊市场景
    print("\n" + "=" * 60)
    print("场景2: 熊市 (7·17型)")
    print("=" * 60)
    result = get_market_regime(
        pe=25.0,
        ma20_trend='down',
        index_change=-2.0,
        timing_kwargs={
            'margin_amount': -0.1,
            'index_bb_break': False,
            'breadth': 0.2,
        },
        risk_kwargs={
            'index_new_high': True,
            'rising_ratio': 0.22,
            'breadth_trend': -0.08,
            'limit_up_trend': -20,
            'external_shock': 0.6,
        },
    )
    print(f"仓位上限: {result['position_limit']*100:.0f}%")
    print(f"市场环境: {result['market_context']:+.3f}")
    print(f"牛市: {result['is_bull_market']}, 熊市: {result['is_bear_market']}")
    print(f"风险评分: {result['risk_score']}")
    for r in result['reasons']:
        print(f"  - {r}")
