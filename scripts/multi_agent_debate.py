#!/usr/bin/env python3
"""
multi_agent_debate.py - v2.2 多空七维辩论验证

v2.0 七维辩论 (恢复):
- 技术Agent: 25%
- 资金Agent: 20%
- 基本面Agent: 20%
- 消息情绪Agent: 15% (新增)
- 产业逻辑Agent: 10% (新增)
- 宏观Agent: 5%
- 行为Agent: 5%

一票否决: 风险Agent
"""

def run_debate(
    tech_signals: dict = None,
    fund_signals: dict = None,
    fundamental_signals: dict = None,
    news_signals: dict = None,
    industry_signals: dict = None,
    macro_signals: dict = None,
    behavior_signals: dict = None,
    risk_flags: dict = None,
) -> dict:
    """
    七维辩论验证
    
    7个Agent权重:
    - 技术: 25%
    - 资金: 20%
    - 基本面: 20%
    - 消息情绪: 15%
    - 产业逻辑: 10%
    - 宏观: 5%
    - 行为: 5%
    
    风险Agent一票否决
    
    返回: {
        'score': float,      # -5~+5
        'agents': dict,      # 各Agent得分
        'is_bullish': bool,  # 是否看多
        'veto': str or None, # 否决原因
    }
    """
    
    agents = {}
    
    # 1. 技术Agent (25%)
    tech_score = 0.0
    if tech_signals:
        macd = tech_signals.get('macd', 0)
        ma = tech_signals.get('ma', 0)
        rsi = tech_signals.get('rsi', 50)
        volume = tech_signals.get('volume', 1.0)
        
        if macd > 0: tech_score += 0.3
        if ma > 0: tech_score += 0.3
        if 50 <= rsi <= 75: tech_score += 0.2
        if volume >= 1.5: tech_score += 0.2
    
    agents['tech'] = min(1.0, max(-1.0, tech_score))
    
    # 2. 资金Agent (20%)
    fund_score = 0.0
    if fund_signals:
        institution = fund_signals.get('institution', 0)
        northbound = fund_signals.get('northbound', 0)
        main_force = fund_signals.get('main_force', 0)
        
        if institution > 30: fund_score += 0.4
        if northbound > 0: fund_score += 0.3
        if main_force > 0: fund_score += 0.3
    
    agents['fund'] = min(1.0, max(-1.0, fund_score))
    
    # 3. 基本面Agent (20%)
    # v2.0: PE<20/ROE>15%/营收利润高增长
    fundamental_score = 0.0
    if fundamental_signals:
        pe = fundamental_signals.get('pe', 50)
        roe = fundamental_signals.get('roe', 0)
        revenue_growth = fundamental_signals.get('revenue_growth', 0)
        profit_growth = fundamental_signals.get('profit_growth', 0)
        
        if pe < 20: fundamental_score += 0.4
        elif pe > 100: fundamental_score -= 0.3
        if roe > 15: fundamental_score += 0.3
        elif roe < 5: fundamental_score -= 0.2
        if revenue_growth > 20 and profit_growth > 20:
            fundamental_score += 0.3
        elif revenue_growth < 0 or profit_growth < 0:
            fundamental_score -= 0.2
    
    agents['fundamental'] = min(1.0, max(-1.0, fundamental_score))
    
    # 4. 消息情绪Agent (15%)
    # v2.0: 正面关键词/情绪分/监管风险
    news_score = 0.0
    if news_signals:
        sentiment = news_signals.get('sentiment', 0)
        risk = news_signals.get('risk', 0)
        keywords_positive = news_signals.get('keywords_positive', 0)
        keywords_negative = news_signals.get('keywords_negative', 0)
        
        # 情绪分
        if sentiment > 0.5: news_score += 0.4
        elif sentiment < -0.5: news_score -= 0.4
        elif sentiment > 0: news_score += 0.1
        elif sentiment < 0: news_score -= 0.1
        
        # 关键词
        if keywords_positive > 3: news_score += 0.3
        if keywords_negative > 3: news_score -= 0.3
        
        # 风险
        news_score -= risk * 0.2
    
    agents['news'] = min(1.0, max(-1.0, news_score))
    
    # 5. 产业逻辑Agent (10%) ★v2.0新增
    # v2.0: 行业周期/政策利好/供需紧张/定价权
    industry_score = 0.0
    if industry_signals:
        cycle = industry_signals.get('cycle', 'stable')  # up/down/stable
        policy = industry_signals.get('policy', 'neutral')  # good/bad/neutral
        supply_demand = industry_signals.get('supply_demand', 'balanced')  # tight/loose
        pricing_power = industry_signals.get('pricing_power', False)
        
        if cycle == 'up': industry_score += 0.4
        elif cycle == 'down': industry_score -= 0.3
        
        if policy == 'good': industry_score += 0.3
        elif policy == 'bad': industry_score -= 0.3
        
        if supply_demand == 'tight': industry_score += 0.2
        elif supply_demand == 'loose': industry_score -= 0.1
        
        if pricing_power: industry_score += 0.1
    
    agents['industry'] = min(1.0, max(-1.0, industry_score))
    
    # 6. 宏观Agent (5%)
    # v2.0: 流动性/汇率/利率周期
    macro_score = 0.0
    if macro_signals:
        liquidity = macro_signals.get('liquidity', 'neutral')  # loose/tight
        exchange_rate = macro_signals.get('exchange_rate', 0)  # 人民币升值>0
        rate_cycle = macro_signals.get('rate_cycle', 'neutral')  # cut/hike
        
        if liquidity == 'loose': macro_score += 0.4
        elif liquidity == 'tight': macro_score -= 0.3
        
        if exchange_rate > 0: macro_score += 0.3
        elif exchange_rate < 0: macro_score -= 0.2
        
        if rate_cycle == 'cut': macro_score += 0.3
        elif rate_cycle == 'hike': macro_score -= 0.2
    
    agents['macro'] = min(1.0, max(-1.0, macro_score))
    
    # 7. 行为Agent (5%)
    # v2.0: 散户恐慌(逆向指标)/融资余额增加
    behavior_score = 0.0
    if behavior_signals:
        retail_panic = behavior_signals.get('retail_panic', False)  # 散户恐慌→看多
        margin_increase = behavior_signals.get('margin_increase', False)  # 融资增加→看多
        short_ratio = behavior_signals.get('short_ratio', 0)  # 融券比例
        
        if retail_panic: behavior_score += 0.5  # 逆向指标
        if margin_increase: behavior_score += 0.3
        if short_ratio > 0.1: behavior_score -= 0.2  # 融券高→看空
    
    agents['behavior'] = min(1.0, max(-1.0, behavior_score))
    
    # 风险Agent - 一票否决
    risk_score = 0.0
    if risk_flags:
        if risk_flags.get('st_risk', False): risk_score -= 1.0
        if risk_flags.get('liquidity_risk', False): risk_score -= 0.8
        if risk_flags.get('valuation_risk', False): risk_score -= 0.5
        if risk_flags.get('regulatory_risk', False): risk_score -= 0.8
    
    agents['risk'] = max(-1.0, risk_score)
    
    # 加权汇总 (七维)
    weights = {
        'tech': 0.25,
        'fund': 0.20,
        'fundamental': 0.20,
        'news': 0.15,
        'industry': 0.10,
        'macro': 0.05,
        'behavior': 0.05,
    }
    
    weighted_score = sum(agents[a] * weights[a] for a in weights if a in agents)
    
    # 映射到 -5~+5
    debate_score = weighted_score * 5
    
    # 风险Agent一票否决
    veto = None
    if agents['risk'] < -0.8:
        debate_score = -5.0
        veto = 'risk'
    
    # 多数决加分
    bullish_count = sum(1 for a in ['tech', 'fund', 'fundamental', 'news', 'industry', 'macro', 'behavior'] 
                        if a in agents and agents[a] > 0)
    if bullish_count >= 4:
        debate_score += 0.5
    
    return {
        'score': max(-5, min(5, debate_score)),
        'agents': agents,
        'is_bullish': debate_score > 0,
        'veto': veto,
    }


if __name__ == '__main__':
    # 测试
    result = run_debate(
        tech_signals={'macd': 0.5, 'ma': 0.3, 'rsi': 65, 'volume': 1.8},
        fund_signals={'institution': 35, 'northbound': 5000, 'main_force': 10000},
        fundamental_signals={'pe': 18, 'roe': 18, 'revenue_growth': 25, 'profit_growth': 30},
        news_signals={'sentiment': 0.4, 'risk': 0.1, 'keywords_positive': 5, 'keywords_negative': 0},
        industry_signals={'cycle': 'up', 'policy': 'good', 'supply_demand': 'tight', 'pricing_power': True},
        macro_signals={'liquidity': 'loose', 'exchange_rate': 0.5, 'rate_cycle': 'cut'},
        behavior_signals={'retail_panic': True, 'margin_increase': True, 'short_ratio': 0.05},
        risk_flags={'st_risk': False, 'liquidity_risk': False},
    )
    
    print("=" * 50)
    print("v2.2 七维辩论测试")
    print("=" * 50)
    print(f"综合得分: {result['score']:+.2f}")
    print(f"看多: {result['is_bullish']}")
    print(f"否决: {result['veto']}")
    print("\n各Agent投票:")
    for agent, score in result['agents'].items():
        bar = "█" * int(abs(score) * 10) + "░" * (10 - int(abs(score) * 10))
        direction = "看多" if score > 0 else "看空" if score < 0 else "中性"
        print(f"  {agent:12s}: {score:+.2f} [{direction}] {bar}")
