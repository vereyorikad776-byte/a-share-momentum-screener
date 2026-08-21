#!/usr/bin/env python3
"""
run_v22_ultimate.py - A股动量选股系统 终极版 v2.2r

一站式入口：选股 → 评分 → 风控 → 交易计划 → 反馈学习

用法:
  python3 run_v22_ultimate.py --mode single --code 600519 --name 贵州茅台
  python3 run_v22_ultimate.py --mode scan              # 盘后全量扫描
  python3 run_v22_ultimate.py --mode check             # 检查持仓风控
  python3 run_v22_ultimate.py --mode report            # 生成学习报告
  python3 run_v22_ultimate.py --mode backtest --days 20 # 回测最近20天

Author: 选股系统 v2.2r
Date: 2026-08-20
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

# 添加脚本目录到路径
SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# 导入各模块
from v22_engine import run_v22_scoring, run_v22_scoring_enhanced, format_v22_enhanced_report, scan_5day_sectors, merge_hot_sectors
from feedback_learning import (
    log_after_scoring, calc_hit_rate, update_pattern_stats,
    get_learning_report, cleanup_old_data
)
from trade_manager import (
    load_positions, check_all_positions, generate_trade_plan,
    generate_conditional_orders, get_position_summary, daily_review
)
from paper_trading import (
    PaperAccount, PaperHolding, PaperTrader,
    get_paper_trading_summary, reset_paper_account, daily_settlement
)
from market_data_feed import run_five_dimension_timing

# 版本信息
VERSION = "v2.2r"
BUILD_DATE = "2026-08-20"


def print_banner():
    """打印启动横幅"""
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║     A股动量选股系统 终极版 {VERSION}                          ║
║     先排除 → 再评分 → 给明确操作建议                         ║
║     Build: {BUILD_DATE}                                       ║
╚══════════════════════════════════════════════════════════════╝
""")


def run_single_stock(code: str, name: str, data: dict = None) -> dict:
    """
    单票评分
    
    Args:
        code: 股票代码
        name: 股票名称
        data: 实时数据字典（可选，不传则尝试从DuckDB获取）
    
    Returns:
        完整评分结果
    """
    print(f"\n{'='*60}")
    print(f"单票评分: {name} ({code})")
    print(f"{'='*60}")
    
    # 如果没有提供数据，尝试从DuckDB获取
    if data is None:
        from data_cache import StockDataCache
        from data_preparation import prepare_scoring_data, enrich_with_tencent
        from datetime import datetime, timedelta
        cache = StockDataCache()
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
        print(f"📥 {code} 本地无缓存，从 akshare 拉取 {start_date}~{end_date} ...")
        df = cache.get_kline(code, start_date=start_date, end_date=end_date)
        if df is not None and len(df) > 0:
            data = prepare_scoring_data(code, name, df)
            if data:
                data = enrich_with_tencent(data)
                print(f"✅ 数据准备完成: {len(df)}根K线 | MACD={data['macd']:.3f} RSI={data['rsi6']:.1f} KDJ_K={data['kdj_k']:.1f} 量比={data['volume_ratio']:.2f}")
            else:
                print(f"⚠ 数据不足（需≥30根K线），无法评分")
                return None
        else:
            print(f"⚠ 无法获取 {code} 的历史数据，请提供实时数据")
            return None
    
    # 运行评分 — v2.2r++ 增强版（自动调用Iwencai SkillHub）
    result = run_v22_scoring_enhanced(data, stock_name=name, stock_code=code)
    
    # 打印增强版报告
    print(format_v22_enhanced_report(result, stock_name=name, stock_code=code))
    
    # 记录日志
    log_after_scoring(code, name, result)
    
    return result


def run_full_scan() -> List[dict]:
    """
    盘后全量扫描
    
    Returns:
        所有候选票的评分结果
    """
    print(f"\n{'='*60}")
    print(f"盘后全量扫描")
    print(f"{'='*60}")
    
    # 读取六池
    from data_cache import DuckDBCache
    cache = DuckDBCache()
    pools = cache.read_pools()
    
    if not pools:
        print("⚠ 六池为空，请先更新池子数据")
        return []
    
    print(f"六池共 {len(pools)} 只候选票")
    
    # 获取历史K线数据
    results = []
    for i, stock in enumerate(pools):
        code = stock.get('code', '')
        name = stock.get('name', '')
        
        if not code:
            continue
        
        print(f"\n[{i+1}/{len(pools)}] {name} ({code})")
        
        # 获取K线
        df = cache.get_kline(code)
        if df is None or len(df) < 20:
            print(f"  ⚠ K线数据不足，跳过")
            continue
        
        # 构建数据
        latest = df.iloc[-1]
        data = {
            'code': code,
            'name': name,
            'close': float(latest['close']),
            'open': float(latest['open']),
            'high': float(latest['high']),
            'low': float(latest['low']),
            'volume': float(latest['volume']),
            'amount': float(latest.get('amount', 0)),
            'prev_close': float(df.iloc[-2]['close']) if len(df) > 1 else float(latest['close']),
            'ma5': float(df['close'].rolling(5).mean().iloc[-1]),
            'ma10': float(df['close'].rolling(10).mean().iloc[-1]),
            'ma20': float(df['close'].rolling(20).mean().iloc[-1]),
            'change_pct': (float(latest['close']) - float(df.iloc[-2]['close'])) / float(df.iloc[-2]['close']) if len(df) > 1 else 0,
        }
        
        # 运行评分
        result = run_v22_scoring(data)
        results.append(result)
        
        # 打印简要结果
        action_emoji = {"买": "🟢", "等": "🟡", "不买": "🔴"}
        emoji = action_emoji.get(result['action'], "⚪")
        print(f"  {emoji} {result['tier']}级 | {result['action']} | 综合分{result['final_score']:.3f}")
        
        # 记录日志
        log_after_scoring(code, name, result)
    
    # 保存结果
    output_file = f"/tmp/v22_scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"扫描完成！共 {len(results)} 只")
    print(f"结果保存至: {output_file}")
    
    # 输出Top 10
    results.sort(key=lambda x: x.get('final_score', 0), reverse=True)
    print(f"\n【Top 10】")
    for i, r in enumerate(results[:10]):
        print(f"  {i+1}. {r['name']}({r['code']}) | {r['tier']}级 | {r['action']} | {r['final_score']:.3f}")
    
    # 清理旧数据
    cleanup_result = cleanup_old_data(days=5)
    print(f"\n数据清理: 清理{cleanup_result['cleaned']}条，保留{cleanup_result['remaining']}条")
    
    return results


def run_position_check() -> None:
    """检查持仓风控"""
    print(f"\n{'='*60}")
    print(f"持仓风控检查")
    print(f"{'='*60}")
    
    # 打印持仓摘要
    print(get_position_summary())
    
    # 获取当前价格（这里需要从外部传入，简化处理）
    positions = load_positions()
    if not positions:
        print("\n当前无持仓")
        return
    
    print(f"\n【风控检查】")
    print("⚠ 请提供当前价格以进行完整风控检查")
    print("用法: 在positions.json中更新current_price字段")
    print(f"  文件路径: {Path(__file__).parent.parent}/data/trade/positions.json")


def run_trade_plan(results: List[dict] = None, 
                   available_cash: float = 100000,
                   total_capital: float = 500000) -> dict:
    """
    生成交易计划
    
    Args:
        results: 评分结果列表
        available_cash: 可用现金
        total_capital: 总资金
    
    Returns:
        交易计划
    """
    print(f"\n{'='*60}")
    print(f"生成交易计划")
    print(f"{'='*60}")
    
    if results is None:
        # 尝试加载最近的扫描结果
        import glob
        scan_files = sorted(glob.glob("/tmp/v22_scan_*.json"), reverse=True)
        if scan_files:
            with open(scan_files[0], "r", encoding="utf-8") as f:
                results = json.load(f)
        else:
            print("⚠ 未找到扫描结果，请先运行扫描")
            return {}
    
    plan = generate_trade_plan(results, available_cash, total_capital)
    
    print(f"\n【卖出计划】{len(plan['sells'])}只")
    for s in plan['sells']:
        print(f"  🔴 {s['name']}({s['code']}) - {s['reason']}")
    
    print(f"\n【持有计划】{len(plan['holds'])}只")
    for h in plan['holds']:
        print(f"  🟢 {h['name']}({h['code']}) - {h['reason']}")
    
    print(f"\n【买入计划】{len(plan['buys'])}只")
    for b in plan['buys']:
        print(f"  🟢 {b['name']}({b['code']})")
        print(f"      买入价: {b['buy_price']:.2f} | 数量: {b['quantity']}股")
        print(f"      止损: {b['stop_loss']} | 策略: {b['strategy']}")
        print(f"      原因: {b['reason']}")
        
        # 生成条件单
        mock_position = {
            "buy_price": b['buy_price'],
            "quantity": b['quantity'],
        }
        orders = generate_conditional_orders(mock_position)
        print(f"      条件单:")
        for o in orders:
            print(f"        {o['type']}: 触发价{o['trigger_price']:.2f} → 委托{o['order_price']:.2f}")
    
    if plan['warnings']:
        print(f"\n【警告】")
        for w in plan['warnings']:
            print(f"  ⚠ {w}")
    
    return plan


def run_learning_report() -> None:
    """生成学习报告"""
    print(f"\n{'='*60}")
    print(f"反馈学习报告")
    print(f"{'='*60}")
    print(get_learning_report())


def run_backtest(days: int = 20) -> None:
    """回测最近N天"""
    print(f"\n{'='*60}")
    print(f"回测最近{days}天")
    print(f"{'='*60}")
    print("⚠ 回测功能需要完整的历史预测数据")
    print("请确保已运行过多次扫描并回填了实际结果")
    
    hit_rate = calc_hit_rate(days=days)
    print(f"\n命中率: {hit_rate['rate']*100:.1f}% ({hit_rate['hit']}/{hit_rate['total']})")
    
    pattern_stats = update_pattern_stats()
    print(f"\n模式效能:")
    for pattern, data in pattern_stats.items():
        print(f"  {pattern}: {data['rate']*100:.1f}% ({data['hit']}/{data['count']})")


def run_iwencai_combo():
    """问财组合拳 — 板块→选股→评分"""
    print(f"\n{'='*60}")
    print(f"问财组合拳选股")
    print(f"{'='*60}")

    from v22_iwencai_bridge import iwencai_combo_screen

    # Step 1: 选板块
    print("\nStep 1: 问财选板块 — 近一周最强板块 TOP3")
    combo = iwencai_combo_screen(
        sector_period="近一周",
        sector_top_n=3,
        stock_query="成交额大于5000万",
        stock_limit=5,
    )

    print(f"\n强势板块:")
    for s in combo["sectors"]:
        print(f"  📈 {s['name']}: {s['change_pct']:+.2f}%")

    # Step 2: 候选票
    candidates = combo["candidates"]
    print(f"\nStep 2: 问财选A股 — 候选票 {len(candidates)}只")

    # Step 3: v22评分
    print(f"\nStep 3: v22增强评分")
    results = []
    for c in candidates[:15]:  # 最多评15只
        name = c["name"]
        code = c["code"]
        sector = c["sector"]
        print(f"\n  [{len(results)+1}] {name}({code}) — {sector}")
        try:
            result = run_single_stock(code, name)
            if result:
                results.append({"code": code, "name": name, "result": result, "sector": sector})
        except Exception as e:
            print(f"    ⚠ 评分失败: {e}")

    # 排序输出
    if results:
        results.sort(key=lambda x: x["result"].get("final_score", 0), reverse=True)
        print(f"\n{'='*60}")
        print(f"问财组合拳 TOP5 推荐")
        print(f"{'='*60}")
        for i, r in enumerate(results[:5], 1):
            res = r["result"]
            # v22_engine.py 返回的是 'tier' 不是 'grade'
            tier = res.get("tier", res.get("grade", "X"))
            score = res.get("final_score", 0)
            action = res.get("action", "观望")
            print(f"  {i}. {r['name']}({r['code']}) — {r['sector']}")
            print(f"     评级: {tier} | 得分: {score:.3f} | 建议: {action}")
    else:
        print("\n⚠ 无有效评分结果")


def main():
    parser = argparse.ArgumentParser(description=f"A股动量选股系统 终极版 {VERSION}")
    parser.add_argument("--mode", choices=["single", "scan", "check", "plan", "report", "backtest", "market", "paper", "iwencai-combo"],
                       default="single", help="运行模式 (single/单票, scan/扫描, check/持仓检查, plan/交易计划, report/学习报告, backtest/回测, market/五维择时, paper/模拟盘, iwencai-combo/问财组合拳)")
    parser.add_argument("--code", help="股票代码（单票模式）")
    parser.add_argument("--name", help="股票名称（单票模式）")
    parser.add_argument("--cash", type=float, default=100000, help="可用现金（计划模式）")
    parser.add_argument("--capital", type=float, default=500000, help="总资金（计划模式）")
    parser.add_argument("--days", type=int, default=20, help="回测天数（回测模式）")
    
    args = parser.parse_args()
    
    print_banner()
    
    if args.mode == "single":
        if not args.code or not args.name:
            print("⚠ 单票模式需要提供 --code 和 --name")
            print("示例: python3 run_v22_ultimate.py --mode single --code 600519 --name 贵州茅台")
            return
        run_single_stock(args.code, args.name)
    
    elif args.mode == "scan":
        results = run_full_scan()
        # 扫描完成后自动生成交易计划
        if results:
            print(f"\n是否生成交易计划? (y/n)")
            # 这里简化处理，自动执行
            run_trade_plan(results, args.cash, args.capital)
    
    elif args.mode == "check":
        run_position_check()
    
    elif args.mode == "plan":
        run_trade_plan(available_cash=args.cash, total_capital=args.capital)
    
    elif args.mode == "report":
        run_learning_report()
    
    elif args.mode == "backtest":
        run_backtest(days=args.days)
    
    elif args.mode == "market":
        run_market_timing()
    
    elif args.mode == "paper":
        run_paper_trade()
    
    elif args.mode == "iwencai-combo":
        run_iwencai_combo()


def run_market_timing():
    """运行五维择时"""
    print(f"\n{'='*60}")
    print(f"五维择时 — 市场环境判断")
    print(f"{'='*60}")
    
    position, reasons = run_five_dimension_timing()
    
    print(f"\n建议仓位: {position*100:.0f}%")
    print(f"\n判断依据:")
    for r in reasons:
        print(f"  • {r}")
    
    # 仓位映射
    if position >= 0.8:
        print(f"\n🟢 市场环境: 强烈看多 → 积极进攻")
    elif position >= 0.5:
        print(f"\n🟡 市场环境: 偏多 → 适度参与")
    elif position >= 0.3:
        print(f"\n🟠 市场环境: 中性 → 谨慎观望")
    else:
        print(f"\n🔴 市场环境: 看空 → 防守为主")


def run_paper_trade(code: str = None, name: str = None, 
                    price: float = None, action: str = "summary"):
    """
    模拟盘操作
    
    Args:
        code: 股票代码
        name: 股票名称
        price: 价格
        action: buy/sell/summary/reset
    """
    print(f"\n{'='*60}")
    print(f"模拟盘")
    print(f"{'='*60}")
    
    if action == "summary":
        print(get_paper_trading_summary())
    
    elif action == "reset":
        reset_paper_account()
    
    elif action == "buy" and code and name and price:
        account = PaperAccount()
        holdings = PaperHolding()
        trader = PaperTrader(account, holdings)
        
        # 计算可买数量（单票20%仓位）
        max_value = account.total_value * 0.20
        quantity = int(max_value / price / 100) * 100
        
        result = trader.buy(code, name, price, quantity, "波段", "模拟盘测试")
        if result.get("success"):
            print(f"✅ 买入成功: {name} {quantity}股 @ {price:.2f}")
            print(f"   费用: {result['fees']['total']:.2f}元")
        else:
            print(f"❌ 买入失败: {result.get('error')}")
    
    elif action == "sell" and code and price:
        account = PaperAccount()
        holdings = PaperHolding()
        trader = PaperTrader(account, holdings)
        
        result = trader.sell(code, price, reason="模拟盘卖出")
        if result.get("success"):
            print(f"✅ 卖出成功: {code} @ {price:.2f}")
            print(f"   实现盈亏: {result['realized_pnl']:.2f}元")
        else:
            print(f"❌ 卖出失败: {result.get('error')}")
    
    elif action == "settle":
        # 每日结算（需要传入价格字典）
        print("请提供持仓价格字典进行结算")
        print("用法: daily_settlement({'600519': 1600.0, '000858': 150.0})")


if __name__ == "__main__":
    main()
