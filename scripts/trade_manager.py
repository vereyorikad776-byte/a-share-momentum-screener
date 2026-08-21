"""
trade_manager.py - 交易执行与风控系统 v2.2r

功能：
1. 生成交易计划（买入/持有/观望/卖出）
2. 风控检查（止损/止盈/仓位/冻结）
3. 条件单参数生成（同花顺格式）
4. 持仓管理
5. 每日盘后复盘
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 数据目录
DATA_DIR = Path("/root/.openclaw/workspace/skills/ifind-momentum-screener/data/trade")
DATA_DIR.mkdir(parents=True, exist_ok=True)

POSITIONS_FILE = DATA_DIR / "positions.json"
TRADE_LOG = DATA_DIR / "trade_log.jsonl"
DAILY_REVIEW = DATA_DIR / "daily_review.jsonl"


# ==================== 风控参数 ====================
RISK_CONFIG = {
    "hard_stop_loss": -0.07,           # 硬止损 -7%
    "tech_stop": 0.97,                  # 技术止损: 跌破MA20×0.97
    "max_hold_days": 10,                # 最长持有10天
    "max_positions": 4,                 # 最大持仓4只
    "max_position_per_stock": 0.20,     # 单票最大20%
    "max_total_position": 0.70,         # 总仓位最大70%
    "min_cash_ratio": 0.30,             # 最低现金30%
    "no_trade_after_stop": True,        # 止损当日不开新仓
    "no_average_down": True,            # 禁止摊平
    # 阶梯止盈
    "take_profit": {
        "10pct": {"trigger": 0.10, "retrace": 0.05},
        "15pct": {"trigger": 0.15, "retrace": 0.08},
        "20pct": {"trigger": 0.20, "retrace": 0.10},
    },
    "fixed_take_profit": 0.20,          # 固定止盈20%
}


# ==================== 持仓管理 ====================

def load_positions() -> List[dict]:
    """加载当前持仓"""
    if not POSITIONS_FILE.exists():
        return []
    with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_positions(positions: List[dict]) -> None:
    """保存持仓"""
    with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def add_position(code: str, name: str, buy_price: float, 
                 quantity: int, stop_loss: float, 
                 strategy: str = "波段", reason: str = "") -> dict:
    """
    添加新持仓
    
    Returns:
        持仓记录
    """
    positions = load_positions()
    
    # 检查是否已有持仓
    for p in positions:
        if p["code"] == code:
            return {"error": f"已持有 {name}，不可重复买入", "action": "reject"}
    
    # 检查持仓数量
    if len(positions) >= RISK_CONFIG["max_positions"]:
        return {"error": f"已达最大持仓数{RISK_CONFIG['max_positions']}只，不可新开仓", "action": "reject"}
    
    position = {
        "code": code,
        "name": name,
        "buy_price": buy_price,
        "quantity": quantity,
        "stop_loss": stop_loss,
        "strategy": strategy,  # 过夜/波段
        "reason": reason,
        "buy_date": datetime.now().strftime("%Y-%m-%d"),
        "hold_days": 0,
        "status": "holding",
        "highest_price": buy_price,
        "take_profit_level": 0,  # 0=未到, 1=3%, 2=6%, 3=10%
    }
    
    positions.append(position)
    save_positions(positions)
    
    # 记录交易日志
    log_trade("BUY", code, name, buy_price, quantity, reason)
    
    return {"success": True, "position": position}


def remove_position(code: str, reason: str = "") -> dict:
    """平仓"""
    positions = load_positions()
    removed = None
    new_positions = []
    
    for p in positions:
        if p["code"] == code:
            removed = p
            log_trade("SELL", code, p["name"], 0, p["quantity"], reason)
        else:
            new_positions.append(p)
    
    if removed:
        save_positions(new_positions)
        return {"success": True, "removed": removed}
    
    return {"error": f"未找到持仓 {code}", "action": "not_found"}


def update_position_prices(prices: Dict[str, float]) -> List[dict]:
    """
    更新持仓的当前价格和盈亏
    
    Args:
        prices: {code: current_price}
    
    Returns:
        更新后的持仓列表
    """
    positions = load_positions()
    today = datetime.now().strftime("%Y-%m-%d")
    
    for p in positions:
        code = p["code"]
        if code not in prices:
            continue
        
        current = prices[code]
        p["current_price"] = current
        p["current_change_pct"] = (current - p["buy_price"]) / p["buy_price"]
        
        # 更新最高价格（用于止盈判断）
        if current > p.get("highest_price", p["buy_price"]):
            p["highest_price"] = current
        
        # 计算持有天数
        buy_date = datetime.strptime(p["buy_date"], "%Y-%m-%d")
        p["hold_days"] = (datetime.now() - buy_date).days
    
    save_positions(positions)
    return positions


# ==================== 风控检查 ====================

def check_stop_loss(position: dict) -> Optional[str]:
    """
    检查是否触发止损
    
    Returns:
        触发原因，未触发返回None
    """
    buy = position["buy_price"]
    current = position.get("current_price", buy)
    change = (current - buy) / buy
    
    # 硬止损 -7%
    if change <= RISK_CONFIG["hard_stop_loss"]:
        return f"硬止损触发: 亏损{change*100:.1f}% ≤ -7%"
    
    # 技术止损: 跌破MA20×0.97
    # 这里需要外部传入MA20，简化处理
    
    return None


def check_take_profit(position: dict) -> Optional[str]:
    """
    检查是否触发止盈
    
    Returns:
        触发原因和动作，未触发返回None
    """
    buy = position["buy_price"]
    highest = position.get("highest_price", buy)
    current = position.get("current_price", buy)
    level = position.get("take_profit_level", 0)
    
    if highest <= buy:
        return None
    
    max_gain = (highest - buy) / buy
    current_gain = (current - buy) / buy
    
    # 阶梯止盈检查
    tp_config = RISK_CONFIG["take_profit"]
    
    # 第三档: 浮盈>20%, 回撤10%
    if max_gain >= tp_config["20pct"]["trigger"]:
        if level < 3:
            position["take_profit_level"] = 3
        retrace = highest - current
        if retrace / highest >= tp_config["20pct"]["retrace"]:
            return f"止盈三档: 最高盈利{max_gain*100:.1f}%, 回撤{retrace/highest*100:.1f}%"
    
    # 第二档: 浮盈>15%, 回撤8%
    elif max_gain >= tp_config["15pct"]["trigger"]:
        if level < 2:
            position["take_profit_level"] = 2
        retrace = highest - current
        if retrace / highest >= tp_config["15pct"]["retrace"]:
            return f"止盈二档: 最高盈利{max_gain*100:.1f}%, 回撤{retrace/highest*100:.1f}%"
    
    # 第一档: 浮盈>10%, 回撤5%
    elif max_gain >= tp_config["10pct"]["trigger"]:
        if level < 1:
            position["take_profit_level"] = 1
        retrace = highest - current
        if retrace / highest >= tp_config["10pct"]["retrace"]:
            return f"止盈一档: 最高盈利{max_gain*100:.1f}%, 回撤{retrace/highest*100:.1f}%"
    
    # 固定止盈20%
    if current_gain >= RISK_CONFIG["fixed_take_profit"]:
        return f"固定止盈: 盈利{current_gain*100:.1f}% ≥ 20%"
    
    return None


def check_time_stop(position: dict) -> Optional[str]:
    """检查时间止损"""
    if position.get("hold_days", 0) >= RISK_CONFIG["max_hold_days"]:
        return f"时间止损: 持有{position['hold_days']}天 ≥ {RISK_CONFIG['max_hold_days']}天"
    return None


def check_all_positions(prices: Dict[str, float]) -> List[dict]:
    """
    检查所有持仓，返回需要操作的股票
    
    Returns:
        [{"code", "name", "action": "止损"/"止盈"/"持有", "reason", "current_price", "gain_pct"}]
    """
    update_position_prices(prices)
    positions = load_positions()
    alerts = []
    
    for p in positions:
        code = p["code"]
        name = p["name"]
        current = p.get("current_price", p["buy_price"])
        gain = p.get("current_change_pct", 0)
        
        # 检查止损
        stop_reason = check_stop_loss(p)
        if stop_reason:
            alerts.append({
                "code": code, "name": name,
                "action": "止损", "reason": stop_reason,
                "current_price": current, "gain_pct": gain,
            })
            continue
        
        # 检查止盈
        tp_reason = check_take_profit(p)
        if tp_reason:
            alerts.append({
                "code": code, "name": name,
                "action": "止盈", "reason": tp_reason,
                "current_price": current, "gain_pct": gain,
            })
            continue
        
        # 检查时间止损
        time_reason = check_time_stop(p)
        if time_reason:
            alerts.append({
                "code": code, "name": name,
                "action": "时间止损", "reason": time_reason,
                "current_price": current, "gain_pct": gain,
            })
            continue
        
        # 正常持有
        alerts.append({
            "code": code, "name": name,
            "action": "持有", "reason": "",
            "current_price": current, "gain_pct": gain,
        })
    
    return alerts


# ==================== 交易计划生成 ====================

def generate_trade_plan(scoring_results: List[dict], 
                        available_cash: float,
                        total_capital: float) -> dict:
    """
    根据评分结果生成交易计划
    
    Args:
        scoring_results: v22评分结果列表
        available_cash: 可用现金
        total_capital: 总资金
    
    Returns:
        {
            "buys": [{code, name, buy_price, quantity, stop_loss, reason}],
            "sells": [{code, name, reason}],
            "holds": [{code, name, reason}],
            "warnings": [str],
        }
    """
    positions = load_positions()
    position_codes = {p["code"] for p in positions}
    
    plan = {
        "buys": [],
        "sells": [],
        "holds": [],
        "warnings": [],
    }
    
    # 检查已有持仓的票
    for p in positions:
        code = p["code"]
        # 找到对应的评分结果
        result = next((r for r in scoring_results if r.get("code") == code), None)
        if result:
            tier = result.get("tier", "C")
            if tier == "X":
                plan["sells"].append({
                    "code": code, "name": p["name"],
                    "reason": f"评级降至X级: {result.get('action_reason', '')}",
                })
            else:
                plan["holds"].append({
                    "code": code, "name": p["name"],
                    "reason": f"{tier}级持有",
                })
    
    # 检查新买入机会
    current_positions = len(positions)
    if current_positions >= RISK_CONFIG["max_positions"]:
        plan["warnings"].append(f"已达最大持仓数{RISK_CONFIG['max_positions']}只，不可新开仓")
        return plan
    
    # 计算可用仓位
    current_ratio = sum(p.get("buy_price", 0) * p.get("quantity", 0) 
                        for p in positions) / total_capital if total_capital > 0 else 0
    remaining_ratio = RISK_CONFIG["max_total_position"] - current_ratio
    
    if remaining_ratio <= 0:
        plan["warnings"].append("已达总仓位上限70%，不可新开仓")
        return plan
    
    # 筛选可买入的票
    candidates = []
    for r in scoring_results:
        code = r.get("code")
        if code in position_codes:
            continue  # 已持仓
        if r.get("action") != "买":
            continue  # action不是买
        if r.get("tier") not in ["S", "A"]:
            continue  # 只买S/A级
        candidates.append(r)
    
    # 按评分排序
    candidates.sort(key=lambda x: x.get("final_score", 0), reverse=True)
    
    # 分配仓位
    for r in candidates:
        if len(plan["buys"]) + current_positions >= RISK_CONFIG["max_positions"]:
            break
        
        code = r["code"]
        name = r["name"]
        tier = r["tier"]
        
        # 单票仓位
        if tier == "S":
            position_ratio = 0.20 * RISK_CONFIG["max_position_per_stock"]  # 重仓
        else:  # A
            position_ratio = 0.15 * RISK_CONFIG["max_position_per_stock"]  # 中仓
        
        position_ratio = min(position_ratio, remaining_ratio)
        budget = total_capital * position_ratio
        
        # 计算可买数量（100股整数倍）
        price = r.get("current_price", 0)
        if price <= 0:
            continue
        quantity = int(budget / price / 100) * 100
        if quantity < 100:
            continue
        
        plan["buys"].append({
            "code": code,
            "name": name,
            "buy_price": price,
            "quantity": quantity,
            "stop_loss": r.get("stop_loss", "MA20"),
            "reason": f"{tier}级 + {r.get('action_reason', '')}",
            "strategy": r.get("strategy_type", "波段"),
        })
        
        remaining_ratio -= position_ratio
        if remaining_ratio <= 0:
            break
    
    return plan


# ==================== 条件单参数生成 ====================

def generate_conditional_orders(position: dict) -> List[dict]:
    """
    为持仓生成同花顺条件单参数
    
    Returns:
        [
            {"type": "止盈1", "trigger_price": ..., "order_price": ..., "quantity": ...},
            {"type": "止盈2", ...},
            {"type": "止损", ...},
        ]
    """
    buy = position["buy_price"]
    qty = position["quantity"]
    
    orders = []
    
    # 止盈1: 浮盈3% → 回撤3%
    tp1_trigger = round(buy * 1.03, 2)
    tp1_order = round(tp1_trigger * 0.97, 2)
    orders.append({
        "type": "止盈1(3%)",
        "trigger_price": tp1_trigger,
        "order_price": tp1_order,
        "quantity": qty,
        "condition": f"股价≥{tp1_trigger}后，回撤3%至{tp1_order}触发",
    })
    
    # 止盈2: 浮盈6% → 回撤5%
    tp2_trigger = round(buy * 1.06, 2)
    tp2_order = round(tp2_trigger * 0.95, 2)
    orders.append({
        "type": "止盈2(6%)",
        "trigger_price": tp2_trigger,
        "order_price": tp2_order,
        "quantity": qty,
        "condition": f"股价≥{tp2_trigger}后，回撤5%至{tp2_order}触发",
    })
    
    # 止盈3: 浮盈10% → 回撤8%
    tp3_trigger = round(buy * 1.10, 2)
    tp3_order = round(tp3_trigger * 0.92, 2)
    orders.append({
        "type": "止盈3(10%)",
        "trigger_price": tp3_trigger,
        "order_price": tp3_order,
        "quantity": qty,
        "condition": f"股价≥{tp3_trigger}后，回撤8%至{tp3_order}触发",
    })
    
    # 硬止损: -7%
    sl_price = round(buy * (1 + RISK_CONFIG["hard_stop_loss"]), 2)
    orders.append({
        "type": "硬止损(-7%)",
        "trigger_price": sl_price,
        "order_price": sl_price * 0.99,  # 市价附近
        "quantity": qty,
        "condition": f"股价跌破{buy}×93%={sl_price}触发",
    })
    
    return orders


# ==================== 日志记录 ====================

def log_trade(action: str, code: str, name: str, price: float, 
              quantity: int, reason: str = "") -> None:
    """记录交易日志"""
    record = {
        "timestamp": datetime.now().isoformat(),
        "action": action,  # BUY/SELL
        "code": code,
        "name": name,
        "price": price,
        "quantity": quantity,
        "reason": reason,
    }
    with open(TRADE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def daily_review(date: str = None) -> dict:
    """
    每日盘后复盘
    
    Returns:
        {
            "date": "2026-08-20",
            "positions": [...],
            "alerts": [...],
            "pnl": {"total_cost": ..., "total_value": ..., "gain_pct": ...},
        }
    """
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    
    positions = load_positions()
    
    review = {
        "date": date,
        "positions": positions,
        "alerts": [],
        "pnl": {"total_cost": 0, "total_value": 0, "gain_pct": 0},
    }
    
    total_cost = 0
    total_value = 0
    
    for p in positions:
        cost = p["buy_price"] * p["quantity"]
        value = p.get("current_price", p["buy_price"]) * p["quantity"]
        total_cost += cost
        total_value += value
        
        # 检查是否需要告警
        gain = p.get("current_change_pct", 0)
        if gain <= -0.05:
            review["alerts"].append(f"⚠ {p['name']} 亏损{gain*100:.1f}%，关注是否触发止损")
        elif gain >= 0.10:
            review["alerts"].append(f"🎉 {p['name']} 盈利{gain*100:.1f}%，关注止盈")
    
    review["pnl"]["total_cost"] = round(total_cost, 2)
    review["pnl"]["total_value"] = round(total_value, 2)
    if total_cost > 0:
        review["pnl"]["gain_pct"] = round((total_value - total_cost) / total_cost, 4)
    
    # 保存复盘记录
    with open(DAILY_REVIEW, "a", encoding="utf-8") as f:
        f.write(json.dumps(review, ensure_ascii=False) + "\n")
    
    return review


# ==================== 便捷函数 ====================

def get_position_summary() -> str:
    """获取持仓摘要"""
    positions = load_positions()
    if not positions:
        return "当前无持仓"
    
    summary = "=== 当前持仓 ===\n"
    total_cost = 0
    total_value = 0
    
    for p in positions:
        cost = p["buy_price"] * p["quantity"]
        current = p.get("current_price", p["buy_price"])
        value = current * p["quantity"]
        gain = p.get("current_change_pct", 0)
        days = p.get("hold_days", 0)
        
        summary += f"  {p['name']}({p['code']}) | 成本{p['buy_price']:.2f} | 现价{current:.2f} | 盈亏{gain*100:+.1f}% | 持有{days}天\n"
        total_cost += cost
        total_value += value
    
    if total_cost > 0:
        total_gain = (total_value - total_cost) / total_cost
        summary += f"\n总成本: {total_cost:.2f} | 总市值: {total_value:.2f} | 总盈亏: {total_gain*100:+.1f}%"
    
    return summary


if __name__ == "__main__":
    print(get_position_summary())
