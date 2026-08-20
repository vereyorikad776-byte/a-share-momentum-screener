#!/usr/bin/env python3
"""
wechat_notifier.py - 微信选股结果推送

功能：
- 将选股结果推送到用户微信
- 支持 Markdown 格式
- 简洁版/详细版两种模式

用法：
    from wechat_notifier import send_screener_result
    send_screener_result(results, mode="brief")
"""

import json
import sys
from datetime import datetime
from typing import List, Dict, Optional


def format_brief_report(results: List[Dict]) -> str:
    """格式化简洁版报告"""
    today = datetime.now().strftime("%m-%d")
    
    s_count = sum(1 for r in results if r.get("tier") == "S")
    a_count = sum(1 for r in results if r.get("tier") == "A")
    
    # 取前5个S级
    s_stocks = [r for r in results if r.get("tier") == "S"][:5]
    
    msg = f"📊 选股日报 {today}\n\n"
    msg += f"S级: {s_count}只 | A级: {a_count}只\n\n"
    
    if s_stocks:
        msg += "⭐ 重点关注:\n"
        for r in s_stocks:
            name = r.get("name", "")
            code = r.get("code", "")
            score = r.get("score", 0)
            action = r.get("action", "")
            msg += f"• {name}({code}) {score:.1f}分 → {action}\n"
    else:
        msg += "今日无S级推荐\n"
    
    msg += f"\n[查看完整报告](https://github.com/vereyorikad776-byte/a-share-momentum-screener/tree/main/reports)"
    
    return msg


def format_detailed_report(results: List[Dict]) -> str:
    """格式化详细版报告"""
    today = datetime.now().strftime("%m-%d")
    
    msg = f"📊 A股动量选股日报 — {today}\n"
    msg += "=" * 30 + "\n\n"
    
    # S级详细
    s_stocks = [r for r in results if r.get("tier") == "S"]
    if s_stocks:
        msg += f"【⭐ S级推荐】共{s_count}只\n\n"
        for i, r in enumerate(s_stocks[:3], 1):
            msg += format_stock_detail(r, i)
            msg += "\n"
    
    # A级简要
    a_stocks = [r for r in results if r.get("tier") == "A"]
    if a_stocks:
        msg += f"【🔶 A级观察】共{len(a_stocks)}只\n"
        for r in a_stocks[:5]:
            msg += f"• {r.get('name','')}({r.get('code','')}) {r.get('score',0):.1f}分\n"
        msg += "\n"
    
    # 市场判断
    try:
        from market_data_feed import run_five_dimension_timing
        position, reasons = run_five_dimension_timing()
        msg += f"【📈 市场环境】建议仓位 {int(position*100)}%\n"
        for r in reasons[:3]:
            msg += f"• {r}\n"
    except:
        pass
    
    msg += f"\n[查看完整报告→](https://github.com/vereyorikad776-byte/a-share-momentum-screener/tree/main/reports)"
    
    return msg


def format_stock_detail(r: Dict, rank: int) -> str:
    """格式化单只股票详情"""
    msg = f"{rank}. {r.get('name','')} ({r.get('code','')})\n"
    msg += f"   评分: {r.get('score',0):.1f} | 操作: {r.get('action','')}\n"
    
    reasons = r.get("reasons", [])
    if reasons:
        msg += f"   理由: {', '.join(reasons[:3])}\n"
    
    return msg


def send_screener_result(
    results: List[Dict],
    mode: str = "brief",
    channel: str = "stdout"
) -> str:
    """
    发送选股结果
    
    Args:
        results: 选股结果列表
        mode: brief(简洁) / detailed(详细)
        channel: stdout(打印) / wechat(微信推送)
    
    Returns:
        格式化后的消息
    """
    
    if mode == "brief":
        msg = format_brief_report(results)
    else:
        msg = format_detailed_report(results)
    
    if channel == "stdout":
        print(msg)
    elif channel == "wechat":
        # 这里可以接入微信推送API
        # 目前先打印，后续可以接入企业微信/飞书等
        print("[微信推送模式]")
        print(msg)
    
    return msg


# 测试
if __name__ == "__main__":
    mock_results = [
        {"code": "600519", "name": "贵州茅台", "tier": "S", "score": 8.5, "action": "买", "reasons": ["MACD>0", "突破新高"]},
        {"code": "000858", "name": "五粮液", "tier": "A", "score": 7.2, "action": "等回调", "reasons": ["均线多头"]},
        {"code": "600000", "name": "浦发银行", "tier": "B", "score": 5.5, "action": "观察", "reasons": ["底部放量"]},
    ]
    
    print("=== 简洁版 ===")
    send_screener_result(mock_results, mode="brief")
    
    print("\n=== 详细版 ===")
    send_screener_result(mock_results, mode="detailed")
