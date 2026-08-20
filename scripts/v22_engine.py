#!/usr/bin/env python3
"""
v22r_engine.py - A股动量选股核心评分引擎 v2.2r (Refactored)

执行纪律 (硬规则):
1. 遇到问题立即中断: 执行过程中遇到任何异常(API失败/数据为空/候选股不足等)
   → 立即中止 → 向用户报告问题详情 → 提供可选方案(重试/放宽条件/中止)
   → 绝不自行修补、猜测或跳过
2. API/数据失败处理: 按优先级尝试: akshare → iFinD → gildata
   → 任一源失败则尝试下一源 → 全部失败则抛出FetchError并终止流程
   → 不返回空数据继续执行
3. 不擅自修改策略逻辑: 严禁为绕过问题而临时修改评分阈值、权重、排除规则
   → 所有参数调整必须通过反馈学习模块或用户明确指令完成

2026-08-19 重构：
- 消除重复加权：每个指标只算一次
- 6维度独立评分 + 加权合成
- 模式检测作为独立加分项
- 恢复v2.0选股核心: 一夜持股法20分制 + 三维融合15分制
- 新增过夜胜率预测
- 新增策略类型判定(过夜/波段/两者皆可/观望)
- 恢复v2.0核心链路: 5日板块扫描 + 热点合并 + 模式检测执行
- 恢复七维辩论: 技术/资金/基本面/消息情绪/产业逻辑/宏观/行为

数据源: 盘中 iFinD 实时 + 盘后 stock_finance_data
"""

import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# 导入质量因子模块
from fscore_module import calc_fscore_from_financials, calc_quality_adjustment
from zscore_module import calc_zscore, get_zscore_v22_action


# =======================================================================
# v2.0 选股核心: 一夜持股法 (20分制) + 三维融合 (15分制)
# =======================================================================

def overnight_score(data: dict) -> Tuple[float, str, List[str]]:
    """
    一夜持股法 20分制 - T+0午后介入, T+1早盘退出
    核心原则: 以追涨为主, 回调买入非绝对
    
    返回: (score, grade, reasons)
    """
    score = 0.0
    reasons = []
    
    close = data.get('close', 0)
    high = data.get('high', close)
    low = data.get('low', close)
    open_price = data.get('open', close)
    volume = data.get('volume', 0)
    prev_close = data.get('prev_close', close)
    
    # === 技术面 (12分) ===
    
    # MACD
    macd = data.get('macd', 0)
    if macd > 0:
        score += 1.2
        reasons.append("MACD>0(+1.2)")
    
    # 均线排列
    ma5 = data.get('ma5', close)
    ma10 = data.get('ma10', close)
    ma20 = data.get('ma20', close)
    if close > ma5 > ma10 > ma20:
        score += 2.0
        reasons.append("均线多头排列(+2.0)")
    
    # RSI
    rsi6 = data.get('rsi6', 50)
    if 50 <= rsi6 <= 80:
        score += 1.2
        reasons.append(f"RSI={rsi6:.0f}强势区(+1.2)")
    
    # KDJ
    k = data.get('kdj_k', 50)
    d = data.get('kdj_d', 50)
    j = data.get('kdj_j', 50)
    if k > d and j < 100:
        score += 1.0
        reasons.append("KDJ金叉且J<100(+1.0)")
    
    # 量价
    volume_ratio = data.get('volume_ratio', 1.0)
    if volume_ratio >= 1.5 and close > open_price:
        score += 1.5
        reasons.append(f"量比{volume_ratio:.1f}且上涨(+1.5)")
    
    # 振幅
    amplitude = (high - low) / open_price * 100 if open_price > 0 else 0
    if 3 <= amplitude <= 8:
        score += 0.8
        reasons.append(f"振幅{amplitude:.1f}%(+0.8)")
    
    # 阳线实体
    body = abs(close - open_price)
    if amplitude > 0 and body / (high - low) >= 0.6:
        score += 0.8
        reasons.append("阳线实体大(+0.8)")
    
    # 连涨天数
    streak = data.get('up_streak', 0)
    if 2 <= streak <= 4:
        score += 1.5
        reasons.append(f"{streak}日连涨(+1.5)")
    
    # 20日新高
    high_20d = data.get('high_20d', close)
    if close >= high_20d:
        score += 1.0
        reasons.append("20日新高(+1.0)")
    
    # 回调惩罚
    high_recent = data.get('high_recent', close)
    if high_recent > 0:
        pullback = (high_recent - close) / high_recent * 100
        if pullback > 15:
            has_hammer = data.get('has_hammer', False)
            has_engulfing = data.get('has_engulfing', False)
            if not has_hammer and not has_engulfing:
                score -= 1.0
                reasons.append(f"回调{pullback:.0f}%无反转(-1.0)")
    
    # === 情绪面 (4分) ===
    
    # 涨幅
    change_pct = data.get('change_pct', 0)
    if 2 <= change_pct <= 7:
        score += 2.0
        reasons.append(f"涨幅{change_pct:.1f}%(+2.0)")
    
    # RSI 50~70
    if 50 <= rsi6 <= 70:
        score += 1.0
        reasons.append("RSI 50-70(+1.0)")
    
    # KDJ向上
    if k > d:
        score += 1.0
        reasons.append("KDJ向上(+1.0)")
    
    # 板块热点
    if data.get('in_hot_sector', False):
        score += 0.8
        reasons.append("板块热点(+0.8)")
    
    # 新闻
    news_sentiment = data.get('news_sentiment', 0)
    if news_sentiment > 0:
        score += 0.5
        reasons.append("新闻正面(+0.5)")
    
    # === 基本面 (4分) ===
    
    # 涨停基因
    if data.get('has_limit_up_gene', False):
        score += 1.2
        reasons.append("涨停基因(+1.2)")
    
    # 倍量阳线
    if volume_ratio >= 2.0 and close > open_price:
        score += 1.5
        reasons.append("倍量阳线(+1.5)")
    
    # 振幅>4%
    if data.get('avg_amplitude_20d', 0) > 4:
        score += 0.8
        reasons.append("20日振幅>4%(+0.8)")
    
    # 板块热点
    if data.get('sector_hot', False):
        score += 0.8
        reasons.append("板块热点(+0.8)")
    
    # 主板标的
    code = data.get('code', '')
    if code.startswith('6') or code.startswith('0'):
        score += 0.5
        reasons.append("主板标的(+0.5)")
    
    # === 宏观调整 ===
    market_sentiment = data.get('market_sentiment', 50)
    if market_sentiment < 40:
        score -= 1.0
        reasons.append("大盘情绪差(-1.0)")
    elif market_sentiment < 60:
        score -= 0.5
        reasons.append("大盘情绪一般(-0.5)")
    
    score = max(0, min(20, score))
    
    # 评级
    if score >= 14:
        grade = "黄金标的"
    elif score >= 11:
        grade = "优质"
    elif score >= 8:
        grade = "观察"
    elif score >= 5:
        grade = "谨慎"
    else:
        grade = "回避"
    
    return score, grade, reasons


def fusion_score(data: dict) -> Tuple[float, str, List[str]]:
    """
    三维融合选股 15分制 - 3~20日波段持仓
    权重: 技术面4.5 + 情绪面2.5 + 基本面3.0 + 资金面5.0
    
    返回: (score, grade, reasons)
    """
    score = 0.0
    reasons = []
    
    close = data.get('close', 0)
    open_price = data.get('open', close)
    volume = data.get('volume', 0)
    
    # === 技术面 (4.5分) ===
    
    # MACD
    macd = data.get('macd', 0)
    if macd > 0:
        score += 1.0
        reasons.append("MACD>0(+1.0)")
    
    # 均线
    ma5 = data.get('ma5', close)
    ma10 = data.get('ma10', close)
    ma20 = data.get('ma20', close)
    if close > ma5 > ma10 > ma20:
        score += 1.5
        reasons.append("均线多头排列(+1.5)")
    
    # RSI
    rsi6 = data.get('rsi6', 50)
    if 50 <= rsi6 <= 75:
        score += 0.8
        reasons.append(f"RSI={rsi6:.0f}(+0.8)")
    
    # KDJ
    k = data.get('kdj_k', 50)
    d = data.get('kdj_d', 50)
    j = data.get('kdj_j', 50)
    if k > d and j < 100:
        score += 0.6
        reasons.append("KDJ金叉(+0.6)")
    
    # 量价
    volume_ratio = data.get('volume_ratio', 1.0)
    if volume_ratio >= 1.5 and close > open_price:
        score += 1.0
        reasons.append(f"量比{volume_ratio:.1f}(+1.0)")
    
    # 振幅
    high = data.get('high', close)
    low = data.get('low', close)
    amplitude = (high - low) / open_price * 100 if open_price > 0 else 0
    if 3 <= amplitude <= 10:
        score += 0.4
        reasons.append(f"振幅{amplitude:.1f}%(+0.4)")
    
    # 20日新高
    high_20d = data.get('high_20d', close)
    if close >= high_20d:
        score += 0.5
        reasons.append("20日新高(+0.5)")
    
    # 连涨
    streak = data.get('up_streak', 0)
    if 2 <= streak <= 4:
        score += 0.6
        reasons.append(f"{streak}日连涨(+0.6)")
    
    # 回调惩罚
    high_recent = data.get('high_recent', close)
    if high_recent > 0:
        pullback = (high_recent - close) / high_recent * 100
        if pullback > 15:
            has_hammer = data.get('has_hammer', False)
            has_engulfing = data.get('has_engulfing', False)
            if not has_hammer and not has_engulfing:
                score -= 1.0
                reasons.append("深度回调无反转(-1.0)")
    
    # === 情绪面 (2.5分) ===
    
    change_pct = data.get('change_pct', 0)
    if 2 <= change_pct <= 7:
        score += 1.5
        reasons.append(f"涨幅{change_pct:.1f}%(+1.5)")
    
    # 5日累计涨幅
    change_5d = data.get('change_pct_5d', 0)
    if 5 <= change_5d <= 20:
        score += 0.6
        reasons.append(f"5日涨{change_5d:.1f}%(+0.6)")
    
    # 板块+新闻
    if data.get('in_hot_sector', False):
        score += 0.5
        reasons.append("热点板块(+0.5)")
    
    news_sentiment = data.get('news_sentiment', 0)
    if news_sentiment > 0:
        score += 0.5
        reasons.append("新闻正面(+0.5)")
    
    # === 基本面 (3.0分) ===
    
    if data.get('in_hot_sector', False):
        score += 1.0
        reasons.append("板块热点(+1.0)")
    
    # 多概念
    concepts = data.get('concepts', [])
    if len(concepts) >= 2:
        score += 0.5
        reasons.append(f"多概念({len(concepts)}个)(+0.5)")
    
    # 市值
    market_cap = data.get('market_cap', 0)
    if 50 <= market_cap <= 500:
        score += 0.5
        reasons.append(f"市值{market_cap:.0f}亿(+0.5)")
    
    # PE
    pe = data.get('pe', 0)
    if 0 < pe <= 30:
        score += 0.5
        reasons.append(f"PE={pe:.0f}(+0.5)")
    
    # 倍量阳线
    if volume_ratio >= 2.0 and close > open_price:
        score += 0.5
        reasons.append("倍量阳线(+0.5)")
    
    # 涨停基因
    if data.get('has_limit_up_gene', False):
        score += 0.5
        reasons.append("涨停基因(+0.5)")
    
    # === 资金面 (5.0分) - 权重最高 ===
    
    # 机构持仓
    inst_ratio = data.get('institution_hold_ratio', 0)
    if inst_ratio >= 30:
        score += 1.5
        reasons.append(f"机构持仓{inst_ratio:.0f}%(+1.5)")
    elif inst_ratio >= 15:
        score += 0.6 + (inst_ratio - 15) / 15 * 0.6
        reasons.append(f"机构持仓{inst_ratio:.0f}%(+{0.6 + (inst_ratio - 15) / 15 * 0.6:.1f})")
    
    # 北向
    northbound_5d = data.get('northbound_net_5d', 0)
    if northbound_5d >= 10000:
        score += 1.0
        reasons.append(f"北向5日净流入{northbound_5d/10000:.1f}亿(+1.0)")
    elif northbound_5d <= -5000:
        score -= 0.5
        reasons.append(f"北向5日净流出{-northbound_5d/10000:.1f}亿(-0.5)")
    
    # 主力
    main_force_5d = data.get('main_force_net_5d', 0)
    if main_force_5d >= 50000:
        score += 1.5
        reasons.append(f"主力5日净流入{main_force_5d/10000:.1f}亿(+1.5)")
    elif main_force_5d <= -10000:
        score -= 0.8
        reasons.append(f"主力5日净流出{-main_force_5d/10000:.1f}亿(-0.8)")
    
    # 股东户数
    holder_change = data.get('holder_change_pct', 0)
    if holder_change <= -10:
        score += 1.0
        reasons.append(f"股东户数减少{abs(holder_change):.0f}%(+1.0)")
    elif holder_change >= 20:
        score -= 0.3
        reasons.append(f"股东户数增加{holder_change:.0f}%(-0.3)")
    
    score = max(0, min(15, score))
    
    # 评级
    if score >= 12:
        grade = "优秀"
    elif score >= 9:
        grade = "良好"
    elif score >= 6:
        grade = "一般"
    elif score >= 3:
        grade = "较差"
    else:
        grade = "回避"
    
    return score, grade, reasons

def step1_mandatory_exclusion(data: dict) -> Tuple[bool, List[str]]:
    """强制排除 - 一票否决"""
    reasons = []
    
    name = data.get('name', '')
    if 'ST' in name or '*ST' in name or '退' in name:
        reasons.append("ST/*ST/退市风险")
    
    close = data.get('close', 0)
    prev_close = data.get('prev_close', close)
    if close <= prev_close * 0.901:
        reasons.append("当日跌停")
    
    open_price = data.get('open', close)
    if open_price > prev_close * 1.02:
        # v2.2r 修复: 只排除高开低走，高开高走保留 (2026-08-20教训)
        if close < open_price:
            reasons.append(f"高开低走: 高开{(open_price/prev_close-1)*100:.1f}% 但收盘低于开盘")
        # 高开高走不排除
    
    change_pct_2d = data.get('change_pct_2d', 0)
    if change_pct_2d < -15:
        reasons.append(f"连续2日跌幅{change_pct_2d:.1f}% > 15%")
    
    amount = data.get('amount', 0)
    if amount < 5000:
        reasons.append(f"成交额{amount:.0f}万 < 5000万")
    
    if data.get('has_major_bad_news', False):
        reasons.append("重大利空")
    
    northbound_5d = data.get('northbound_net_5d', 0)
    if northbound_5d < -10000:
        reasons.append(f"北向连续5日净流出{-northbound_5d:.0f}万")
    
    return len(reasons) > 0, reasons


def step1_5_news_exclusion(data: dict) -> Tuple[bool, List[str]]:
    """
    新闻公告异动排除 - v2.2r 强化版
    
    硬排除规则（基于2026-08-20教训）:
    1. 新闻黑名单
    2. 公告风险等级>=4
    3. 公司澄清"概念零收入"或"无重大影响"
    4. 概念营收占比<10%却爆炒
    5. PE>100倍且非盈利高增长
    6. 5日涨幅>30%（游资拉抬）
    """
    reasons = []
    
    if data.get('is_news_blacklisted', False):
        reasons.append("新闻黑名单")
    
    notice_risk = data.get('notice_risk', 0)
    if isinstance(notice_risk, str):
        risk_map = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4, 'fatal': 5}
        notice_risk = risk_map.get(notice_risk, 0)
    if notice_risk >= 4:
        reasons.append(f"公告风险等级{notice_risk} (严重/致命)")
    
    # 硬排除: 公司澄清概念无收入
    if data.get('concept_clarified', False):
        reasons.append("公司澄清:概念无实际收入")
    
    # 硬排除: 概念营收占比<10%
    concept_revenue_pct = data.get('concept_revenue_pct', 0)
    if concept_revenue_pct > 0 and concept_revenue_pct < 10:
        reasons.append(f"概念营收仅占{concept_revenue_pct:.1f}%")
    
    # 硬排除: PE>100倍（除非利润增速>50%）
    pe_ttm = data.get('pe_ttm', 0)
    profit_growth = data.get('profit_growth', 0)
    if pe_ttm > 100 and profit_growth < 50:
        reasons.append(f"PE{pe_ttm:.0f}倍估值过高")
    
    # 硬排除: 5日涨幅>30%（游资拉抬）
    change_5d = data.get('change_5d', 0)
    if change_5d > 30:
        reasons.append(f"5日涨{change_5d:.1f}%游资拉抬")
    
    return len(reasons) > 0, reasons


# =======================================================================
# Step 2: 模式检测 (0~2.0分) - 独立形态维度
# =======================================================================

def step2_pattern_detection(data: dict) -> Tuple[float, str]:
    """
    六大模式检测 - 只算形态，不算技术指标
    """
    close = data.get('close', 0)
    high_20d = data.get('high_20d', close)
    volume = data.get('volume', 0)
    volume_20d_avg = data.get('volume_20d_avg', volume)
    
    patterns = []
    
    # 模式1: 突破
    if close > high_20d and volume > volume_20d_avg * 1.5:
        breakout_pct = (close - high_20d) / high_20d * 100 if high_20d > 0 else 0
        if breakout_pct > 2:
            patterns.append((1.0, "突破(大幅越过)"))
        elif breakout_pct > 1:
            patterns.append((0.5, "突破(中等越过)"))
        else:
            patterns.append((0.2, "突破(勉强越过)"))
    
    # 模式2: 回调再起
    high_recent = data.get('high_recent', close)
    volume_rally_avg = data.get('volume_rally_avg', volume)
    has_hammer = data.get('has_hammer', False)
    has_engulfing = data.get('has_engulfing', False)
    pullback_pct = (high_recent - close) / high_recent * 100 if high_recent > 0 else 0
    
    if 8 <= pullback_pct <= 15 and volume < volume_rally_avg * 0.5 and (has_hammer or has_engulfing):
        rebound_count = data.get('rebound_count', 1)
        if rebound_count == 1:
            patterns.append((0.2, f"回调再起(第1次,71.9%失败)"))
        elif rebound_count == 2:
            patterns.append((0.5, f"回调再起(第2次,59.1%失败)"))
        elif rebound_count == 3:
            patterns.append((0.8, f"回调再起(第3次,52.8%失败)"))
        else:
            patterns.append((1.0, f"回调再起(第{rebound_count}次,43.3%失败)"))
    
    # 模式3: 旗形整理
    high_5d_ago = data.get('high_5d_ago', close)
    days_in_channel = data.get('days_in_channel', 0)
    volume_trend_down = data.get('volume_trend_down', False)
    breakout_today = data.get('breakout_today', False)
    
    if high_5d_ago > 0 and (close - high_5d_ago) / high_5d_ago * 100 >= 30:
        if 5 <= days_in_channel <= 7 and volume_trend_down and breakout_today:
            patterns.append((1.0, "旗形整理"))
    
    # 模式4: 杯柄形态
    low_20d = data.get('low_20d', close)
    high_cup = data.get('high_cup', close)
    handle_low = data.get('handle_low', close)
    volume_handle = data.get('volume_handle', volume)
    volume_cup_avg = data.get('volume_cup_avg', volume)
    
    if low_20d > 0 and (high_cup - low_20d) / low_20d * 100 >= 20:
        handle_pct = (high_cup - handle_low) / high_cup * 100 if high_cup > 0 else 0
        if 8 <= handle_pct <= 12 and volume_handle < volume_cup_avg * 0.8 and close > high_cup:
            patterns.append((1.0, "杯柄形态"))
    
    # 模式5: 龙头首阴
    prev_close = data.get('prev_close', close)
    streak_days = data.get('streak_days', 0)
    if streak_days >= 3 and close < prev_close and volume < volume_rally_avg * 1.5:
        patterns.append((0.8, "龙头首阴"))
    
    # 模式6: 筹码反转
    cost_distribution = data.get('cost_distribution', [])
    auction_strength = data.get('auction_strength', 0)
    if cost_distribution and len(cost_distribution) > 0:
        deep_trap_score = sum((1 - close/cost)**2 for cost in cost_distribution 
                              if cost > 0 and close < cost * 0.7)
        if deep_trap_score > 10 and auction_strength > 0.3:
            patterns.append((0.6, "筹码反转"))
    
    if not patterns:
        return 0.0, "无模式"
    
    best = max(patterns, key=lambda x: x[0])
    return best[0], best[1]


# =======================================================================
# Step 3: 技术面评分 (0~25分) - 唯一技术打分
# =======================================================================

def step3_technical_score(data: dict) -> Tuple[float, List[str]]:
    """
    技术面评分 - 所有技术指标只在这里算一次
    输入: K线数据 + 技术指标
    输出: (分数, 理由列表)
    """
    score = 0.0
    reasons = []
    
    close = data.get('close', 0)
    high = data.get('high', close)
    low = data.get('low', close)
    open_price = data.get('open', close)
    volume = data.get('volume', 0)
    
    # 动量指标
    macd = data.get('macd', 0)
    if macd > 0:
        score += 3.0
        reasons.append("MACD>0")
    
    rsi6 = data.get('rsi6', 50)
    if 50 <= rsi6 <= 80:
        score += 3.0
        reasons.append(f"RSI={rsi6:.0f}(强势区)")
    elif rsi6 > 80:
        score -= 1.0
        reasons.append(f"RSI={rsi6:.0f}(超买)")
    
    # KDJ
    k = data.get('kdj_k', 50)
    d = data.get('kdj_d', 50)
    j = data.get('kdj_j', 50)
    if k > d:
        score += 2.0
        reasons.append("KDJ金叉")
    if j < 100:
        score += 1.0
        reasons.append("J<100(未超买)")
    
    # 均线系统
    ma5 = data.get('ma5', close)
    ma10 = data.get('ma10', close)
    ma20 = data.get('ma20', close)
    
    if close > ma5:
        score += 2.0
        reasons.append("收盘价>MA5")
    if ma5 > ma10:
        score += 2.0
        reasons.append("MA5>MA10")
    if ma10 > ma20:
        score += 2.0
        reasons.append("MA10>MA20")
    if close > ma20:
        score += 2.0
        reasons.append("收盘价>MA20")
    
    # 20日新高
    high_20d = data.get('high_20d', close)
    if close >= high_20d:
        score += 3.0
        reasons.append("20日新高")
    else:
        # === 首启战法指标: 距高点距离 ===
        # 距20日高点越近，蓄势突破概率越高
        distance_to_high = (high_20d - close) / high_20d * 100 if high_20d > 0 else 100
        if distance_to_high < 3:
            score += 1.0
            reasons.append(f"距20日高点仅{distance_to_high:.1f}%(蓄势)")
        elif distance_to_high < 5:
            score += 0.5
            reasons.append(f"距20日高点{distance_to_high:.1f}%(接近)")
    
    # 量价
    volume_ratio = data.get('volume_ratio', 1.0)
    if volume_ratio >= 2.0:
        score += 3.0
        reasons.append(f"量比{volume_ratio:.1f}(显著放量)")
    elif volume_ratio >= 1.5:
        score += 2.0
        reasons.append(f"量比{volume_ratio:.1f}(温和放量)")
    
    # 振幅
    amplitude = (high - low) / open_price * 100 if open_price > 0 else 0
    if 3 <= amplitude <= 8:
        score += 2.0
        reasons.append(f"振幅{amplitude:.1f}%(健康)")
    elif amplitude > 12:
        score -= 1.0
        reasons.append(f"振幅{amplitude:.1f}%(过大)")
    
    # 阳线实体
    body_ratio = abs(close - open_price) / (high - low) if high > low else 0
    if body_ratio >= 0.6:
        score += 2.0
        reasons.append("阳线实体>60%")
    
    # 连涨天数
    streak = data.get('streak_days', 0)
    if 2 <= streak <= 4:
        score += 3.0
        reasons.append(f"连涨{streak}天")
    elif streak > 4:
        score -= 1.0
        reasons.append(f"连涨{streak}天(过热)")
    
    # 回调惩罚
    pullback = data.get('pullback_pct', 0)
    if pullback > 15:
        score -= 2.0
        reasons.append(f"回调{pullback:.1f}%(过深)")
    
    # === v2.2r 新增: 冲高回落检测 (2026-08-20教训) ===
    # 早盘急拉后回落 = 拉高出货信号
    if high > close and high > open_price:
        pullback_from_high = (high - close) / high * 100
        if pullback_from_high >= 5:
            # 冲高回落超过5%
            score -= 3.0
            reasons.append(f"冲高回落{pullback_from_high:.1f}%(出货)")
        elif pullback_from_high >= 3:
            score -= 1.5
            reasons.append(f"冲高回落{pullback_from_high:.1f}%")
        
        # 收盘价位置检测
        day_range = high - low
        if day_range > 0:
            close_position = (close - low) / day_range
            if close_position < 0.3:
                # 收在日内低位 = 出货
                score -= 2.0
                reasons.append("收在日内低位(出货)")
    
    return max(0, min(25, score)), reasons


# =======================================================================
# Step 4: 情绪面评分 (0~15分) - 唯一情绪打分
# =======================================================================

def step4_sentiment_score(data: dict) -> Tuple[float, List[str]]:
    """
    情绪面评分 - 涨幅/连涨/热点/板块，不涉及技术指标
    """
    score = 0.0
    reasons = []
    
    # 涨幅
    change_pct = data.get('change_pct', 0)
    if 2 <= change_pct <= 5:
        score += 4.0
        reasons.append(f"涨幅{change_pct:.1f}%(温和)")
    elif 5 < change_pct <= 7:
        score += 3.0
        reasons.append(f"涨幅{change_pct:.1f}%(强势)")
    elif 7 < change_pct <= 10:
        score += 2.0
        reasons.append(f"涨幅{change_pct:.1f}%(过热)")
    elif change_pct > 10:
        score += 1.0
        reasons.append(f"涨幅{change_pct:.1f}%(涨停)")
    elif change_pct < -3:
        score -= 2.0
        reasons.append(f"跌幅{change_pct:.1f}%(走弱)")
    
    # 热点板块
    is_hot = data.get('is_hot_sector', False)
    if is_hot:
        score += 3.0
        reasons.append("热点板块")
    
    # 板块涨幅
    sector_change = data.get('sector_change', 0)
    if sector_change > 2:
        score += 3.0
        reasons.append(f"板块+{sector_change:.1f}%(强势)")
    elif sector_change > 0:
        score += 1.5
        reasons.append(f"板块+{sector_change:.1f}%")
    elif sector_change < -2:
        score -= 1.0
        reasons.append(f"板块{sector_change:.1f}%(弱势)")
    
    # === 首启战法指标: 板块内强度排名 ===
    # 个股涨幅 vs 板块涨幅 = 相对强度
    if sector_change != 0:
        relative_strength = change_pct - sector_change
        if relative_strength > sector_change * 0.2:  # 跑赢板块20%以上
            score += 2.0
            reasons.append(f"板块内领跑(+{relative_strength:.1f}%)")
        elif relative_strength > 0:
            score += 1.0
            reasons.append(f"跑赢板块(+{relative_strength:.1f}%)")
        elif relative_strength < -2:
            score -= 1.0
            reasons.append(f"跑输板块({relative_strength:.1f}%)")
    
    # 多概念
    has_multi = data.get('has_multi_concepts', False)
    if has_multi:
        score += 2.0
        reasons.append("多概念叠加")
    
    # 涨停基因
    streak = data.get('streak_days', 0)
    if streak >= 2:
        score += 2.0
        reasons.append("连涨惯性")
    
    return max(0, min(15, score)), reasons


# =======================================================================
# Step 5: 资金面评分 (0~15分) - 唯一资金打分
# =======================================================================

def step5_fund_score(data: dict) -> Tuple[float, List[str]]:
    """
    资金面评分 - 机构/北向/主力/散户反向，不涉及技术指标
    """
    score = 0.0
    reasons = []
    
    # 机构持仓
    inst = data.get('institution_hold_pct', 0)
    if inst >= 30:
        score += 4.0
        reasons.append(f"机构持仓{inst:.0f}%(高)")
    elif inst >= 15:
        score += 2.0
        reasons.append(f"机构持仓{inst:.0f}%(中)")
    
    # 北向资金
    north = data.get('northbound_net_5d', 0)
    if north >= 10000:
        score += 3.0
        reasons.append(f"北向5日净流入{north/10000:.0f}亿")
    elif north >= 5000:
        score += 1.5
        reasons.append(f"北向5日净流入{north/10000:.1f}亿")
    elif north <= -5000:
        score -= 2.0
        reasons.append(f"北向5日净流出{-north/10000:.1f}亿")
    
    # 主力资金
    main = data.get('main_force_net_5d', 0)
    if main >= 50000:
        score += 4.0
        reasons.append(f"主力5日净流入{main/10000:.0f}亿")
    elif main >= 10000:
        score += 2.0
        reasons.append(f"主力5日净流入{main/10000:.1f}亿")
    elif main <= -10000:
        score -= 2.0
        reasons.append(f"主力5日净流出{-main/10000:.1f}亿")
    
    # 股东人数变化
    shareholder = data.get('shareholder_change_pct', 0)
    if shareholder <= -10:
        score += 3.0
        reasons.append(f"股东数减少{abs(shareholder):.0f}%(筹码集中)")
    elif shareholder >= 20:
        score -= 1.0
        reasons.append(f"股东数增加{shareholder:.0f}%(分散)")
    
    # BetaGap (板块内欠涨)
    beta = data.get('beta', 1.0)
    sector_return = data.get('sector_return', 0)
    stock_return = data.get('change_pct', 0)
    betagap = beta * sector_return - stock_return
    if betagap > 0:
        bonus = min(betagap * 0.5, 2.0)
        score += bonus
        reasons.append(f"BetaGap={betagap:.1f}(欠涨+{bonus:.1f})")
    
    # 散户资金流反向
    retail_flow = data.get('retail_etf_flow', 0)
    index_change = data.get('index_change', 0)
    if retail_flow > 0 and index_change < 0:
        score -= 2.0
        reasons.append("散户接盘信号(ETF流入+指数跌)")
    elif retail_flow < 0 and index_change > 0:
        score += 1.0
        reasons.append("机构吸筹信号(ETF流出+指数涨)")
    
    return max(0, min(15, score)), reasons


# =======================================================================
# Step 6: 基本面评分 (0~15分) - 唯一财务打分
# =======================================================================

def step6_fundamental_score(data: dict) -> Tuple[float, List[str], Dict]:
    """
    基本面评分 - F-Score + Z-Score + 估值，唯一财务打分
    返回: (分数, 理由, 调整信息)
    """
    score = 0.0
    reasons = []
    adjustment = {'risk_flag': 'ok', 'exclude': False}
    
    # F-Score
    fscore = calc_fscore_from_financials(data)
    f_score = fscore['f_score']
    
    # v2.2r 修复: 财务数据缺失时不exclude，不扣分不加分 (2026-08-20教训)
    has_financials = any(data.get(k) is not None for k in ['roe', 'gross_margin', 'net_margin', 'debt_ratio', 'current_ratio'])
    
    if not has_financials:
        # 无财务数据，不评分，不exclude
        reasons.append("财务数据缺失(不评分)")
        adjustment['f_score'] = None
    elif f_score >= 4:
        score += 5.0
        reasons.append(f"F-Score={f_score}/5(优秀)")
    elif f_score == 3:
        score += 3.0
        reasons.append(f"F-Score={f_score}/5(良好)")
    elif f_score == 2:
        score += 1.0
        reasons.append(f"F-Score={f_score}/5(一般)")
    elif f_score == 1:
        score += 0.0
        reasons.append(f"F-Score={f_score}/5(较差)")
        adjustment['risk_flag'] = 'warning'
    else:
        score -= 2.0
        reasons.append(f"F-Score={f_score}/5(极差)")
        adjustment['risk_flag'] = 'exclude'
        adjustment['exclude'] = True
    
    if fscore['warnings']:
        for w in fscore['warnings'][:2]:
            reasons.append(f"⚠ {w}")
    
    # Z-Score
    bs = data.get('balance_sheet')
    inc = data.get('income_statement')
    z_info = {'z_score': None, 'zone': None}
    
    if bs is not None and inc is not None:
        zscore = calc_zscore(bs, inc)
        z = zscore.get('z_score')
        z_info['z_score'] = z
        z_info['zone'] = zscore.get('zone')
        
        if z is not None:
            if z >= 1.5:
                score += 3.0
                reasons.append(f"Z-Score={z:.2f}(安全)")
            elif z >= 0.5:
                score += 1.0
                reasons.append(f"Z-Score={z:.2f}(灰色)")
            elif z >= 0:
                score += 0.0
                reasons.append(f"Z-Score={z:.2f}(危险)")
                adjustment['risk_flag'] = 'warning'
            else:
                score -= 3.0
                reasons.append(f"Z-Score={z:.2f}(极高风险)")
                adjustment['risk_flag'] = 'exclude'
                adjustment['exclude'] = True
    
    # 估值
    pe = data.get('pe', 0)
    if 0 < pe <= 30:
        score += 2.0
        reasons.append(f"PE={pe:.0f}(合理)")
    elif pe > 100:
        score -= 1.0
        reasons.append(f"PE={pe:.0f}(过高)")
    
    market_cap = data.get('market_cap', 0)
    if 50 <= market_cap <= 500:
        score += 2.0
        reasons.append(f"市值{market_cap:.0f}亿(适中)")
    
    adjustment['z_info'] = z_info
    adjustment['f_score'] = f_score
    adjustment['quality_tag'] = fscore['quality_tag']
    
    return max(0, min(15, score)), reasons, adjustment


# =======================================================================
# Step 7: 市场环境评分 (-5~+5分) - 唯一宏观打分
# =======================================================================

def step7_market_score(data: dict) -> Tuple[float, List[str], float]:
    """
    市场环境评分 - 五灯诊断 + 五维择时合并
    返回: (分数, 理由, 乘数)
    """
    score = 0.0
    reasons = []
    lights = 0
    
    # ===== 五灯诊断 =====
    # 大盘
    index_change = data.get('index_change', 0)
    if index_change >= 0:
        lights += 1
        reasons.append("大盘绿灯")
    
    # 板块
    sector_change = data.get('sector_change', 0)
    if sector_change >= 0:
        lights += 1
        reasons.append("板块绿灯")
    
    # 趋势
    ma5 = data.get('ma5', data.get('close', 0))
    ma10 = data.get('ma10', data.get('close', 0))
    if ma5 > ma10:
        lights += 1
        reasons.append("趋势绿灯")
    
    # 价格
    close = data.get('close', 0)
    ma20 = data.get('ma20', close)
    bias = (close - ma20) / ma20 * 100 if ma20 > 0 else 0
    if bias < 18:
        lights += 1
        reasons.append("价格绿灯")
    
    # 仓位
    total_position = data.get('total_position_pct', 0)
    if total_position < 0.8:
        lights += 1
        reasons.append("仓位绿灯")
    
    # 五灯 → 基础分
    light_score = {5: 2.0, 4: 1.0, 3: 0.0, 2: -1.0, 1: -2.0, 0: -3.0}.get(lights, 0)
    score += light_score
    
    # 五灯 → 乘数
    multiplier = {5: 1.2, 4: 1.1, 3: 1.0, 2: 0.9, 1: 0.85, 0: 0.8}.get(lights, 1.0)
    
    # ===== 五维择时 =====
    # 估值
    erp = data.get('erp', 0)
    if erp > 0.03:
        score += 1.0
        reasons.append("ERP高(看多)")
    elif erp < 0.01:
        score -= 1.0
        reasons.append("ERP低(看空)")
    
    # 资金
    margin = data.get('margin_status', 0)
    if margin > 0:
        score += 1.0
        reasons.append("融资放大")
    elif margin < 0:
        score -= 1.0
        reasons.append("融资收缩")
    
    # 技术/广度
    breadth = data.get('market_breadth', 0.5)
    if breadth > 0.6:
        score += 1.0
        reasons.append("市场广度好")
    elif breadth < 0.4:
        score -= 1.0
        reasons.append("市场广度差")
    
    # 情绪
    sentiment = data.get('sentiment_score', 0)
    if sentiment > 0.3:
        score += 1.0
        reasons.append("情绪乐观")
    elif sentiment < -0.3:
        score -= 1.0
        reasons.append("情绪悲观")
    
    # 基本面
    fundamental = data.get('fundamental_score', 0)
    if fundamental > 0:
        score += 1.0
        reasons.append("基本面改善")
    elif fundamental < 0:
        score -= 1.0
        reasons.append("基本面恶化")
    
    # MA20趋势
    ma20_trend = data.get('ma20_trend', 'neutral')
    if ma20_trend == 'up':
        score += 0.5
        reasons.append("MA20向上")
    elif ma20_trend == 'down':
        score -= 0.5
        reasons.append("MA20向下")
    
    return max(-5, min(5, score)), reasons, multiplier


# =======================================================================
# Step 8: 消息面评分 (-5~+5分) - 唯一消息打分
# =======================================================================

def step8_news_score(data: dict) -> Tuple[float, List[str]]:
    """消息面评分 - 新闻/公告/业绩/合同"""
    score = 0.0
    reasons = []
    
    news_sentiment = data.get('news_sentiment', 0)
    if news_sentiment > 0.3:
        score += 2.0
        reasons.append("新闻情绪正面")
    elif news_sentiment < -0.3:
        score -= 2.0
        reasons.append("新闻情绪负面")
    
    notice_risk = data.get('notice_risk', 0)
    if isinstance(notice_risk, str):
        risk_map = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4, 'fatal': 5}
        notice_risk = risk_map.get(notice_risk, 1)
    
    if notice_risk <= 2:
        score += 1.0
        reasons.append("公告风险低")
    elif notice_risk >= 4:
        score -= 2.0
        reasons.append("公告风险高")
    
    earnings = data.get('earnings_impact', 0)
    if earnings > 0:
        score += 1.5
        reasons.append("业绩利好")
    elif earnings < 0:
        score -= 1.5
        reasons.append("业绩利空")
    
    if data.get('has_contract', False):
        contract = data.get('contract_impact', 0)
        score += min(contract, 2.0)
        reasons.append(f"合同利好(+{contract:.1f})")
    
    hot_relation = data.get('hot_relation', 0)
    if hot_relation > 0:
        score += min(hot_relation * 1.5, 2.0)
        reasons.append(f"热点关联(+{hot_relation:.1f})")
    
    return max(-5, min(5, score)), reasons


# =======================================================================
# Step 9: 交叉验证 - 不做重复打分，只检查一致性
# =======================================================================

def step9_cross_validation(tech: float, sentiment: float, fund: float,
                           fundamental: float, market: float) -> Tuple[float, List[str], bool]:
    """
    交叉验证 - 检查各维度是否同向
    返回: (一致性加分, 理由, 是否否决)
    """
    reasons = []
    
    # 检查技术 vs 情绪是否同向
    tech_signal = 1 if tech >= 12 else (-1 if tech <= 5 else 0)
    sent_signal = 1 if sentiment >= 8 else (-1 if sentiment <= 3 else 0)
    
    if tech_signal == sent_signal and tech_signal != 0:
        reasons.append("技术与情绪同向")
    elif tech_signal != 0 and sent_signal != 0:
        reasons.append("⚠ 技术与情绪背离")
    
    # 检查资金 vs 基本面
    fund_signal = 1 if fund >= 8 else (-1 if fund <= 3 else 0)
    funda_signal = 1 if fundamental >= 8 else (-1 if fundamental <= 3 else 0)
    
    if fund_signal == funda_signal and fund_signal != 0:
        reasons.append("资金与基本面同向")
    
    # 多数决加分
    signals = [tech_signal, sent_signal, fund_signal, funda_signal]
    bullish = sum(1 for s in signals if s == 1)
    bearish = sum(1 for s in signals if s == -1)
    
    if bullish >= 3:
        return 0.03, reasons + ["多维度共振(看多)"], False
    elif bearish >= 3:
        return -0.05, reasons + ["多维度背离(看空)"], False
    
    return 0.0, reasons, False


# =======================================================================
# Step 10: 分级 (v2.0 Tier S/A/B/X)
# =======================================================================

def step10_tier_classification(overnight: float, fusion: float, 
                                debate: float, pattern: float,
                                is_top3_sector: bool = False) -> str:
    """
    v2.0 三级分类 - Tier S/A/B/X
    
    准入条件:
    Tier S (超级): 匹配≥2个五大模式 AND 隔夜≥12 AND 融合≥10 AND 位于合并热点前3板块
    Tier A (活跃): 匹配1个五大模式 AND 隔夜≥8 AND 融合≥7
    Tier B (备用): 未匹配模式但隔夜≥5 或 融合≥5，未被强制排除
    Tier X (排除): 触发任意强制排除规则
    
    参数:
        is_top3_sector: 是否位于合并热点前3板块
    """
    # Tier S: 超级 - 最高标准
    if pattern >= 2.0 and overnight >= 12 and fusion >= 10 and is_top3_sector:
        return 'S'
    
    # Tier A: 活跃 - 标准模式匹配
    elif pattern >= 1.0 and overnight >= 8 and fusion >= 7:
        return 'A'
    
    # Tier B: 备用 - 未匹配模式但基础分达标
    elif overnight >= 5 or fusion >= 5:
        return 'B'
    
    # Tier X: 排除
    else:
        return 'X'


def check_classification_results(results: List[dict], min_count: int = 5) -> None:
    """
    检查有效候选股数量
    若S+A+B合计 < min_count，抛出ClassificationError
    """
    valid_count = sum(1 for r in results if r.get('tier') in ['S', 'A', 'B'])
    if valid_count < min_count:
        raise ClassificationError(
            f"有效候选股仅{valid_count}只(<{min_count})，"
            f"建议放宽条件或中止扫描"
        )


# =======================================================================
# Step 11: 最终合成 (v2.0公式)
# =======================================================================

def step11_final_synthesis(overnight: float, fusion: float, debate: float,
                           step_multiplier: float, data: dict) -> float:
    """
    v2.0 最终合成评分公式:
    base_score = (overnight/20 × 0.35) + (fusion/15 × 0.35) + (debate/5 × 0.20) + 0.10
    final_score = base_score × step_multiplier
    
    参数:
        overnight: 0~20, 一夜持股法得分
        fusion: 0~15, 三维融合得分  
        debate: -5~+5, 多空七维辩论得分
        step_multiplier: 0.8~1.2, 五步诊断乘数
    """
    # 归一化加权
    base_score = (
        (overnight / 20.0) * 0.35 +    # 隔夜 35%
        (fusion / 15.0) * 0.35 +       # 融合 35%
        ((debate + 5) / 10.0) * 0.20 + # 辩论 20% (映射-5~+5到0~1)
        0.10                            # 固定基础 10%
    )
    
    # 五步诊断乘数
    final = base_score * step_multiplier
    
    # 周一效应
    today = data.get('date', '')
    if isinstance(today, str) and len(today) >= 8:
        try:
            dt = datetime.strptime(today, '%Y%m%d')
            if dt.weekday() == 0:  # 周一
                friday_change = data.get('friday_index_change', 0)
                if friday_change < -1.5:
                    final += 0.03
        except:
            pass
    
    return max(0, min(1.5, final))


# =======================================================================
# 过夜胜率预测 (新增)
# =======================================================================

def calc_overnight_probability(data: dict) -> dict:
    """
    预测次日(T+1)上涨概率 - 基于多因子贝叶斯模型
    
    输出:
        probability: 0~100% 次日上涨概率
        rating: 高/中/低/回避
        expected_return: 预期次日收益率(%)
        confidence: 置信度(高/中/低)
        factors: 影响因子列表
    """
    score = 0.0
    factors = []
    
    close = data.get('close', 0)
    open_price = data.get('open', close)
    prev_close = data.get('prev_close', close)
    volume = data.get('volume', 0)
    volume_20d_avg = data.get('volume_20d_avg', volume)
    
    # === 技术面因子 (权重35%) ===
    tech_score = 0.0
    
    # MACD
    macd = data.get('macd', 0)
    if macd > 0:
        tech_score += 8.0
        factors.append("MACD红柱(+8%)")
    elif macd < 0:
        tech_score -= 5.0
        factors.append("MACD绿柱(-5%)")
    
    # 均线排列
    ma5 = data.get('ma5', close)
    ma10 = data.get('ma10', close)
    ma20 = data.get('ma20', close)
    if close > ma5 > ma10 > ma20:
        tech_score += 12.0
        factors.append("均线多头排列(+12%)")
    elif close > ma5 > ma10:
        tech_score += 6.0
        factors.append("短期多头排列(+6%)")
    elif close < ma5:
        tech_score -= 5.0
        factors.append("跌破MA5(-5%)")
    
    # RSI
    rsi6 = data.get('rsi6', 50)
    if 50 <= rsi6 <= 75:
        tech_score += 5.0
        factors.append(f"RSI={rsi6:.0f}强势区(+5%)")
    elif rsi6 > 80:
        tech_score -= 3.0
        factors.append(f"RSI={rsi6:.0f}超买(-3%)")
    elif rsi6 < 30:
        tech_score -= 5.0
        factors.append(f"RSI={rsi6:.0f}超卖(-5%)")
    
    # KDJ
    k = data.get('kdj_k', 50)
    d = data.get('kdj_d', 50)
    if k > d:
        tech_score += 5.0
        factors.append("KDJ金叉(+5%)")
    else:
        tech_score -= 3.0
        factors.append("KDJ死叉(-3%)")
    
    # 20日新高
    high_20d = data.get('high_20d', close)
    if close >= high_20d:
        tech_score += 8.0
        factors.append("20日新高(+8%)")
    
    score += tech_score * 0.35
    
    # === 量价因子 (权重25%) ===
    volume_score = 0.0
    
    # 量比
    volume_ratio = data.get('volume_ratio', 1.0)
    if volume_ratio >= 2.0:
        volume_score += 10.0
        factors.append(f"量比{volume_ratio:.1f}倍量(+10%)")
    elif volume_ratio >= 1.5:
        volume_score += 6.0
        factors.append(f"量比{volume_ratio:.1f}放量(+6%)")
    elif volume_ratio < 0.8:
        volume_score -= 5.0
        factors.append(f"量比{volume_ratio:.1f}缩量(-5%)")
    
    # 阳线实体
    if close > open_price:
        body_pct = (close - open_price) / open_price * 100 if open_price > 0 else 0
        if body_pct > 3:
            volume_score += 5.0
            factors.append(f"大阳线+{body_pct:.1f}%(+5%)")
        else:
            volume_score += 2.0
            factors.append("阳线(+2%)")
    else:
        volume_score -= 5.0
        factors.append("阴线(-5%)")
    
    # 成交额
    amount = data.get('amount', 0)
    if amount >= 10000:
        volume_score += 3.0
        factors.append("成交额>1亿(+3%)")
    elif amount < 3000:
        volume_score -= 3.0
        factors.append("成交额<3000万(-3%)")
    
    score += volume_score * 0.25
    
    # === 情绪因子 (权重20%) ===
    sentiment_score = 0.0
    
    # 当日涨幅
    change_pct = data.get('change_pct', 0)
    if 2 <= change_pct <= 5:
        sentiment_score += 10.0
        factors.append(f"涨幅{change_pct:.1f}%(温和上涨+10%)")
    elif 5 < change_pct <= 7:
        sentiment_score += 8.0
        factors.append(f"涨幅{change_pct:.1f}%(强势+8%)")
    elif 7 < change_pct <= 9.8:
        sentiment_score += 5.0
        factors.append(f"涨幅{change_pct:.1f}%(近涨停+5%)")
    elif change_pct >= 9.8:
        sentiment_score += 2.0
        factors.append("已涨停(+2%)")
    elif change_pct < -3:
        sentiment_score -= 8.0
        factors.append(f"跌幅{change_pct:.1f}%(-8%)")
    elif change_pct < 0:
        sentiment_score -= 4.0
        factors.append(f"收跌{change_pct:.1f}%(-4%)")
    
    # 板块热度
    if data.get('is_hot_sector', False):
        sentiment_score += 6.0
        factors.append("热点板块(+6%)")
    
    # 大盘情绪
    market_sentiment = data.get('market_sentiment', 50)
    if market_sentiment >= 60:
        sentiment_score += 4.0
        factors.append("大盘情绪好(+4%)")
    elif market_sentiment <= 40:
        sentiment_score -= 4.0
        factors.append("大盘情绪差(-4%)")
    
    score += sentiment_score * 0.20
    
    # === 模式因子 (权重15%) ===
    pattern_score = 0.0
    
    # 突破模式
    if close > high_20d and volume > volume_20d_avg * 1.5:
        breakout_pct = (close - high_20d) / high_20d * 100 if high_20d > 0 else 0
        if breakout_pct > 2:
            pattern_score += 12.0
            factors.append(f"突破+{breakout_pct:.1f}%(+12%)")
        elif breakout_pct > 1:
            pattern_score += 8.0
            factors.append(f"突破+{breakout_pct:.1f}%(+8%)")
    
    # 回调再起
    high_recent = data.get('high_recent', close)
    if high_recent > 0:
        pullback = (high_recent - close) / high_recent * 100
        if 8 <= pullback <= 15:
            has_hammer = data.get('has_hammer', False)
            has_engulfing = data.get('has_engulfing', False)
            if has_hammer or has_engulfing:
                pattern_score += 8.0
                factors.append("回调反转(+8%)")
    
    # 连涨惯性
    streak = data.get('up_streak', 0)
    if streak >= 3:
        pattern_score += 5.0
        factors.append(f"{streak}日连涨(+5%)")
    elif streak >= 2:
        pattern_score += 2.0
        factors.append(f"{streak}日连涨(+2%)")
    
    score += pattern_score * 0.15
    
    # === 基本面因子 (权重5%) ===
    funda_score = 0.0
    
    # F-Score
    f_score = data.get('f_score', None)
    if f_score is not None:
        if f_score >= 4:
            funda_score += 5.0
            factors.append(f"F-Score={f_score}(+5%)")
        elif f_score >= 2:
            funda_score += 2.0
            factors.append(f"F-Score={f_score}(+2%)")
        else:
            funda_score -= 3.0
            factors.append(f"F-Score={f_score}(-3%)")
    
    # Z-Score
    z_score = data.get('z_score', None)
    if z_score is not None:
        if z_score >= 1.5:
            funda_score += 3.0
            factors.append(f"Z-Score安全(+3%)")
        elif z_score < 0:
            funda_score -= 5.0
            factors.append(f"Z-Score危险(-5%)")
    
    score += funda_score * 0.05
    
    # === 计算最终概率 ===
    # 基础概率50% + 因子得分
    base_prob = 50.0
    probability = base_prob + score
    
    # 限制在合理范围
    probability = max(15.0, min(95.0, probability))
    
    # 评级
    if probability >= 70:
        rating = "高"
        expected_return = "+2~5%"
    elif probability >= 55:
        rating = "中"
        expected_return = "+1~3%"
    elif probability >= 40:
        rating = "低"
        expected_return = "-1~+2%"
    else:
        rating = "回避"
        expected_return = "-2~0%"
    
    # 置信度
    factor_count = len(factors)
    data_completeness = sum(1 for k in ['macd', 'rsi6', 'volume_ratio', 'change_pct'] if k in data and data[k] != 0)
    if factor_count >= 6 and data_completeness >= 4:
        confidence = "高"
    elif factor_count >= 4 and data_completeness >= 3:
        confidence = "中"
    else:
        confidence = "低"
    
    return {
        'probability': round(probability, 1),
        'rating': rating,
        'expected_return': expected_return,
        'confidence': confidence,
        'factors': factors,
        'raw_score': round(score, 2),
    }

def run_v22_scoring(data: dict) -> dict:
    """
    v2.2 完整版评分流程 - 恢复v2.0选股核心
    
    流程:
    1. 强制排除 (Tier X)
    2. 模式检测 (六大模式)
    3. 一夜持股法 20分制 (T+0午后介入/T+1早盘退出)
    4. 三维融合 15分制 (3~20日波段)
    5. 五灯诊断 → step_multiplier (0.8~1.2)
    6. 多空七维辩论 → debate_score (-5~+5)
    7. 三级分类 Tier S/A/B/X
    8. 最终合成: (隔夜/20×0.35)+(融合/15×0.35)+(辩论/5×0.20)+0.10 × step_multiplier
    
    同时保留6维度独立评分用于内部参考:
    技术/情绪/资金/基本面/市场/消息
    """
    # === v2.2r 新增: 数据完整性检查 (2026-08-20教训) ===
    # 检查数据时效性
    data_time = data.get('data_time', '')
    if data_time:
        try:
            from datetime import datetime
            dt = datetime.strptime(data_time, '%Y%m%d%H%M')
            now = datetime.now()
            age_hours = (now - dt).total_seconds() / 3600
            if age_hours > 2:
                # 数据超过2小时，标记但不阻止评分
                data['_data_warning'] = f'数据已过期{age_hours:.0f}小时'
        except:
            pass
    
    # 检查关键字段缺失
    required_fields = ['close', 'volume', 'ma5', 'ma10', 'ma20']
    missing = [f for f in required_fields if f not in data or data[f] == 0]
    if missing:
        result = {
            'tier': 'X',
            'final_score': 0.0,
            'action': '不买',
            'action_reason': f'数据不完整，缺少: {", ".join(missing)}',
            'reasons': [f'数据不完整: {", ".join(missing)}'],
        }
        return result
    
    result = {
        'tier': 'X',
        'final_score': 0.0,
        'pattern': 0.0,
        'pattern_name': '',
        'overnight_score': 0.0,
        'overnight_grade': '',
        'fusion_score': 0.0,
        'fusion_grade': '',
        'debate_score': 0.0,
        'debate_bias': '',
        'step_multiplier': 1.0,
        'five_step_lights': 0,
        # 保留6维度参考
        'tech': 0.0,
        'sentiment': 0.0,
        'fund': 0.0,
        'fundamental': 0.0,
        'market': 0.0,
        'news': 0.0,
        'f_score': None,
        'z_score': None,
        'z_zone': None,
        'quality_tag': None,
        'reasons': [],
        # v2.2r 新增: 明确操作建议
        'action': '不买',  # 买 / 等 / 不买
        'action_reason': '',
        'buy_price': None,
        'stop_loss': None,
    }
    
    # Step 1: 强制排除
    excluded, reasons = step1_mandatory_exclusion(data)
    if excluded:
        result['tier'] = 'X'
        result['reasons'].extend(reasons)
        result['action_reason'] = f'强制排除: {reasons[0]}'
        return result
    
    excluded, reasons = step1_5_news_exclusion(data)
    if excluded:
        result['tier'] = 'X'
        result['reasons'].extend(reasons)
        result['action_reason'] = f'新闻排除: {reasons[0]}'
        return result
    
    # Step 2: 模式检测
    pattern_score, pattern_name = step2_pattern_detection(data)
    result['pattern'] = pattern_score
    result['pattern_name'] = pattern_name
    if pattern_score > 0:
        result['reasons'].append(f"模式: {pattern_name}")
    
    # Step 3: 一夜持股法 20分制
    overnight, overnight_grade, overnight_reasons = overnight_score(data)
    result['overnight_score'] = overnight
    result['overnight_grade'] = overnight_grade
    result['reasons'].extend(overnight_reasons)
    
    # Step 4: 三维融合 15分制
    fusion, fusion_grade, fusion_reasons = fusion_score(data)
    result['fusion_score'] = fusion
    result['fusion_grade'] = fusion_grade
    result['reasons'].extend(fusion_reasons)
    
    # Step 5: 五灯诊断 → step_multiplier
    market_score, market_reasons, market_mul = step7_market_score(data)
    result['market'] = market_score
    result['step_multiplier'] = market_mul
    result['reasons'].extend(market_reasons)
    # 计算绿灯数
    result['five_step_lights'] = market_reasons.count('绿灯')
    
    # Step 6: 多空七维辩论 (通过multi_agent_debate.py)
    # 这里先占位，实际调用在scanner层
    result['debate_score'] = 0.0
    result['debate_bias'] = '中性'
    
    # 保留6维度参考评分
    tech_score, tech_reasons = step3_technical_score(data)
    sent_score, sent_reasons = step4_sentiment_score(data)
    fund_score, fund_reasons = step5_fund_score(data)
    funda_score, funda_reasons, adjustment = step6_fundamental_score(data)
    news_score, news_reasons = step8_news_score(data)
    
    result['tech'] = tech_score
    result['sentiment'] = sent_score
    result['fund'] = fund_score
    result['fundamental'] = funda_score
    result['news'] = news_score
    # 记录各维度理由
    result['reasons'].extend(tech_reasons)
    result['reasons'].extend(sent_reasons)
    result['reasons'].extend(fund_reasons)
    result['reasons'].extend(funda_reasons)
    result['reasons'].extend(news_reasons)
    result['f_score'] = adjustment.get('f_score')
    result['quality_tag'] = adjustment.get('quality_tag')
    z_info = adjustment.get('z_info', {})
    result['z_score'] = z_info.get('z_score')
    result['z_zone'] = z_info.get('zone')
    
    # 基本面风险排除
    if adjustment.get('exclude'):
        result['tier'] = 'X'
        result['reasons'].append("基本面风险排除")
        return result
    
    # Step 7: 三级分类 Tier S/A/B/X
    # 检查是否在热点前3板块
    is_top3 = data.get('is_top3_sector', False)
    tier = step10_tier_classification(overnight, fusion, 0.0, pattern_score, is_top3)
    result['tier'] = tier
    
    # Step 8: 最终合成 (v2.0公式)
    # debate_score暂时用0，实际在scanner层调用multi_agent_debate后回填
    final = step11_final_synthesis(overnight, fusion, result['debate_score'], 
                                   result['step_multiplier'], data)
    result['final_score'] = final
    
    # ★ 新增: 过夜胜率预测
    overnight_prob = calc_overnight_probability(data)
    result['overnight_prob'] = overnight_prob['probability']
    result['overnight_rating'] = overnight_prob['rating']
    result['overnight_expected'] = overnight_prob['expected_return']
    result['overnight_confidence'] = overnight_prob['confidence']
    result['overnight_factors'] = overnight_prob['factors']
    
    # ★ 新增: 策略类型判定
    result['strategy_type'] = classify_strategy(
        result['overnight_score'], result['overnight_grade'],
        result['fusion_score'], result['fusion_grade']
    )
    
    # === v2.2r 新增: 明确操作建议 (2026-08-20教训) ===
    close = data.get('close', 0)
    change_pct = data.get('change_pct', 0)
    ma5 = data.get('ma5', close)
    ma10 = data.get('ma10', close)
    ma20 = data.get('ma20', close)
    
    if result['tier'] == 'X':
        result['action'] = '不买'
        result['action_reason'] = '触发强制排除规则'
    elif result['tier'] == 'S':
        if change_pct <= 5:
            result['action'] = '买'
            result['action_reason'] = 'S级且涨幅可控'
            result['buy_price'] = f"≤{close:.2f}"
            result['stop_loss'] = f"{ma10:.2f}"
        else:
            result['action'] = '等'
            result['action_reason'] = f'S级但已涨{change_pct:.1f}%，等回调到MA5({ma5:.2f})'
            result['buy_price'] = f"{ma5:.2f}附近"
            result['stop_loss'] = f"{ma10:.2f}"
    elif result['tier'] == 'A':
        if change_pct <= 3:
            result['action'] = '买'
            result['action_reason'] = f'A级且涨幅{change_pct:.1f}%可控'
            result['buy_price'] = f"≤{close:.2f}"
            result['stop_loss'] = f"{ma20:.2f}"
        elif change_pct <= 5:
            result['action'] = '等'
            result['action_reason'] = f'A级但已涨{change_pct:.1f}%，等回调到MA5({ma5:.2f})'
            result['buy_price'] = f"{ma5:.2f}附近"
            result['stop_loss'] = f"{ma20:.2f}"
        else:
            result['action'] = '等'
            result['action_reason'] = f'A级但已涨{change_pct:.1f}%过高，等回调到MA10({ma10:.2f})'
            result['buy_price'] = f"{ma10:.2f}附近"
            result['stop_loss'] = f"{ma20:.2f}"
    elif result['tier'] == 'B':
        result['action'] = '等'
        result['action_reason'] = 'B级观望，等 stronger 信号'
        result['buy_price'] = f"{ma20:.2f}附近"
    else:
        result['action'] = '不买'
        result['action_reason'] = '不满足任何买入条件'
    
    return result


# =======================================================================
# 策略类型判定 (过夜 vs 波段)
# =======================================================================

def classify_strategy(overnight: float, overnight_grade: str,
                       fusion: float, fusion_grade: str) -> dict:
    """
    判定股票适合的交易策略类型
    
    返回: {
        'type': '过夜' | '波段' | '两者皆可' | '观望',
        'overnight': bool,
        'swing': bool,
        'reason': str,
    }
    """
    # 过夜策略阈值
    overnight_ok = overnight >= 8  # 黄金/优质
    # 波段策略阈值  
    swing_ok = fusion >= 5  # 一般及以上
    
    if overnight_ok and swing_ok:
        return {
            'type': '两者皆可',
            'overnight': True,
            'swing': True,
            'reason': f'隔夜{overnight:.1f}分({overnight_grade}) + 波段{fusion:.1f}分({fusion_grade})'
        }
    elif overnight_ok:
        return {
            'type': '过夜',
            'overnight': True,
            'swing': False,
            'reason': f'隔夜{overnight:.1f}分({overnight_grade})，波段{fusion:.1f}分({fusion_grade})偏弱'
        }
    elif swing_ok:
        return {
            'type': '波段',
            'overnight': False,
            'swing': True,
            'reason': f'波段{fusion:.1f}分({fusion_grade})，隔夜{overnight:.1f}分({overnight_grade})偏弱'
        }
    else:
        return {
            'type': '观望',
            'overnight': False,
            'swing': False,
            'reason': f'隔夜{overnight:.1f}分({overnight_grade}) + 波段{fusion:.1f}分({fusion_grade})，均不满足'
        }


# =======================================================================
# 主线池质量评分 (不变)
# =======================================================================

def calc_main_line_quality(concept_data: dict) -> float:
    """主线池质量评分 (扩散指标+RRG)"""
    diffusion = concept_data.get('diffusion', 0)
    rrg_x = concept_data.get('rrg_x', 0)
    rrg_y = concept_data.get('rrg_y', 0)
    
    if rrg_x > 100 and rrg_y > 100:
        rrg_zone = 'leading'
    elif rrg_x > 100 and rrg_y < 100:
        rrg_zone = 'weakening'
    elif rrg_x < 100 and rrg_y > 100:
        rrg_zone = 'improving'
    else:
        rrg_zone = 'lagging'
    
    diffusion_ma20 = concept_data.get('diffusion_ma20', diffusion)
    diffusion_up = diffusion > diffusion_ma20
    
    if diffusion_up and rrg_zone == 'leading':
        return 1.0
    elif diffusion > 0.6 and rrg_zone == 'weakening':
        return 0.3
    elif rrg_zone == 'improving' and diffusion < 0.4:
        return 0.5
    elif rrg_zone == 'lagging':
        return 0.0
    else:
        return 0.3


def calc_diffusion(stocks_in_concept: list) -> float:
    """计算概念扩散指标"""
    if not stocks_in_concept:
        return 0.0
    
    total_cap = sum(s.get('free_float_cap', 0) for s in stocks_in_concept)
    if total_cap == 0:
        return 0.0
    
    rising_cap = sum(s.get('free_float_cap', 0) 
                     for s in stocks_in_concept 
                     if s.get('change_pct', 0) > 0)
    
    return rising_cap / total_cap


# ======================================================================
# v2.0 核心链路: 5日板块扫描 + 热点合并 + 模式检测执行
# ======================================================================

class ScanError(Exception):
    """板块扫描数据不完整"""
    pass

class ClassificationError(Exception):
    """有效候选股不足"""
    pass


def scan_5day_sectors(sector_history: List[dict]) -> List[dict]:
    """
    全市场5日板块扫描
    复合评分 = 0.4×涨幅排名 + 0.3×涨停密度 + 0.3×资金流排名
    返回: Top 20 板块列表
    """
    if not sector_history:
        raise ScanError("板块历史数据为空")
    
    sectors = {}
    for record in sector_history:
        name = record.get('sector_name', '')
        if not name:
            continue
        if name not in sectors:
            sectors[name] = {
                'name': name,
                'appear_days': 0,
                'avg_change': 0,
                'limit_up_count': 0,
                'total_amount': 0,
            }
        sectors[name]['appear_days'] += record.get('appear_days', 0)
        sectors[name]['avg_change'] += record.get('avg_change', 0)
        sectors[name]['limit_up_count'] += record.get('limit_up_count', 0)
        sectors[name]['total_amount'] += record.get('total_amount', 0)
    
    if len(sectors) < 3:
        raise ScanError(f"板块数据不完整，仅{len(sectors)}个板块")
    
    # 计算排名
    sorted_by_change = sorted(sectors.values(), key=lambda x: x['avg_change'], reverse=True)
    change_ranks = {s['name']: i+1 for i, s in enumerate(sorted_by_change)}
    
    for s in sectors.values():
        days = max(1, s['appear_days'])
        s['limit_up_density'] = s['limit_up_count'] / days
    
    sorted_by_density = sorted(sectors.values(), key=lambda x: x['limit_up_density'], reverse=True)
    density_ranks = {s['name']: i+1 for i, s in enumerate(sorted_by_density)}
    
    sorted_by_amount = sorted(sectors.values(), key=lambda x: x['total_amount'], reverse=True)
    amount_ranks = {s['name']: i+1 for i, s in enumerate(sorted_by_amount)}
    
    n = len(sectors)
    results = []
    for name, s in sectors.items():
        change_score = (n - change_ranks.get(name, n)) / n * 100
        density_score = (n - density_ranks.get(name, n)) / n * 100
        amount_score = (n - amount_ranks.get(name, n)) / n * 100
        composite = 0.4 * change_score + 0.3 * density_score + 0.3 * amount_score
        
        results.append({
            'name': name,
            'composite_score': round(composite, 2),
            'appear_days': s['appear_days'],
            'avg_change': round(s['avg_change'], 2),
            'limit_up_density': round(s['limit_up_density'], 2),
            'total_amount': s['total_amount'],
        })
    
    results.sort(key=lambda x: x['composite_score'], reverse=True)
    return results[:20]


def merge_hot_sectors(sector_5day: List[dict], sector_today: List[dict]) -> List[dict]:
    """
    热点合并: 5日扫描与当日热点取并集、去重
    同时出现的板块给予1.15倍加成
    返回: Top 15 合并热点板块
    """
    merged = {}
    
    for s in sector_5day:
        name = s['name']
        merged[name] = {
            'name': name,
            'score_5day': s['composite_score'],
            'score_today': 0,
            'is_both': False,
        }
    
    for s in sector_today:
        name = s.get('sector_name', '')
        if not name:
            continue
        if name in merged:
            merged[name]['score_today'] = s.get('score', 0)
            merged[name]['is_both'] = True
        else:
            merged[name] = {
                'name': name,
                'score_5day': 0,
                'score_today': s.get('score', 0),
                'is_both': False,
            }
    
    results = []
    for name, m in merged.items():
        base_score = max(m['score_5day'], m['score_today'] * 0.8)
        if m['is_both']:
            base_score *= 1.15
        
        results.append({
            'name': name,
            'final_score': round(base_score, 2),
            'score_5day': m['score_5day'],
            'score_today': m['score_today'],
            'is_both': m['is_both'],
        })
    
    results.sort(key=lambda x: x['final_score'], reverse=True)
    return results[:15]


def run_pattern_detection_on_sectors(
    merged_sectors: List[dict],
    sector_top_stocks: Dict[str, List[dict]],
    recent_limit_up_pool: List[str],
    recent_strong_pool: List[str],
    stock_data_map: Dict[str, dict],
) -> Dict[str, dict]:
    """
    五大模式检测执行流程
    对合并热点板块Top 3 + 近5日涨停/强势池全部标的运行模式检测
    单标的可匹配多个模式，得分累加上限2.0分
    """
    results = {}
    all_codes = set()
    
    # 收集所有待检测标的
    for sector_name, stocks in sector_top_stocks.items():
        for s in stocks[:3]:
            code = s.get('code', '')
            if code:
                all_codes.add(code)
    
    all_codes.update(recent_limit_up_pool)
    all_codes.update(recent_strong_pool)
    
    # 逐一检测
    for code in all_codes:
        data = stock_data_map.get(code, {})
        if not data:
            continue
        
        pattern_score, pattern_name = step2_pattern_detection(data)
        
        if code not in results:
            results[code] = {'pattern_score': 0.0, 'pattern_names': []}
        
        # 累加，上限2.0
        new_score = min(2.0, results[code]['pattern_score'] + pattern_score)
        results[code]['pattern_score'] = new_score
        if pattern_name and pattern_name != "无模式":
            results[code]['pattern_names'].append(pattern_name)
    
    return results


# ======================================================================
# 测试
# =======================================================================

if __name__ == '__main__':
    test_data = {
        'code': '600519',
        'name': '贵州茅台',
        'close': 1500.0,
        'open': 1480.0,
        'high': 1510.0,
        'low': 1475.0,
        'prev_close': 1470.0,
        'volume': 50000,
        'amount': 75000,
        'volume_20d_avg': 40000,
        'high_20d': 1490.0,
        'ma5': 1480.0,
        'ma10': 1460.0,
        'ma20': 1440.0,
        'macd': 5.0,
        'rsi6': 65.0,
        'kdj_k': 60.0,
        'kdj_d': 55.0,
        'kdj_j': 70.0,
        'volume_ratio': 1.8,
        'change_pct': 2.0,
        'streak_days': 2,
        'is_hot_sector': True,
        'institution_hold_pct': 35.0,
        'market_cap': 18000.0,
        'beta': 1.2,
        'sector_return': 2.5,
        'index_change': 0.5,
        'sector_change': 1.0,
        'total_position_pct': 0.3,
        'rebound_count': 3,
        'retail_etf_flow': -5000,
        'erp': 0.04,
        'margin_status': 1,
        'market_breadth': 0.65,
        'sentiment_score': 0.4,
        'fundamental_score': 0.2,
        'news_sentiment': 0.3,
        'notice_risk': 2,
        'date': '20260818',
        'roe': 15.0,
        'gross_margin': 90.0,
        'net_margin': 50.0,
        'debt_ratio': 30.0,
        'current_ratio': 3.0,
    }
    
    result = run_v22r_scoring(test_data)
    
    print("=" * 60)
    print("v2.2r 重构版评分结果")
    print("=" * 60)
    print(f"评级: {result['tier']}")
    print(f"最终得分: {result['final_score']:.3f}")
    print(f"模式: {result['pattern_name']} ({result['pattern']:.1f})")
    print(f"技术面: {result['tech']:.1f}/25")
    print(f"情绪面: {result['sentiment']:.1f}/15")
    print(f"资金面: {result['fund']:.1f}/15")
    print(f"基本面: {result['fundamental']:.1f}/15")
    print(f"市场环境: {result['market']:+.1f} (乘数{result['market_mul']:.2f})")
    print(f"消息面: {result['news']:+.1f}")
    print(f"F-Score: {result['f_score']}/5 ({result['quality_tag']})")
    print(f"Z-Score: {result['z_score']}")
    print(f"\n理由:")
    for r in result['reasons']:
        print(f"  - {r}")
