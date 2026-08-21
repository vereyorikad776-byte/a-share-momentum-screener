#!/usr/bin/env python3
"""
v22_iwencai_bridge.py — v22评分系统 × Iwencai SkillHub 桥接层

把同花顺问财25个官方API技能整合进v22评分系统：
- 消息面增强: news/announcement/report → 情绪/利好利空/覆盖度
- 机构面新增: insresearch/management → 机构关注度/管理层稳定性
- 事件面新增: event → 重大事项/重组/并购
- 基本面增强: finance/industry/business → 财务数据/行业PE/主营业务
- 选股增强: 问财选板块 + 问财选A股 → 热点板块/自然语言筛候选

设计原则:
1. 增强不替代: Iwencai数据作为补充，原有技术面/情绪面/资金面不变
2. 失败降级: Iwencai调用失败 → 返回空数据 → 不影响评分继续
3. 报告详细: 每只票输出"为什么给这个分"的分项理由
"""

import os
import sys
import json
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# ── 自动读取 ~/.bashrc 中的 IWENCAI_API_KEY ──
if not os.environ.get("IWENCAI_API_KEY"):
    try:
        with open(os.path.expanduser("~/.bashrc"), "r") as f:
            for line in f:
                if line.strip().startswith("export IWENCAI_API_KEY="):
                    key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
                    os.environ["IWENCAI_API_KEY"] = key
                    break
    except Exception:
        pass

# 导入enhanced_data_feed中的Iwencai快捷函数
sys.path.insert(0, "/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts")
from enhanced_data_feed import (
    iwencai_news, iwencai_announcement, iwencai_report,
    iwencai_insresearch, iwencai_management, iwencai_event,
    iwencai_finance, iwencai_industry_pe, iwencai_business,
    iwencai_stock_screen, iwencai_sector_ranking,
)


def fetch_iwencai_data(stock_name: str, code: str = "") -> dict:
    """
    为单只股票获取Iwencai全维度数据
    返回: {"news": [...], "announcement": [...], "report": [...],
           "insresearch": [...], "management": [...], "event": [...],
           "finance": {}, "industry_pe": {}, "business": {},
           "_fetch_time": str, "_success": bool}
    """
    result = {
        "news": [], "announcement": [], "report": [],
        "insresearch": [], "management": [], "event": [],
        "finance": {}, "industry_pe": {}, "business": {},
        "_fetch_time": datetime.now().strftime("%Y%m%d %H:%M"),
        "_success": False,
    }
    
    try:
        # ── 消息面 ──
        result["news"] = iwencai_news(stock_name, limit=10)
        result["announcement"] = iwencai_announcement(stock_name, limit=10)
        result["report"] = iwencai_report(stock_name, limit=5)
        
        # ── 机构面 ──
        result["insresearch"] = iwencai_insresearch(stock_name)
        result["management"] = iwencai_management(stock_name)
        
        # ── 事件面 ──
        result["event"] = iwencai_event(stock_name)
        
        # ── 基本面增强 ──
        result["finance"] = iwencai_finance(stock_name)
        result["business"] = iwencai_business(stock_name)
        
        # 行业PE（从finance里取行业名再查）
        industry = result["finance"].get("所属行业", "")
        if industry:
            result["industry_pe"] = iwencai_industry_pe(industry)
        
        result["_success"] = True
    except Exception as e:
        result["_error"] = f"{type(e).__name__}: {e}"
    
    return result


def analyze_news_sentiment(news_list: list) -> Tuple[float, List[str]]:
    """
    分析新闻情绪 — 返回 (情绪得分-1~1, 理由列表)
    简单关键词匹配，后续可接NLP模型
    """
    if not news_list:
        return 0.0, ["无近期新闻"]
    
    positive_keywords = ["利好", "增长", "盈利", "突破", "订单", "合作", "签约",
                         "中标", "扩建", "投产", "获批", "通过", "增持", "回购",
                         "预增", "高分红", "创新", "领先", "第一"]
    negative_keywords = ["利空", "下降", "亏损", "下滑", "减持", "质押", "冻结",
                         "问询", "监管", "处罚", "诉讼", "仲裁", "退市", "风险",
                         "警告", "降薪", "裁员", "停产"]
    
    pos_count = 0
    neg_count = 0
    recent_news = news_list[:5]  # 只看最近5条
    
    for item in recent_news:
        title = item.get("标题", item.get("title", ""))
        content = item.get("内容", item.get("content", ""))
        text = f"{title} {content}"
        
        for kw in positive_keywords:
            if kw in text:
                pos_count += 1
                break
        for kw in negative_keywords:
            if kw in text:
                neg_count += 1
                break
    
    total = len(recent_news)
    if total == 0:
        return 0.0, ["新闻无内容"]
    
    sentiment = (pos_count - neg_count) / total
    reasons = []
    if pos_count > 0:
        reasons.append(f"近{total}条新闻中{pos_count}条含利好关键词")
    if neg_count > 0:
        reasons.append(f"近{total}条新闻中{neg_count}条含利空关键词")
    if pos_count == 0 and neg_count == 0:
        reasons.append(f"近{total}条新闻无明显情绪倾向")
    
    return sentiment, reasons


def analyze_announcement_impact(ann_list: list) -> Tuple[float, List[str]]:
    """
    分析公告影响 — 返回 (影响得分-5~5, 理由列表)
    """
    if not ann_list:
        return 0.0, ["无近期公告"]
    
    # 利好公告类型
    positive_types = ["业绩预告", "业绩预增", "分红", "增持", "回购", "股权激励",
                      "中标", "合同", "合作", "获批", "通过", "投产", "扩建"]
    # 利空公告类型
    negative_types = ["业绩预亏", "减持", "质押", "冻结", "问询", "监管", "处罚",
                      "诉讼", "仲裁", "退市风险", "暂停上市", "终止"]
    
    score = 0.0
    reasons = []
    
    for item in ann_list[:5]:
        title = item.get("标题", item.get("title", ""))
        
        for pt in positive_types:
            if pt in title:
                score += 1.0
                reasons.append(f"利好公告: {title[:20]}...")
                break
        for nt in negative_types:
            if nt in title:
                score -= 2.0  # 利空权重更高
                reasons.append(f"⚠️利空公告: {title[:20]}...")
                break
    
    return max(-5, min(5, score)), reasons[:3]


def analyze_report_coverage(report_list: list) -> Tuple[float, List[str]]:
    """
    分析研报覆盖度 — 返回 (覆盖度得分0~5, 理由列表)
    """
    if not report_list:
        return 0.0, ["无机构研报覆盖"]
    
    count = len(report_list)
    score = min(count * 0.8, 3.0)  # 最多3分
    
    # 检查是否有"买入"或"增持"评级
    ratings = []
    for r in report_list:
        title = r.get("标题", r.get("title", ""))
        if "买入" in title or "增持" in title:
            ratings.append("买入/增持")
        elif "减持" in title or "卖出" in title:
            ratings.append("减持/卖出")
    
    reasons = [f"近{count}份研报覆盖"]
    if ratings:
        buy_count = ratings.count("买入/增持")
        sell_count = ratings.count("减持/卖出")
        if buy_count > 0:
            score += 1.0
            reasons.append(f"{buy_count}份买入/增持评级")
        if sell_count > 0:
            score -= 1.0
            reasons.append(f"⚠️{sell_count}份减持/卖出评级")
    
    return max(0, min(5, score)), reasons


def analyze_institutional_research(ins_list: list) -> Tuple[float, List[str]]:
    """
    分析机构调研 — 返回 (机构面得分0~5, 理由列表)
    """
    if not ins_list:
        return 0.0, ["近6个月无机构调研"]
    
    count = len(ins_list)
    score = min(count * 0.5, 3.0)
    
    # 检查是否有知名机构
    top_institutions = ["高盛", "摩根", "瑞银", "中金", "中信证券", "华泰",
                        "易方达", "华夏", "嘉实", "汇添富"]
    has_top = False
    for item in ins_list:
        inst = item.get("调研机构", item.get("机构", ""))
        for top in top_institutions:
            if top in inst:
                has_top = True
                break
    
    reasons = [f"近6个月{count}次机构调研"]
    if has_top:
        score += 1.5
        reasons.append("含头部机构调研")
    
    return min(5, score), reasons


def analyze_management_stability(mgmt_list: list) -> Tuple[float, List[str]]:
    """
    分析管理层稳定性 — 返回 (稳定性得分-3~3, 理由列表)
    高管离职 = 负面，新任 = 中性
    """
    if not mgmt_list:
        return 1.0, ["近期无管理层变动"]  # 稳定 = 小幅加分
    
    score = 0.0
    reasons = []
    
    for item in mgmt_list[:3]:
        title = item.get("标题", item.get("title", ""))
        if "离职" in title or "辞职" in title or "卸任" in title:
            score -= 1.5
            reasons.append(f"⚠️高管变动: {title[:20]}...")
        elif "聘任" in title or "任命" in title:
            score += 0.3
            reasons.append(f"新任高管: {title[:20]}...")
    
    return max(-3, min(3, score)), reasons


def analyze_event_risk(event_list: list) -> Tuple[float, List[str]]:
    """
    分析事件风险 — 返回 (事件得分-5~5, 理由列表)
    """
    if not event_list:
        return 0.0, ["近期无重大事项"]
    
    score = 0.0
    reasons = []
    
    positive_events = ["重组", "并购", "收购", "战略合作", "股权激励", "定增",
                       "回购", "增持", "中标", "专利", "突破"]
    negative_events = ["诉讼", "仲裁", "处罚", "问询", "监管", "减持", "质押",
                       "冻结", "退市", "暂停", "终止", "违约"]
    
    for item in event_list[:5]:
        title = item.get("标题", item.get("title", ""))
        content = item.get("内容", item.get("content", ""))
        text = f"{title} {content}"
        
        for pe in positive_events:
            if pe in text:
                score += 1.0
                reasons.append(f"利好事件: {title[:20]}...")
                break
        for ne in negative_events:
            if ne in text:
                score -= 2.0
                reasons.append(f"⚠️风险事件: {title[:20]}...")
                break
    
    return max(-5, min(5, score)), reasons[:3]


def analyze_financial_enhance(finance: dict, industry_pe: dict) -> Tuple[float, List[str]]:
    """
    财务数据增强分析 — 返回 (财务增强得分-3~3, 理由列表)
    对比行业PE，判断估值高低
    """
    score = 0.0
    reasons = []
    
    if not finance:
        return 0.0, ["财务数据未获取"]
    
    # 从finance中提取关键指标
    pe = finance.get("市盈率", finance.get("PE", 0))
    pb = finance.get("市净率", finance.get("PB", 0))
    roe = finance.get("ROE", 0)
    
    # 行业PE对比
    industry_pe_val = industry_pe.get("行业平均PE", industry_pe.get("PE", 0))
    if pe and industry_pe_val and industry_pe_val > 0:
        pe_ratio = pe / industry_pe_val
        if pe_ratio < 0.7:
            score += 1.5
            reasons.append(f"PE{pe:.1f}低于行业均值{industry_pe_val:.1f}({pe_ratio:.1%})")
        elif pe_ratio > 1.5:
            score -= 1.0
            reasons.append(f"PE{pe:.1f}高于行业均值{industry_pe_val:.1f}({pe_ratio:.1%})")
    
    # ROE
    if roe:
        if roe > 15:
            score += 1.0
            reasons.append(f"ROE{roe:.1f}%优秀")
        elif roe < 5:
            score -= 0.5
            reasons.append(f"ROE{roe:.1f}%偏低")
    
    return max(-3, min(3, score)), reasons


# ═══════════════════════════════════════════════════════════════
# 主入口: Iwencai增强评分
# ═══════════════════════════════════════════════════════════════

def run_iwencai_enhancement(stock_name: str, code: str = "") -> dict:
    """
    为单只股票运行Iwencai全维度增强分析
    
    返回: {
        "news_score": float,      # -5~5 消息面
        "institutional_score": float,  # 0~5 机构面
        "event_score": float,     # -5~5 事件面
        "finance_enhance": float, # -3~3 财务增强
        "total_iwencai": float,   # 汇总得分
        "details": {              # 分项详情
            "news": {"sentiment": float, "impact": float, "coverage": float, "reasons": [...]},
            "institutional": {"research": float, "management": float, "reasons": [...]},
            "event": {"score": float, "reasons": [...]},
            "finance": {"score": float, "reasons": [...]},
        },
        "raw_data": {...},        # 原始Iwencai数据
        "_fetch_time": str,
    }
    """
    # 1. 获取数据
    raw = fetch_iwencai_data(stock_name, code)
    
    # 2. 分析
    news_sent, news_reasons = analyze_news_sentiment(raw["news"])
    ann_score, ann_reasons = analyze_announcement_impact(raw["announcement"])
    report_score, report_reasons = analyze_report_coverage(raw["report"])
    ins_score, ins_reasons = analyze_institutional_research(raw["insresearch"])
    mgmt_score, mgmt_reasons = analyze_management_stability(raw["management"])
    evt_score, evt_reasons = analyze_event_risk(raw["event"])
    fin_score, fin_reasons = analyze_financial_enhance(raw["finance"], raw["industry_pe"])
    
    # 3. 汇总
    news_total = max(-5, min(5, news_sent * 3 + ann_score * 0.5 + report_score * 0.3))
    institutional_total = max(0, min(5, ins_score + mgmt_score))
    event_total = max(-5, min(5, evt_score))
    finance_total = max(-3, min(3, fin_score))
    
    total = news_total * 0.4 + institutional_total * 0.3 + event_total * 0.2 + finance_total * 0.1
    
    return {
        "news_score": round(news_total, 2),
        "institutional_score": round(institutional_total, 2),
        "event_score": round(event_total, 2),
        "finance_enhance": round(finance_total, 2),
        "total_iwencai": round(total, 2),
        "details": {
            "news": {
                "sentiment": round(news_sent, 2),
                "sentiment_reasons": news_reasons,
                "announcement_score": round(ann_score, 2),
                "announcement_reasons": ann_reasons,
                "report_score": round(report_score, 2),
                "report_reasons": report_reasons,
            },
            "institutional": {
                "research_score": round(ins_score, 2),
                "research_reasons": ins_reasons,
                "management_score": round(mgmt_score, 2),
                "management_reasons": mgmt_reasons,
            },
            "event": {
                "score": round(evt_score, 2),
                "reasons": evt_reasons,
            },
            "finance": {
                "score": round(fin_score, 2),
                "reasons": fin_reasons,
            },
        },
        "raw_data": raw,
        "_fetch_time": raw["_fetch_time"],
    }


# ═══════════════════════════════════════════════════════════════
# 快捷函数: 批量增强
# ═══════════════════════════════════════════════════════════════

def batch_iwencai_enhance(stock_list: List[dict]) -> Dict[str, dict]:
    """
    批量获取Iwencai增强数据
    stock_list: [{"name": "贵州茅台", "code": "600519"}, ...]
    返回: {"600519": {...}, ...}
    """
    results = {}
    for stock in stock_list:
        name = stock.get("name", "")
        code = stock.get("code", "")
        if not name:
            continue
        try:
            results[code or name] = run_iwencai_enhancement(name, code)
        except Exception as e:
            results[code or name] = {
                "error": f"{type(e).__name__}: {e}",
                "total_iwencai": 0.0,
            }
    return results


# ═══════════════════════════════════════════════════════════════
# 问财组合拳: 板块 → 选股 → 评分
# ═══════════════════════════════════════════════════════════════

def iwencai_combo_screen(
    sector_period: str = "近一周",
    sector_top_n: int = 3,
    stock_query: str = None,
    stock_limit: int = 10,
) -> dict:
    """
    问财组合拳 — 三步选股:
    1. 问财选板块: 找出当前最强N个板块 (Iwencai优先，失败则用akshare fallback)
    2. 问财选A股: 在强势板块中自然语言筛候选
    3. 返回候选列表 + 板块信息，供v22评分
    """
    # Step 1: 选板块 — Iwencai优先，失败则用akshare fallback
    sectors = iwencai_sector_ranking(sector_period, limit=sector_top_n * 2)
    
    # Fallback: Iwencai失败时用akshare板块数据
    if not sectors:
        print("  ⚠ Iwencai板块API失效，切换akshare fallback...")
        try:
            import akshare as ak
            # 行业板块
            df = ak.stock_board_industry_name_em()
            if df is not None and len(df) > 0:
                df = df.sort_values("涨跌幅", ascending=False)
                for _, row in df.head(sector_top_n * 2).iterrows():
                    name = row.get("板块名称", "")
                    change = row.get("涨跌幅", 0)
                    if name and change:
                        sectors.append({
                            "指数简称": name,
                            "涨跌幅": change,
                            "指数代码": "",
                        })
        except Exception as e:
            print(f"  ⚠ akshare fallback也失败: {e}")
    
    top_sectors = []
    for s in sectors[:sector_top_n]:
        name = s.get("指数简称", s.get("name", s.get("板块名称", "")))
        change = s.get("涨跌幅", s.get(f"涨跌幅[20260814-20260820]", s.get("change_pct", 0)))
        code = s.get("指数代码", s.get("code", ""))
        if name:
            top_sectors.append({"name": name, "change_pct": change, "code": code})

    # Step 2: 板块内选股
    all_candidates = []
    for sec in top_sectors:
        sec_name = sec["name"]
        # 构造查询: "板块名 + 用户条件" 或默认 "板块名 涨幅大于0"
        if stock_query:
            q = f"{sec_name}板块 {stock_query}"
        else:
            q = f"{sec_name}板块 近5日涨幅大于0"

        stocks = iwencai_stock_screen(q, limit=stock_limit)
        for st in stocks:
            all_candidates.append({
                "name": st.get("股票简称", st.get("name", "")),
                "code": st.get("股票代码", st.get("code", "")).replace(".SH", "").replace(".SZ", ""),
                "sector": sec_name,
                "sector_change": sec["change_pct"],
                "iwencai_raw": st,
            })

    # 去重 (同一只票可能在多个板块)
    seen = set()
    unique = []
    for c in all_candidates:
        key = c["code"]
        if key and key not in seen:
            seen.add(key)
            unique.append(c)

    return {
        "sectors": top_sectors,
        "candidates": unique,
        "meta": {
            "sector_period": sector_period,
            "sector_top_n": sector_top_n,
            "stock_limit_per_sector": stock_limit,
            "total_candidates": len(unique),
        },
    }


# ═══════════════════════════════════════════════════════════════
# 测试
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== Iwencai增强评分测试 ===")
    result = run_iwencai_enhancement("贵州茅台", "600519")
    
    print(f"\n📊 总得分: {result['total_iwencai']}")
    print(f"📰 消息面: {result['news_score']}")
    print(f"🏛️ 机构面: {result['institutional_score']}")
    print(f"⚡ 事件面: {result['event_score']}")
    print(f"💰 财务增强: {result['finance_enhance']}")
    
    print("\n📰 消息详情:")
    for r in result["details"]["news"]["sentiment_reasons"]:
        print(f"  - {r}")
    for r in result["details"]["news"]["announcement_reasons"]:
        print(f"  - {r}")
    for r in result["details"]["news"]["report_reasons"]:
        print(f"  - {r}")
    
    print("\n🏛️ 机构详情:")
    for r in result["details"]["institutional"]["research_reasons"]:
        print(f"  - {r}")
    for r in result["details"]["institutional"]["management_reasons"]:
        print(f"  - {r}")
