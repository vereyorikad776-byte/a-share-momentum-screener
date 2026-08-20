#!/usr/bin/env python3
"""
news_sentiment.py — 舆情情报模块
===============================
接入iFinD新闻/公告/热点数据，为v21评分提供真实的news_score
"""
import sys, json, re
from datetime import datetime, timedelta

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')
from ifind_call import call

# 关键词库
RISK_KEYWORDS = [
    '减持', '解禁', '退市', 'ST', '立案调查', '监管', '处罚', '亏损',
    '暴雷', '违约', '债务', '诉讼', '仲裁', '冻结', '质押', '清仓',
    '召回', '停产', '裁员', '业绩下滑', '不及预期'
]

POSITIVE_KEYWORDS = [
    '增持', '回购', '预增', '中标', '签约', '订单', '扩产', '投产',
    '突破', '创新高', '龙头', '领先', '独家', '核心技术', '专利',
    '政策利好', '补贴', '扶持', '进口替代', '国产替代'
]

def _to_ifind_code(code):
    """转换代码格式"""
    code = str(code).strip()
    if code.startswith(('sh.', 'sz.', 'bj.')):
        return code[3:]
    if code.startswith('6'):
        return code + '.SH'
    if code.startswith(('0', '3')):
        return code + '.SZ'
    return code

class NewsSentimentAnalyzer:
    """舆情分析器"""
    
    def __init__(self):
        self.cache = {}  # 简单内存缓存，避免重复请求
    
    def search_stock_news(self, code, days=3):
        """搜索个股新闻，返回情感评分"""
        cache_key = f"{code}_{days}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        ifind_code = _to_ifind_code(code)
        
        # 1. 搜索新闻
        news_result = call('news', 'search_news', {
            'query': f'{ifind_code} 最近{days}天',
            'top_k': 10
        })
        
        # 2. 搜索公告
        notice_result = call('news', 'search_notice', {
            'query': f'{ifind_code} 最近{days}天',
            'top_k': 10
        })
        
        # 3. 解析文本
        news_texts = []
        if news_result.get('ok'):
            content = news_result.get('data', {}).get('result', {}).get('content', [])
            news_texts.extend(self._extract_texts(content))
        
        notice_texts = []
        if notice_result.get('ok'):
            content = notice_result.get('data', {}).get('result', {}).get('content', [])
            notice_texts.extend(self._extract_texts(content))
        
        all_text = ' '.join(news_texts + notice_texts)
        
        # 4. 计算情感
        sentiment = self._calc_sentiment(all_text)
        risk_score = self._calc_risk(notice_texts)
        
        result = {
            'sentiment': round(sentiment, 2),      # -1 ~ +1
            'risk_score': risk_score,               # 0 ~ 5
            'news_count': len(news_texts),
            'notice_count': len(notice_texts),
            'has_major_risk': risk_score >= 4,
        }
        
        self.cache[cache_key] = result
        return result
    
    def _extract_texts(self, content):
        """从返回内容中提取文本"""
        texts = []
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict):
                    text = item.get('text', item.get('content', ''))
                    if text:
                        texts.append(str(text))
                elif isinstance(item, str):
                    texts.append(item)
        elif isinstance(content, str):
            texts.append(content)
        return texts
    
    def _calc_sentiment(self, text):
        """基于关键词计算情感"""
        if not text:
            return 0.0
        
        pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
        neg_count = sum(1 for kw in RISK_KEYWORDS if kw in text)
        total = pos_count + neg_count
        
        if total == 0:
            return 0.0
        
        # 归一化到 -1 ~ +1
        score = (pos_count - neg_count) / max(total, 3)
        return max(-1, min(1, score))
    
    def _calc_risk(self, notice_texts):
        """从公告中提取风险等级 0-5"""
        if not notice_texts:
            return 0
        
        text = ' '.join(notice_texts)
        risk_count = sum(1 for kw in RISK_KEYWORDS if kw in text)
        
        # 减持/解禁/退市/立案 = 高风险
        if any(kw in text for kw in ['减持', '解禁', '退市', '立案']):
            return min(5, 3 + risk_count)
        
        return min(5, risk_count)
    
    def get_news_score_for_v21(self, code, days=3):
        """为v21评分计算news_score (-3 ~ +3)"""
        result = self.search_stock_news(code, days)
        
        # 基础分
        sentiment = result['sentiment']
        risk = result['risk_score']
        
        # 计算得分
        news_score = sentiment * 1.5 + (5 - risk) * 0.2
        
        # 信息不足时降权
        if result['news_count'] + result['notice_count'] < 2:
            news_score *= 0.5
        
        return max(-3, min(3, round(news_score, 2))), result


# 全局单例
_analyzer = None

def get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = NewsSentimentAnalyzer()
    return _analyzer

def get_news_score(code, days=3):
    """便捷函数：获取个股新闻评分"""
    try:
        analyzer = get_analyzer()
        score, detail = analyzer.get_news_score_for_v21(code, days)
        return score, detail
    except Exception as e:
        print(f"新闻评分失败 {code}: {e}")
        return 0.0, {'error': str(e)}


if __name__ == '__main__':
    # 测试
    test_codes = ['600519', '000001', '002230']
    for code in test_codes:
        score, detail = get_news_score(code)
        print(f"{code}: news_score={score} sentiment={detail.get('sentiment')} risk={detail.get('risk_score')} "
              f"news={detail.get('news_count')} notices={detail.get('notice_count')}")
