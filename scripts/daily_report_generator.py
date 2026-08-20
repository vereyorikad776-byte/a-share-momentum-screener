#!/usr/bin/env python3
"""
daily_report_generator.py - 每日选股报告生成器

功能：
- 运行完整选股扫描
- 生成 Markdown 报告
- 自动 push 到 GitHub 仓库
- 保留历史记录，支持对比

用法：
    python3 daily_report_generator.py [--push]

报告格式：YYYY-MM-DD-report.md
"""

import argparse
import json
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# 路径设置
SCRIPT_DIR = Path(__file__).parent
REPO_ROOT = SCRIPT_DIR.parent
REPORTS_DIR = REPO_ROOT / "reports"
sys.path.insert(0, str(SCRIPT_DIR))

from v22_engine import run_v22_scoring

# 可选导入
try:
    from market_regime import get_position_adjustment
except ImportError:
    get_position_adjustment = None


def generate_daily_report(scan_results: list, market_data: dict = None) -> str:
    """
    生成每日选股报告 Markdown
    
    Args:
        scan_results: 扫描结果列表
        market_data: 市场数据（可选）
    
    Returns:
        Markdown 字符串
    """
    today = datetime.now().strftime("%Y-%m-%d")
    weekday = datetime.now().strftime("%A")
    
    md = f"""# 📊 A股动量选股日报 — {today} ({weekday})

> 生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> 系统版本: v2.2r++

---

## 📈 市场环境

"""
    
    # 五维择时
    try:
        from market_data_feed import run_five_dimension_timing
        position, reasons = run_five_dimension_timing()
        
        position_pct = int(position * 100)
        emoji = "🟢" if position >= 0.5 else "🟡" if position >= 0.3 else "🔴"
        
        md += f"""| 维度 | 状态 |
|:---|:---|
| **建议仓位** | {emoji} {position_pct}% |

**判断依据：**
"""
        for r in reasons[:5]:
            md += f"- {r}\n"
        
    except Exception as e:
        md += f"⚠ 五维择时获取失败: {e}\n"
    
    md += "\n---\n\n## 🎯 选股结果\n\n"
    
    # 分级统计
    s_count = sum(1 for r in scan_results if r.get("tier") == "S")
    a_count = sum(1 for r in scan_results if r.get("tier") == "A")
    b_count = sum(1 for r in scan_results if r.get("tier") == "B")
    x_count = sum(1 for r in scan_results if r.get("tier") == "X")
    
    md += f"""| 级别 | 数量 | 操作建议 |
|:---:|:---:|:---|
| **S级** | {s_count} | 重点关注，考虑买入 |
| **A级** | {a_count} | 观察等待 |
| **B级** | {b_count} | 可纳入观察池 |
| **X级** | {x_count} | 排除或风险警示 |

---

"""
    
    # S级详细
    s_stocks = [r for r in scan_results if r.get("tier") == "S"]
    if s_stocks:
        md += "### ⭐ S级推荐\n\n"
        for i, r in enumerate(s_stocks[:10], 1):
            code = r.get("code", "")
            name = r.get("name", "")
            score = r.get("score", 0)
            action = r.get("action", "")
            reasons = r.get("reasons", [])
            
            md += f"""**{i}. {name} ({code})**

| 指标 | 数值 |
|:---|:---|
| 综合评分 | {score:.1f} |
| 操作建议 | {action} |
| 核心理由 | {', '.join(reasons[:3])} |

"""
    
    # A级简要
    a_stocks = [r for r in scan_results if r.get("tier") == "A"]
    if a_stocks:
        md += "### 🔶 A级观察\n\n"
        md += "| 排名 | 代码 | 名称 | 评分 | 操作建议 |\n"
        md += "|:---:|:---:|:---:|:---:|:---|\n"
        for i, r in enumerate(a_stocks[:20], 1):
            md += f"| {i} | {r.get('code','')} | {r.get('name','')} | {r.get('score',0):.1f} | {r.get('action','')} |\n"
        md += "\n"
    
    # 风险提示
    x_stocks = [r for r in scan_results if r.get("tier") == "X"]
    if x_stocks:
        md += "### ⚠️ X级风险\n\n"
        for r in x_stocks[:5]:
            md += f"- **{r.get('name','')}** ({r.get('code','')}): {', '.join(r.get('reasons',[])[:2])}\n"
        md += "\n"
    
    # 交易计划
    md += """---

## 📋 交易计划

"""
    try:
        from trade_manager import generate_trade_plan
        plan = generate_trade_plan(scan_results, available_cash=100000, total_capital=500000)
        
        md += "### 买入计划\n\n"
        if plan.get("buys"):
            for b in plan["buys"][:5]:
                md += f"- **{b['name']}** ({b['code']}): 买入价{b['buy_price']:.2f}, 止损{b['stop_loss']}, 仓位{b.get('position_pct','')}\n"
        else:
            md += "今日无明确买入信号。\n"
        
        md += "\n### 持仓检查\n\n"
        if plan.get("holds"):
            for h in plan["holds"][:5]:
                md += f"- **{h['name']}** ({h['code']}): {h['reason']}\n"
        else:
            md += "无持仓需关注。\n"
            
    except Exception as e:
        md += f"⚠ 交易计划生成失败: {e}\n"
    
    md += """\n---

## 📊 统计摘要

"""
    md += f"""| 指标 | 数值 |
|:---|:---|
| 扫描总数 | {len(scan_results)} |
| S级 | {s_count} |
| A级 | {a_count} |
| B级 | {b_count} |
| X级 | {x_count} |
| 生成时间 | {datetime.now().strftime("%H:%M:%S")} |

---

> 💡 **提示**: 对比历史报告请查看 `reports/` 目录下其他日期文件。
"""
    
    return md


def save_and_push_report(md_content: str, push: bool = False) -> str:
    """
    保存报告并可选 push 到 GitHub
    
    Returns:
        报告文件路径
    """
    REPORTS_DIR.mkdir(exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    report_file = REPORTS_DIR / f"{today}-report.md"
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(md_content)
    
    print(f"✅ 报告已保存: {report_file}")
    
    if push:
        try:
            # git add
            subprocess.run(
                ["git", "add", str(report_file)],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True
            )
            
            # git commit
            subprocess.run(
                ["git", "commit", "-m", f"📊 Daily report: {today}"],
                cwd=REPO_ROOT,
                check=False,  # 可能无变更
                capture_output=True
            )
            
            # git push
            result = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True
            )
            
            print(f"✅ 已 push 到 GitHub")
            
        except subprocess.CalledProcessError as e:
            print(f"⚠️ Push 失败: {e}")
            print(f"   stderr: {e.stderr if hasattr(e, 'stderr') else 'N/A'}")
    
    return str(report_file)


def main():
    parser = argparse.ArgumentParser(description="每日选股报告生成器")
    parser.add_argument("--push", action="store_true", help="自动 push 到 GitHub")
    parser.add_argument("--mock-data", action="store_true", help="使用模拟数据测试")
    args = parser.parse_args()
    
    print(f"📊 生成每日选股报告...")
    
    if args.mock_data:
        # 模拟数据测试
        mock_results = [
            {"code": "600519", "name": "贵州茅台", "tier": "S", "score": 8.5, "action": "买", "reasons": ["MACD>0", "突破新高"]},
            {"code": "000858", "name": "五粮液", "tier": "A", "score": 7.2, "action": "等回调", "reasons": ["均线多头排列"]},
            {"code": "600000", "name": "浦发银行", "tier": "B", "score": 5.5, "action": "观察", "reasons": ["底部放量"]},
            {"code": "000001", "name": "平安银行", "tier": "X", "score": 3.2, "action": "不买", "reasons": ["冲高回落", "消息面利空"]},
        ]
        md = generate_daily_report(mock_results)
    else:
        # 这里应该调用实际扫描逻辑
        # 简化版：读取现有结果或提示
        print("⚠ 实际扫描需要完整数据，当前使用演示模式")
        print("   使用 --mock-data 查看报告格式")
        mock_results = []
        md = generate_daily_report(mock_results)
    
    report_path = save_and_push_report(md, push=args.push)
    
    print(f"\n📄 报告路径: {report_path}")
    if args.push:
        print("🔗 GitHub: https://github.com/vereyorikad776-byte/a-share-momentum-screener/tree/main/reports")


if __name__ == "__main__":
    main()
