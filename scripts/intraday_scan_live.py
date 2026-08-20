#!/usr/bin/env python3
"""
intraday_scan_live.py - 盘中实时扫描（简化版）

功能：
- 读取自选池/六池候选票
- 用 iFinD 获取实时数据
- v22 简化评分（技术面+情绪面+排除规则）
- 筛选 S/A 级信号
- 输出简洁结果

用法：
    python3 intraday_scan_live.py

输出格式：
    {
        "time": "14:30",
        "signals": [
            {"code": "600519", "name": "贵州茅台", "tier": "S", "score": 8.5, "price": 1500.0, "change_pct": 3.2, "action": "买", "reasons": [...]}
        ]
    }
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from v22_engine import run_v22_scoring
from data_cache import get_cached_klines

# 候选池（简化版：先读本地自选池）
WATCHLIST = [
    # 用户自选 + 近期活跃票
    {"code": "600519", "name": "贵州茅台"},
    {"code": "000858", "name": "五粮液"},
    {"code": "600000", "name": "浦发银行"},
    {"code": "000001", "name": "平安银行"},
    {"code": "002594", "name": "比亚迪"},
    {"code": "300750", "name": "宁德时代"},
]


def scan_live(max_stocks: int = 20) -> dict:
    """
    盘中实时扫描
    
    Returns:
        {"time": str, "signals": list}
    """
    print(f"🔍 盘中扫描开始 {datetime.now().strftime('%H:%M:%S')}")
    
    signals = []
    
    for stock in WATCHLIST[:max_stocks]:
        code = stock["code"]
        name = stock["name"]
        
        try:
            # 获取数据（优先本地缓存，否则跳过）
            df = get_cached_klines(code)
            if df is None or len(df) < 20:
                continue
            
            # 简化评分（只跑核心步骤）
            result = run_v22_scoring(code, name)
            
            tier = result.get("tier", "X")
            score = result.get("score", 0)
            
            # 只保留 S/A 级
            if tier in ["S", "A"] and score >= 6.5:
                signals.append({
                    "code": code,
                    "name": name,
                    "tier": tier,
                    "score": score,
                    "price": result.get("price", 0),
                    "change_pct": result.get("change_pct", 0),
                    "action": result.get("action", ""),
                    "reasons": result.get("reasons", [])[:3]
                })
                print(f"  ✅ {name}({code}) {tier}级 {score:.1f}分 → {result.get('action', '')}")
            
            # 限流保护
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ⚠️ {name}({code}) 扫描失败: {e}")
            continue
    
    # 排序
    signals.sort(key=lambda x: x["score"], reverse=True)
    
    result = {
        "time": datetime.now().strftime("%H:%M"),
        "signals": signals
    }
    
    print(f"🔍 扫描完成，发现 {len(signals)} 个信号")
    return result


def main():
    result = scan_live()
    
    # 输出 JSON
    print("\n=== 扫描结果 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    # 保存到文件
    output_file = SCRIPT_DIR.parent / "data" / f"intraday_{datetime.now().strftime('%H%M')}.json"
    output_file.parent.mkdir(exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 已保存: {output_file}")


if __name__ == "__main__":
    main()
