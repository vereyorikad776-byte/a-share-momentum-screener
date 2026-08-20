#!/usr/bin/env python3
"""
News Analyzer v1.0
新闻公告异动分析模块 —— 把"消息面"变成可量化的评分信号

核心能力：
1. 新闻情感分析 → 利好/利空强度 (-1~+1)
2. 公告风险检测 → 业绩暴雷/监管处罚/大股东减持 (0~5级)
3. 热点事件关联 → 股票与当前热点的匹配度 (0~1)
4. 研报异动检测 → 研报上调/下调/首次覆盖
5. 综合新闻评分 → 整合所有信号为单一分数

数据源：iFinD search_news / search_notice / search_trending_news
"""

import sys
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

# 添加 ifind-momentum-screener 路径
sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

# iFinD调用 - 延迟加载，未配置时返回None
call = None
def _get_call():
    global call
    if call is not None:
        return call
    try:
        from ifind_call import call as _call
        call = _call
        return call
    except Exception as e:
        print(f"⚠️ iFinD未配置: {e}")
        return None

def safe_call(*args, **kwargs):
    """安全调用iFinD，未配置时返回None"""
    c = _get_call()
    if c is None:
        return None
    try:
        return c(*args, **kwargs)
    except Exception as e:
        print(f"⚠️ iFinD调用失败: {e}")
        return None

# 导入 ifind_client 的限速控制
# from ifind_client import _throttle
# 已删除ifind_client，使用简单限速
import time
_last_call = 0
def _throttle():
    global _last_call
    now = time.time()
    elapsed = now - _last_call
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    _last_call = time.time()


# ============ 负面关键词库 ============

NEGATIVE_KEYWORDS = {
    "致命级": ["立案调查", "财务造假", "重大违法", "强制退市", "破产", "资不抵债"],
    "严重级": ["业绩预亏", "净利润下滑", "亏损扩大", "商誉减值", "资产减值", "债务违约", "评级下调", "暂停上市"],
    "警示级": ["监管函", "关注函", "问询函", "警示函", "行政处罚", "减持", "清仓", "解禁", "限售股上市", "股东减持"],
    "利空级": ["不及预期", " miss ", "下滑", "下降", "减少", "裁员", "停工", "停产", "召回", "诉讼", "仲裁"],
}

POSITIVE_KEYWORDS = {
    "重大级": ["业绩预增", "净利润增长", "扭亏为盈", "中标", "重大合同", "订单", "扩产", "产能释放", "涨价", "产品提价"],
    "利好级": ["回购", "增持", "股权激励", "分红", "高送转", "战略合作", "技术突破", "专利", "获批", "认证"],
    "关注级": ["调研", "机构关注", "买入评级", "增持评级", "目标价上调", "首次覆盖"],
}

HOT_EVENT_KEYWORDS = {
    "算力/AIDC": ["算力", "AIDC", "数据中心", "智算中心", "GPU", "服务器"],
    "光通信/CPO": ["光通信", "CPO", "光模块", "硅光", "800G", "1.6T"],
    "半导体": ["半导体", "芯片", "晶圆", "光刻", "EDA", "国产替代"],
    "AI/大模型": ["人工智能", "大模型", "AI", "Agent", "智能体"],
    "机器人": ["机器人", "人形机器人", "具身智能", "减速器", "丝杠"],
    "新能源": ["新能源", "光伏", "储能", "锂电池", "固态电池", "氢能"],
    "创新药": ["创新药", "生物医药", "ADC", "GLP-1", "临床获批"],
    "低空经济": ["低空经济", "eVTOL", "飞行汽车", "无人机", "空管"],
    "智能驾驶": ["智能驾驶", "自动驾驶", "激光雷达", "毫米波雷达", "NOA"],
    "电力/电网": ["电力", "电网", "特高压", "虚拟电厂", "储能", "充电桩"],
}


def _throttle_news():
    """新闻接口限速"""
    _throttle()


def get_news_for_stock(code: str, name: str = "", days: int = 3, size: int = 10) -> List[Dict]:
    """
    获取单只股票的相关新闻
    
    Args:
        code: 股票代码
        name: 股票简称（用于搜索）
        days: 回溯天数
        size: 返回条数
    
    Returns:
        List[Dict]: [{title, content, date, source}, ...]
    """
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = f"{name or code}"
    _throttle_news()
    result = safe_call('news', 'search_news', {
        'query': query,
        'time_start': start_date,
        'time_end': end_date,
        'size': size
    })
    
    if not result or not result.get('ok'):
        return []
    
    return _parse_news_result(result)


def get_notices_for_stock(code: str, name: str = "", days: int = 7, size: int = 10) -> List[Dict]:
    """
    获取单只股票的相关公告
    
    Args:
        code: 股票代码
        name: 股票简称
        days: 回溯天数
        size: 返回条数
    
    Returns:
        List[Dict]: [{title, content, date, type}, ...]
    """
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    query = f"{name or code}"
    _throttle_news()
    result = safe_call('news', 'search_notice', {
        'query': query,
        'time_start': start_date,
        'time_end': end_date,
        'size': size
    })
    
    if not result or not result.get('ok'):
        return []
    
    return _parse_notice_result(result)


def get_trending_news(keyword: str = "", industry: str = "", time_scope: str = "近一周", size: int = 10) -> List[Dict]:
    """
    获取热点事件资讯
    
    Args:
        keyword: 关键词
        industry: 行业名称
        time_scope: 时效范围 (24小时/近一周/近一月)
        size: 返回条数
    
    Returns:
        List[Dict]: [{title, content, date, heat}, ...]
    """
    params = {'time_scope': time_scope, 'size': size}
    if keyword:
        params['keyword'] = keyword
    if industry:
        params['industry_name'] = industry
    
    _throttle_news()
    result = safe_call('news', 'search_trending_news', params)
    
    if not result or not result.get('ok'):
        return []
    
    return _parse_news_result(result)


def _parse_news_result(result) -> List[Dict]:
    """解析新闻搜索结果"""
    entries = []
    try:
        content = result.get('data', {}).get('result', {}).get('content', [])
        if not content:
            return entries
        text = content[0].get('text', '')
        import json
        parsed = json.loads(text)
        data = parsed.get('data', parsed)
        
        # 尝试多种格式
        if isinstance(data, list):
            for item in data:
                entries.append({
                    'title': item.get('title', item.get('标题', '')),
                    'content': item.get('content', item.get('摘要', item.get('正文', ''))),
                    'date': item.get('date', item.get('发布时间', item.get('时间', ''))),
                    'source': item.get('source', item.get('来源', '')),
                })
        elif isinstance(data, dict):
            # 可能是嵌套结构
            for key in ['news', 'list', 'items', 'result']:
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        entries.append({
                            'title': item.get('title', item.get('标题', '')),
                            'content': item.get('content', item.get('摘要', '')),
                            'date': item.get('date', item.get('发布时间', '')),
                            'source': item.get('source', item.get('来源', '')),
                        })
                    break
    except Exception as e:
        pass
    
    return entries


def _parse_notice_result(result) -> List[Dict]:
    """解析公告搜索结果（格式同新闻）"""
    return _parse_news_result(result)


# ============ 信号检测 ============

def analyze_news_sentiment(news_list: List[Dict]) -> Tuple[float, List[str]]:
    """
    分析新闻情感倾向
    
    Returns:
        (sentiment_score, reasons)
        sentiment_score: -1.0(极利空) ~ +1.0(极利好)
    """
    if not news_list:
        return 0.0, []
    
    total_score = 0.0
    reasons = []
    
    for news in news_list:
        text = f"{news.get('title', '')} {news.get('content', '')}"
        score = 0.0
        
        # 负面检测
        for level, keywords in NEGATIVE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    if level == "致命级":
                        score -= 2.0
                        reasons.append(f"⚠️ 致命利空: {kw}")
                    elif level == "严重级":
                        score -= 1.0
                        reasons.append(f"⚠️ 严重利空: {kw}")
                    elif level == "警示级":
                        score -= 0.5
                        reasons.append(f"⚠️ 警示: {kw}")
                    else:
                        score -= 0.2
        
        # 正面检测
        for level, keywords in POSITIVE_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    if level == "重大级":
                        score += 1.5
                        reasons.append(f"✅ 重大利好: {kw}")
                    elif level == "利好级":
                        score += 0.8
                        reasons.append(f"✅ 利好: {kw}")
                    else:
                        score += 0.3
        
        total_score += score
    
    # 归一化到 -1~+1
    avg_score = total_score / len(news_list) if news_list else 0
    sentiment = max(-1.0, min(1.0, avg_score / 3.0))  # 缩放因子
    
    return sentiment, list(set(reasons))[:5]  # 去重，最多5条


def analyze_notices_risk(notice_list: List[Dict]) -> Tuple[int, List[str]]:
    """
    分析公告风险等级
    
    Returns:
        (risk_level, reasons)
        risk_level: 0(无风险) ~ 5(极高风险)
    """
    if not notice_list:
        return 0, []
    
    risk_score = 0
    reasons = []
    
    for notice in notice_list:
        text = f"{notice.get('title', '')} {notice.get('content', '')}"
        
        # 致命级
        for kw in NEGATIVE_KEYWORDS["致命级"]:
            if kw in text:
                risk_score = max(risk_score, 5)
                reasons.append(f"🔴 致命风险: {kw}")
                return 5, reasons  # 直接返回最高级
        
        # 严重级
        for kw in NEGATIVE_KEYWORDS["严重级"]:
            if kw in text:
                risk_score = max(risk_score, 4)
                reasons.append(f"🟠 严重风险: {kw}")
        
        # 警示级
        for kw in NEGATIVE_KEYWORDS["警示级"]:
            if kw in text:
                risk_score = max(risk_score, 3)
                reasons.append(f"🟡 风险: {kw}")
        
        # 业绩相关
        if "业绩预告" in text or "业绩快报" in text:
            if any(kw in text for kw in ["预亏", "亏损", "下滑", "下降", "减少"]):
                risk_score = max(risk_score, 4)
                reasons.append(f"🟠 业绩预亏/下滑")
            elif any(kw in text for kw in ["预增", "增长", "扭亏", "大幅"]):
                # 正面业绩，不增加风险
                pass
    
    return min(5, risk_score), list(set(reasons))[:5]


def detect_earnings_event(notice_list: List[Dict]) -> Tuple[Optional[str], float]:
    """
    检测业绩披露事件
    
    Returns:
        (event_type, impact_score)
        event_type: "预增"/"预亏"/"超预期"/"不及预期"/None
        impact_score: -2~+2
    """
    for notice in notice_list:
        text = f"{notice.get('title', '')} {notice.get('content', '')}"
        
        if "业绩预告" in text or "业绩快报" in text or "年度报告" in text or "季度报告" in text:
            if any(kw in text for kw in ["预增", "净利润增长", "大幅增长", "扭亏为盈"]):
                if "超预期" in text or "大幅" in text:
                    return "超预期", 2.0
                return "预增", 1.0
            elif any(kw in text for kw in ["预亏", "亏损", "净利润下降", "大幅下滑"]):
                if "不及预期" in text:
                    return "不及预期", -2.0
                return "预亏", -1.5
    
    return None, 0.0


def detect_major_contract(notice_list: List[Dict]) -> Tuple[bool, float]:
    """
    检测重大合同/订单公告
    
    Returns:
        (has_contract, impact_score)
    """
    for notice in notice_list:
        text = f"{notice.get('title', '')}"
        if any(kw in text for kw in ["中标", "重大合同", "签订", "订单", "框架协议"]):
            # 估算合同金额影响（粗略）
            impact = 1.0
            if "亿元" in text:
                impact = 1.5
            elif "千万" in text or "百万" in text:
                impact = 0.8
            return True, impact
    
    return False, 0.0


def check_hot_event_relation(code: str, name: str, concept_list: List[str], hot_keywords: List[str]) -> float:
    """
    检查股票与当前热点事件的关联度
    
    Args:
        code: 股票代码
        name: 股票名称
        concept_list: 股票所属概念列表
        hot_keywords: 当前热点关键词列表
    
    Returns:
        relation_score: 0~1
    """
    if not concept_list or not hot_keywords:
        return 0.0
    
    match_count = 0
    for concept in concept_list:
        for hot in hot_keywords:
            if hot in concept or concept in hot:
                match_count += 1
    
    # 归一化
    score = min(1.0, match_count / max(len(hot_keywords) * 0.3, 1))
    return score


def get_hot_events(top_n: int = 5) -> List[Dict]:
    """
    获取当前热点事件列表
    
    Returns:
        List[Dict]: [{keyword, heat, related_concepts}, ...]
    """
    hot_news = get_trending_news(time_scope="24小时", size=20)
    
    # 统计热点关键词频率
    keyword_count = {}
    for news in hot_news:
        text = f"{news.get('title', '')} {news.get('content', '')}"
        for category, keywords in HOT_EVENT_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    keyword_count[category] = keyword_count.get(category, 0) + 1
    
    # 排序返回
    sorted_hot = sorted(keyword_count.items(), key=lambda x: x[1], reverse=True)
    return [
        {'keyword': cat, 'heat': count, 'related_concepts': HOT_EVENT_KEYWORDS.get(cat, [])}
        for cat, count in sorted_hot[:top_n]
    ]


# ============ 综合评分接口 ============

def get_news_score(code: str, name: str = "", date_str: str = "",
                   concept_list: List[str] = None,
                   fetch_news: bool = True) -> Dict:
    """
    综合新闻公告评分接口（供 v21_engine 调用）
    
    Returns:
        {
            'news_sentiment': -1~+1,      # 新闻情感
            'notice_risk': 0~5,            # 公告风险等级
            'earnings_event': str/None,    # 业绩事件
            'earnings_impact': -2~+2,      # 业绩影响分
            'has_contract': bool,          # 重大合同
            'contract_impact': 0~1.5,      # 合同影响分
            'hot_relation': 0~1,           # 热点关联度
            'is_blacklisted': bool,        # 是否触发黑名单
            'blacklist_reasons': [str],    # 黑名单原因
            'raw_score': float,            # 原始综合分
        }
    """
    result = {
        'news_sentiment': 0.0,
        'notice_risk': 0,
        'earnings_event': None,
        'earnings_impact': 0.0,
        'has_contract': False,
        'contract_impact': 0.0,
        'hot_relation': 0.0,
        'is_blacklisted': False,
        'blacklist_reasons': [],
        'raw_score': 0.0,
    }
    
    if not fetch_news:
        return result
    
    try:
        # 1. 获取新闻
        news_list = get_news_for_stock(code, name, days=3, size=10)
        sentiment, sentiment_reasons = analyze_news_sentiment(news_list)
        result['news_sentiment'] = sentiment
        
        # 2. 获取公告
        notice_list = get_notices_for_stock(code, name, days=7, size=15)
        risk_level, risk_reasons = analyze_notices_risk(notice_list)
        result['notice_risk'] = risk_level
        
        # 3. 业绩检测
        earnings_event, earnings_impact = detect_earnings_event(notice_list)
        result['earnings_event'] = earnings_event
        result['earnings_impact'] = earnings_impact
        
        # 4. 重大合同
        has_contract, contract_impact = detect_major_contract(notice_list)
        result['has_contract'] = has_contract
        result['contract_impact'] = contract_impact
        
        # 5. 热点关联
        if concept_list:
            hot_events = get_hot_events(top_n=5)
            hot_keywords = []
            for event in hot_events:
                hot_keywords.extend(event.get('related_concepts', []))
            result['hot_relation'] = check_hot_event_relation(code, name, concept_list, hot_keywords)
        
        # 6. 黑名单检测
        if risk_level >= 4:
            result['is_blacklisted'] = True
            result['blacklist_reasons'] = risk_reasons
        elif sentiment < -0.8:
            result['is_blacklisted'] = True
            result['blacklist_reasons'] = sentiment_reasons
        
        # 7. 综合原始分
        raw = (
            sentiment * 2.0 +           # 新闻情感 -2~+2
            (5 - risk_level) * 0.3 +    # 风险等级 0~1.5
            earnings_impact +           # 业绩 -2~+2
            contract_impact +           # 合同 0~1.5
            result['hot_relation'] * 0.5  # 热点 0~0.5
        )
        result['raw_score'] = raw
        
    except Exception as e:
        # 新闻接口失败不阻断主流程
        pass
    
    return result


# ============ 快捷函数 ============

def quick_news_check(code: str, name: str = "") -> Tuple[bool, List[str]]:
    """
    快速新闻风险检查（用于强制排除规则）
    
    Returns:
        (is_risky, reasons)
    """
    score = get_news_score(code, name, fetch_news=True)
    if score['is_blacklisted']:
        return True, score['blacklist_reasons']
    if score['notice_risk'] >= 4:
        return True, [f"公告风险等级{score['notice_risk']}"]
    return False, []


if __name__ == "__main__":
    # 测试
    print("测试新闻分析模块...")
    
    # 测试热点获取
    print("\n1. 当前热点事件:")
    hot = get_hot_events(top_n=5)
    for h in hot:
        print(f"   {h['keyword']}: 热度={h['heat']}")
    
    # 测试单票新闻评分
    print("\n2. 600519 新闻评分:")
    score = get_news_score('600519', '贵州茅台', concept_list=['白酒', '消费', '食品饮料'])
    print(f"   新闻情感: {score['news_sentiment']:.2f}")
    print(f"   公告风险: {score['notice_risk']}")
    print(f"   业绩事件: {score['earnings_event']}")
    print(f"   热点关联: {score['hot_relation']:.2f}")
    print(f"   黑名单: {score['is_blacklisted']}")
    print(f"   综合分: {score['raw_score']:.2f}")
