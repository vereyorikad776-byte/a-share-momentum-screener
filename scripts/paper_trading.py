"""
paper_trading.py - 模拟盘引擎 v2.2r

东方系统精华：虚拟券商 + 真实费率 + SSE流式进度

功能：
1. 虚拟资金账户
2. 模拟成交（按收盘价/开盘价）
3. 真实费率模拟（佣金万3，最低5元）
4. 持仓盈亏实时计算
5. 交易记录持久化
6. 与v22评分系统联动
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 数据目录
DATA_DIR = Path("/root/.openclaw/workspace/skills/ifind-momentum-screener/data/paper_trading")
DATA_DIR.mkdir(parents=True, exist_ok=True)

ACCOUNT_FILE = DATA_DIR / "account.json"
HOLDINGS_FILE = DATA_DIR / "holdings.json"
TRADE_HISTORY_FILE = DATA_DIR / "trade_history.jsonl"
DAILY_PNL_FILE = DATA_DIR / "daily_pnl.jsonl"


# ==================== 费率配置 ====================
FEES = {
    "commission_rate": 0.0003,  # 万3
    "min_commission": 5.0,       # 最低5元
    "stamp_duty_rate": 0.001,    # 印花税千1（卖出时收）
    "transfer_fee_rate": 0.00002, # 过户费十万分之二
}


# ==================== 账户管理 ====================

class PaperAccount:
    """模拟盘账户"""
    
    def __init__(self, initial_cash: float = 1000000.0):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.total_value = initial_cash
        self.daily_pnl = []
        
        # 加载已有数据
        self._load()
    
    def _load(self):
        """加载账户数据"""
        if ACCOUNT_FILE.exists():
            with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.initial_cash = data.get("initial_cash", self.initial_cash)
                self.cash = data.get("cash", self.initial_cash)
                self.total_value = data.get("total_value", self.initial_cash)
                self.total_value = data.get("total_value", self.initial_cash)
    
    def _save(self):
        """保存账户数据"""
        with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "cash": self.cash,
                "total_value": self.total_value,
                "last_update": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)
    
    def get_summary(self) -> dict:
        """获取账户摘要"""
        return {
            "initial_cash": self.initial_cash,
            "cash": self.cash,
            "total_value": self.total_value,
            "total_return": (self.total_value - self.initial_cash) / self.initial_cash,
            "available_cash": self.cash,
        }


class PaperHolding:
    """模拟盘持仓"""
    
    def __init__(self):
        self.positions = {}
        self._load()
    
    def _load(self):
        """加载持仓"""
        if HOLDINGS_FILE.exists():
            with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
                self.positions = json.load(f)
    
    def _save(self):
        """保存持仓"""
        with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.positions, f, ensure_ascii=False, indent=2)
    
    def add(self, code: str, name: str, price: float, quantity: int, 
            strategy: str = "波段", reason: str = "") -> dict:
        """添加持仓"""
        if code in self.positions:
            return {"error": f"已持有 {name}", "action": "reject"}
        
        self.positions[code] = {
            "code": code,
            "name": name,
            "buy_price": price,
            "quantity": quantity,
            "strategy": strategy,
            "reason": reason,
            "buy_date": datetime.now().strftime("%Y-%m-%d"),
            "hold_days": 0,
            "current_price": price,
            "highest_price": price,
            "unrealized_pnl": 0,
            "unrealized_pnl_pct": 0,
        }
        self._save()
        return {"success": True, "position": self.positions[code]}
    
    def remove(self, code: str) -> dict:
        """移除持仓"""
        if code in self.positions:
            pos = self.positions.pop(code)
            self._save()
            return {"success": True, "removed": pos}
        return {"error": f"未找到持仓 {code}"}
    
    def update_price(self, code: str, current_price: float):
        """更新持仓价格"""
        if code in self.positions:
            pos = self.positions[code]
            pos["current_price"] = current_price
            pos["unrealized_pnl"] = (current_price - pos["buy_price"]) * pos["quantity"]
            pos["unrealized_pnl_pct"] = (current_price - pos["buy_price"]) / pos["buy_price"]
            
            if current_price > pos.get("highest_price", pos["buy_price"]):
                pos["highest_price"] = current_price
            
            # 更新持有天数
            buy_date = datetime.strptime(pos["buy_date"], "%Y-%m-%d")
            pos["hold_days"] = (datetime.now() - buy_date).days
            
            self._save()
    
    def get_all(self) -> List[dict]:
        """获取所有持仓"""
        return list(self.positions.values())


# ==================== 交易执行 ====================

class PaperTrader:
    """模拟盘交易执行器"""
    
    def __init__(self, account: PaperAccount, holdings: PaperHolding):
        self.account = account
        self.holdings = holdings
    
    def _calc_fees(self, price: float, quantity: int, action: str) -> dict:
        """
        计算交易费用
        
        Args:
            price: 成交价
            quantity: 数量
            action: BUY/SELL
        
        Returns:
            {"commission": ..., "stamp_duty": ..., "transfer_fee": ..., "total": ...}
        """
        amount = price * quantity
        
        # 佣金（买卖都收，最低5元）
        commission = max(amount * FEES["commission_rate"], FEES["min_commission"])
        
        # 印花税（仅卖出）
        stamp_duty = amount * FEES["stamp_duty_rate"] if action == "SELL" else 0
        
        # 过户费（买卖都收）
        transfer_fee = amount * FEES["transfer_fee_rate"]
        
        return {
            "commission": commission,
            "stamp_duty": stamp_duty,
            "transfer_fee": transfer_fee,
            "total": commission + stamp_duty + transfer_fee,
        }
    
    def buy(self, code: str, name: str, price: float, quantity: int,
            strategy: str = "波段", reason: str = "") -> dict:
        """
        模拟买入
        
        Returns:
            {"success": True/False, "position": ..., "fees": ...}
        """
        amount = price * quantity
        fees = self._calc_fees(price, quantity, "BUY")
        total_cost = amount + fees["total"]
        
        # 检查资金
        if total_cost > self.account.cash:
            return {"error": f"资金不足: 需要{total_cost:.2f}, 可用{self.account.cash:.2f}"}
        
        # 扣除资金
        self.account.cash -= total_cost
        
        # 添加持仓
        result = self.holdings.add(code, name, price, quantity, strategy, reason)
        if not result.get("success"):
            # 回滚资金
            self.account.cash += total_cost
            return result
        
        # 记录交易
        self._log_trade("BUY", code, name, price, quantity, fees, reason)
        
        # 保存账户
        self.account._save()
        
        return {
            "success": True,
            "position": result["position"],
            "fees": fees,
            "total_cost": total_cost,
        }
    
    def sell(self, code: str, price: float, quantity: int = None,
             reason: str = "") -> dict:
        """
        模拟卖出
        
        Args:
            code: 股票代码
            price: 卖出价
            quantity: 数量（None=全部）
            reason: 卖出原因
        
        Returns:
            {"success": True/False, "realized_pnl": ..., "fees": ...}
        """
        pos = self.holdings.positions.get(code)
        if not pos:
            return {"error": f"未持有 {code}"}
        
        if quantity is None:
            quantity = pos["quantity"]
        
        if quantity > pos["quantity"]:
            return {"error": f"持仓不足: 持有{pos['quantity']}, 卖出{quantity}"}
        
        amount = price * quantity
        fees = self._calc_fees(price, quantity, "SELL")
        net_amount = amount - fees["total"]
        
        # 计算实现盈亏
        realized_pnl = (price - pos["buy_price"]) * quantity
        
        # 更新资金
        self.account.cash += net_amount
        
        # 更新或移除持仓
        if quantity >= pos["quantity"]:
            self.holdings.remove(code)
        else:
            pos["quantity"] -= quantity
            self.holdings._save()
        
        # 记录交易
        self._log_trade("SELL", code, pos["name"], price, quantity, fees, reason, realized_pnl)
        
        # 保存账户
        self.account._save()
        
        return {
            "success": True,
            "realized_pnl": realized_pnl,
            "fees": fees,
            "net_amount": net_amount,
        }
    
    def _log_trade(self, action: str, code: str, name: str, price: float,
                   quantity: int, fees: dict, reason: str = "",
                   realized_pnl: float = 0):
        """记录交易日志"""
        record = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "code": code,
            "name": name,
            "price": price,
            "quantity": quantity,
            "amount": price * quantity,
            "fees": fees,
            "reason": reason,
            "realized_pnl": realized_pnl,
        }
        with open(TRADE_HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ==================== 每日结算 ====================

def daily_settlement(prices: Dict[str, float]) -> dict:
    """
    每日收盘结算
    
    Args:
        prices: {code: current_price}
    
    Returns:
        {"date", "total_value", "cash", "unrealized_pnl", "positions": [...]}
    """
    account = PaperAccount()
    holdings = PaperHolding()
    
    # 更新持仓价格
    total_unrealized = 0
    for code, price in prices.items():
        holdings.update_price(code, price)
    
    # 计算总市值
    positions = holdings.get_all()
    position_value = sum(p["current_price"] * p["quantity"] for p in positions)
    total_value = account.cash + position_value
    account.total_value = total_value
    account._save()
    
    # 记录每日盈亏
    record = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "cash": account.cash,
        "position_value": position_value,
        "total_value": total_value,
        "total_return": (total_value - account.initial_cash) / account.initial_cash,
        "position_count": len(positions),
    }
    with open(DAILY_PNL_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    
    return record


# ==================== 便捷函数 ====================

def get_paper_trading_summary() -> str:
    """获取模拟盘摘要"""
    account = PaperAccount()
    holdings = PaperHolding()
    positions = holdings.get_all()
    
    summary = f"""
=== 模拟盘账户 ===
初始资金: {account.initial_cash:,.2f}
可用现金: {account.cash:,.2f}
总市值:   {account.total_value:,.2f}
总收益率: {(account.total_value - account.initial_cash) / account.initial_cash * 100:+.2f}%

持仓 ({len(positions)}只):
"""
    for p in positions:
        pnl_pct = p.get("unrealized_pnl_pct", 0) * 100
        emoji = "🟢" if pnl_pct >= 0 else "🔴"
        summary += f"  {emoji} {p['name']}({p['code']}) | 成本{p['buy_price']:.2f} | 现价{p['current_price']:.2f} | 盈亏{pnl_pct:+.1f}% | {p['hold_days']}天\n"
    
    return summary


def reset_paper_account():
    """重置模拟盘"""
    for f in [ACCOUNT_FILE, HOLDINGS_FILE, TRADE_HISTORY_FILE, DAILY_PNL_FILE]:
        if f.exists():
            f.unlink()
    print("✅ 模拟盘已重置")


if __name__ == "__main__":
    print(get_paper_trading_summary())
