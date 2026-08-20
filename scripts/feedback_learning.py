"""
feedback_learning.py - 反馈迭代学习系统 v2.2r

功能：
1. 预测日志记录
2. 次日结果回填
3. 命中率统计
4. 模式效能分析
5. 用户否决学习
6. 数据自动清理（保留最近5个交易日）
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# 数据目录
DATA_DIR = Path("/root/.openclaw/workspace/skills/ifind-momentum-screener/data/feedback")
DATA_DIR.mkdir(parents=True, exist_ok=True)

PREDICTION_LOG = DATA_DIR / "predictions.jsonl"
PATTERN_STATS = DATA_DIR / "pattern_stats.json"
HIT_RATE_LOG = DATA_DIR / "hit_rate.json"
USER_OVERRIDES = DATA_DIR / "user_overrides.jsonl"


def log_prediction(prediction: dict) -> None:
    """
    记录一次预测日志
    
    prediction = {
        "timestamp": "2026-08-20T14:30:00",
        "code": "600519",
        "name": "贵州茅台",
        "predicted_tier": "A",
        "predicted_score": 0.452,
        "overnight_prob": 58.3,
        "strategy_type": "适合波段",
        "pattern": "突破",
        "action": "等",
        "buy_price": "≤1685.00",
        "stop_loss": "MA20(1620.00)",
        "actual_next_day_change": None,  # 次日回填
        "hit": None,                     # true/false
        "user_override": False           # 用户是否否决
    }
    """
    prediction["log_time"] = datetime.now().isoformat()
    
    with open(PREDICTION_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(prediction, ensure_ascii=False) + "\n")


def fill_actual_result(code: str, trade_date: str, actual_change: float) -> bool:
    """
    次日回填实际结果
    
    Args:
        code: 股票代码
        trade_date: 预测日期 (YYYY-MM-DD)
        actual_change: 次日涨跌幅 (小数, 如 0.025 表示+2.5%)
    
    Returns:
        是否找到并更新了记录
    """
    if not PREDICTION_LOG.exists():
        return False
    
    updated = False
    lines = []
    
    with open(PREDICTION_LOG, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                # 匹配同一只票+同日期的预测
                if record.get("code") == code and trade_date in record.get("timestamp", ""):
                    record["actual_next_day_change"] = actual_change
                    record["hit"] = actual_change > 0  # 正收益=命中
                    record["fill_time"] = datetime.now().isoformat()
                    updated = True
                lines.append(record)
            except:
                continue
    
    if updated:
        with open(PREDICTION_LOG, "w", encoding="utf-8") as f:
            for record in lines:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    return updated


def calc_hit_rate(days: int = 20) -> dict:
    """
    计算最近N天的命中率统计
    
    Returns:
        {
            "total": 50,
            "hit": 32,
            "miss": 18,
            "rate": 0.64,
            "by_tier": {"S": {...}, "A": {...}, "B": {...}, "X": {...}},
            "by_pattern": {"突破": {...}, "回调再起": {...}}
        }
    """
    if not PREDICTION_LOG.exists():
        return {"total": 0, "hit": 0, "miss": 0, "rate": 0}
    
    cutoff = datetime.now() - timedelta(days=days)
    
    total = 0
    hit = 0
    miss = 0
    by_tier = {}
    by_pattern = {}
    
    with open(PREDICTION_LOG, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                log_time = datetime.fromisoformat(record.get("log_time", "").replace("Z", "+00:00"))
                if log_time < cutoff:
                    continue
                
                if record.get("hit") is None:
                    continue  # 还未回填
                
                total += 1
                if record["hit"]:
                    hit += 1
                else:
                    miss += 1
                
                # 按tier统计
                tier = record.get("predicted_tier", "unknown")
                if tier not in by_tier:
                    by_tier[tier] = {"total": 0, "hit": 0}
                by_tier[tier]["total"] += 1
                if record["hit"]:
                    by_tier[tier]["hit"] += 1
                
                # 按pattern统计
                pattern = record.get("pattern", "无模式")
                if pattern not in by_pattern:
                    by_pattern[pattern] = {"total": 0, "hit": 0, "avg_return": 0}
                by_pattern[pattern]["total"] += 1
                if record["hit"]:
                    by_pattern[pattern]["hit"] += 1
                
            except:
                continue
    
    # 计算比率
    rate = hit / total if total > 0 else 0
    for tier in by_tier:
        t = by_tier[tier]["total"]
        h = by_tier[tier]["hit"]
        by_tier[tier]["rate"] = h / t if t > 0 else 0
    
    for pattern in by_pattern:
        t = by_pattern[pattern]["total"]
        h = by_pattern[pattern]["hit"]
        by_pattern[pattern]["rate"] = h / t if t > 0 else 0
    
    result = {
        "period_days": days,
        "total": total,
        "hit": hit,
        "miss": miss,
        "rate": round(rate, 3),
        "by_tier": by_tier,
        "by_pattern": by_pattern,
    }
    
    # 保存命中率统计
    with open(HIT_RATE_LOG, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result


def update_pattern_stats() -> dict:
    """
    更新模式效能统计
    
    Returns:
        {
            "突破": {"count": 50, "hit": 38, "rate": 0.76, "avg_return": 0.025},
            "回调再起": {"count": 30, "hit": 18, "rate": 0.60, "avg_return": 0.015}
        }
    """
    if not PREDICTION_LOG.exists():
        return {}
    
    stats = {}
    
    with open(PREDICTION_LOG, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                if record.get("hit") is None:
                    continue
                
                pattern = record.get("pattern", "无模式")
                if pattern not in stats:
                    stats[pattern] = {"count": 0, "hit": 0, "total_return": 0}
                
                stats[pattern]["count"] += 1
                if record["hit"]:
                    stats[pattern]["hit"] += 1
                
                actual = record.get("actual_next_day_change", 0)
                if actual is not None:
                    stats[pattern]["total_return"] += actual
                
            except:
                continue
    
    # 计算比率
    for pattern in stats:
        s = stats[pattern]
        s["rate"] = round(s["hit"] / s["count"], 3) if s["count"] > 0 else 0
        s["avg_return"] = round(s["total_return"] / s["count"], 4) if s["count"] > 0 else 0
        del s["total_return"]
    
    # 保存
    with open(PATTERN_STATS, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    return stats


def log_user_override(code: str, reason: str) -> None:
    """
    记录用户手动否决的推荐
    
    Args:
        code: 股票代码
        reason: 用户否决的原因
    """
    record = {
        "timestamp": datetime.now().isoformat(),
        "code": code,
        "reason": reason,
    }
    
    with open(USER_OVERRIDES, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    # 同时更新对应预测记录的user_override字段
    if PREDICTION_LOG.exists():
        lines = []
        with open(PREDICTION_LOG, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    pred = json.loads(line.strip())
                    if pred.get("code") == code:
                        pred["user_override"] = True
                        pred["override_reason"] = reason
                    lines.append(pred)
                except:
                    continue
        
        with open(PREDICTION_LOG, "w", encoding="utf-8") as f:
            for pred in lines:
                f.write(json.dumps(pred, ensure_ascii=False) + "\n")


def analyze_user_overrides() -> dict:
    """
    分析用户否决的共性特征
    
    Returns:
        {
            "total_overrides": 10,
            "common_reasons": {"概念不实": 3, "涨幅过高": 2, ...},
            "suggestion": "建议提高概念验证权重，增加涨幅限制"
        }
    """
    if not USER_OVERRIDES.exists():
        return {"total_overrides": 0, "common_reasons": {}, "suggestion": ""}
    
    reasons = {}
    total = 0
    
    with open(USER_OVERRIDES, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line.strip())
                reason = record.get("reason", "未知")
                reasons[reason] = reasons.get(reason, 0) + 1
                total += 1
            except:
                continue
    
    # 生成建议
    suggestion = ""
    if "概念" in str(reasons):
        suggestion += "建议加强概念真实性验证；"
    if "涨幅" in str(reasons):
        suggestion += "建议收紧涨幅限制；"
    if "追高" in str(reasons):
        suggestion += "建议增加追高保护机制；"
    
    return {
        "total_overrides": total,
        "common_reasons": dict(sorted(reasons.items(), key=lambda x: -x[1])),
        "suggestion": suggestion or "暂无明确建议"
    }


def cleanup_old_data(days: int = 5) -> dict:
    """
    清理超期数据，只保留最近N个交易日
    
    Args:
        days: 保留天数（默认5个交易日）
    
    Returns:
        {"cleaned": 123, "remaining": 45}
    """
    cutoff = datetime.now() - timedelta(days=days)
    cleaned = 0
    remaining = 0
    
    # 清理预测日志
    if PREDICTION_LOG.exists():
        lines = []
        with open(PREDICTION_LOG, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    log_time = datetime.fromisoformat(record.get("log_time", "").replace("Z", "+00:00"))
                    if log_time >= cutoff:
                        lines.append(record)
                        remaining += 1
                    else:
                        cleaned += 1
                except:
                    remaining += 1
                    lines.append(json.loads(line.strip()) if line.strip() else {})
        
        with open(PREDICTION_LOG, "w", encoding="utf-8") as f:
            for record in lines:
                if record:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    # 清理用户否决记录
    if USER_OVERRIDES.exists():
        lines = []
        with open(USER_OVERRIDES, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    ts = datetime.fromisoformat(record.get("timestamp", "").replace("Z", "+00:00"))
                    if ts >= cutoff:
                        lines.append(record)
                except:
                    pass
        
        with open(USER_OVERRIDES, "w", encoding="utf-8") as f:
            for record in lines:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    return {"cleaned": cleaned, "remaining": remaining, "cutoff": cutoff.isoformat()}


def get_learning_report() -> str:
    """
    生成学习报告
    """
    hit_rate = calc_hit_rate(days=20)
    pattern_stats = update_pattern_stats()
    overrides = analyze_user_overrides()
    
    report = f"""
=== 反馈学习报告 ===
统计周期: 最近{hit_rate.get('period_days', 20)}个交易日

【命中率统计】
总预测: {hit_rate['total']} | 命中: {hit_rate['hit']} | 未命中: {hit_rate['miss']}
整体命中率: {hit_rate['rate']*100:.1f}%

【分等级命中率】
"""
    for tier, data in hit_rate.get("by_tier", {}).items():
        report += f"  {tier}级: {data.get('hit',0)}/{data.get('total',0)} = {data.get('rate',0)*100:.1f}%\n"
    
    report += "\n【模式效能】\n"
    for pattern, data in pattern_stats.items():
        report += f"  {pattern}: {data['hit']}/{data['count']} = {data['rate']*100:.1f}%, 平均收益 {data['avg_return']*100:.2f}%\n"
    
    report += f"""
【用户否决分析】
总否决: {overrides['total_overrides']}
常见原因: {dict(list(overrides['common_reasons'].items())[:3])}
建议: {overrides['suggestion']}
"""
    return report


# 便捷函数：评分后自动记录日志
def log_after_scoring(code: str, name: str, result: dict) -> None:
    """
    评分完成后自动记录预测日志
    """
    prediction = {
        "timestamp": datetime.now().isoformat(),
        "code": code,
        "name": name,
        "predicted_tier": result.get("tier", "C"),
        "predicted_score": result.get("final_score", 0),
        "overnight_prob": result.get("overnight_prob", 0),
        "strategy_type": result.get("strategy_type", "观望"),
        "pattern": result.get("pattern_match", "无模式"),
        "action": result.get("action", "等"),
        "buy_price": result.get("buy_price", ""),
        "stop_loss": result.get("stop_loss", ""),
        "actual_next_day_change": None,
        "hit": None,
        "user_override": False,
    }
    log_prediction(prediction)


if __name__ == "__main__":
    # 测试
    print(get_learning_report())
    print("\n清理超期数据:", cleanup_old_data(days=5))
