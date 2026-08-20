#!/usr/bin/env python3
"""
统一配置系统 — 从 KhQuantFramework 借鉴

把硬编码的配置全部抽出来，支持:
- 默认配置 (default.yaml)
- 策略级覆盖 (strategy/*.yaml)
- 运行时热更新
"""

import os
import json
from typing import Dict, Any, Optional
from copy import deepcopy

# 配置目录
CONFIG_DIR = os.path.join(os.path.dirname(__file__), '..', 'config')
DEFAULT_CONFIG_PATH = os.path.join(CONFIG_DIR, 'default.json')


# ============ 默认配置 ============

DEFAULT_CONFIG = {
    # === 数据源配置 ===
    "data_source": {
        "primary": "baostock",           # 主数据源
        "realtime": "ifind",             # 实时数据源
        "fundamentals": "ifind",         # 基本面数据源
        "news": "ifind",                 # 新闻数据源
        "cache": {
            "enabled": True,
            "storage_dir": None,          # None = 默认路径
            "auto_fetch": True,           # 缺失时自动补充
        },
    },

    # === 池子配置 ===
    "pools": {
        "bottom": {
            "name": "底部放量池",
            "description": "底部放量异动票,等板块确认后升级",
            "max_size": 20,
            "scan_frequency": "daily",
            "priority": 1,                 # 优先级(1=最高)
        },
        "limit_up": {
            "name": "涨停池",
            "description": "昨日涨停 + 回踩后二次启动候选",
            "max_size": 20,
            "scan_frequency": "daily",
            "priority": 2,
        },
        "main_line": {
            "name": "主线池",
            "description": "当前热点板块核心票",
            "max_size": 20,
            "scan_frequency": "daily",
            "priority": 3,
        },
        "strong": {
            "name": "强势池",
            "description": "趋势完好,回踩均线买入",
            "max_size": 20,
            "scan_frequency": "daily",
            "priority": 4,
        },
        "user_pick": {
            "name": "自选池",
            "description": "用户自选股票,手动维护",
            "max_size": 20,
            "scan_frequency": "manual",
            "priority": 5,
        },
    },

    # === 评分引擎配置 ===
    "scoring": {
        "weights": {
            "overnight": 0.35,             # 一夜持股法权重
            "fusion": 0.35,                # 三维融合权重
            "debate": 0.20,                # 多空辩论权重
            "base": 0.10,                  # 基础分
        },
        "tier_thresholds": {
            "S": {"pattern": 2.0, "overnight": 14, "fusion": 11, "require_breakout": True},
            "A": {"pattern": 1.0, "overnight": 10, "fusion": 8, "require_fund_positive": True},
            "B": {"overnight": 6, "fusion": 6},
        },
        "exclusion": {
            "min_turnover": 50000000,      # 最低成交额(元)
            "max_drop_2day": 15,           # 2日最大跌幅%
            "enable_st_filter": True,      # 过滤ST
            "enable_news_blacklist": True, # 新闻黑名单
        },
    },

    # === 交易配置 ===
    "trading": {
        "commission_rate": 0.00025,        # 手续费率
        "stamp_duty_rate": 0.001,          # 印花税率(卖出)
        "transfer_fee_rate": 0.00002,      # 过户费率
        "min_commission": 5,               # 最低佣金
        "slippage": {
            "mode": "ratio",               # ratio=比例, tick=跳数
            "buy_ratio": 0.001,            # 买入滑点 0.1%
            "sell_ratio": 0.001,           # 卖出滑点 0.1%
        },
        "price_precision": {
            "default": 0.01,               # 默认精确到分
            "high_price": {                # 高价股
                "threshold": 100,
                "precision": 0.01,         # A股都是0.01
            },
        },
        "t_plus": {
            "default": 1,                  # 默认T+1
            "etf_t0": True,                # ETF支持T+0
            "kfund_t0": True,              # 可转债支持T+0
        },
    },

    # === 风控配置 (v2.2优化版) ===
    "risk": {
        "hard_stop_loss": -0.07,           # 硬止损 -7%（原-4%太紧，观潮数据真实平均亏损4.6%）
        "ma_stop": True,                   # MA20 止损启用
        "ma_stop_buffer": 0.03,            # MA止损缓冲3%
        "take_profit": 0.20,               # 固定止盈放宽到+20%（让利润奔跑，极少达到，主要依赖动态止盈）
        "trailing_profit_3pct": 0.03,      # 浮盈>3%后，回撤3%止盈（保本）
        "trailing_profit_6pct": 0.05,      # 浮盈>6%后，回撤5%止盈（锁定利润）
        "trailing_profit_10pct": 0.08,     # 浮盈>10%后，回撤8%止盈（让利润奔跑）
        "max_position_per_stock": 0.20,    # 单票最大仓位20%（原25%，降低波动）
        "max_total_position": 0.70,        # 总仓位上限70%（预留30%现金）
        "min_cash_ratio": 0.30,            # 最低现金比例30%
        "max_hold_days": 10,               # 最长持有10天（原15天，短线策略不宜久拿）
        "market_timing": {                 # 大盘择时（新增）
            "enabled": True,
            "ma20_trend_days": 3,          # MA20连续3日向下判定为熊市
            "bear_max_position": 0.30,     # 熊市最大仓位30%
            "bear_stop_new_positions": True,  # 熊市停止开新仓
            "bull_max_position": 0.70,     # 牛市最大仓位70%
        },
        "no_trade_after_stop": True,       # 止损后当日不开新仓
    },

    # === 盘中扫描配置 ===
    "intraday": {
        "enabled": True,
        "schedule": {
            "0930": {
                "name": "开盘突破",
                "query": "主板非ST股票,今日涨跌幅大于3%小于8%,今日主力资金净流入大于3000万",
                "buy_type": "突破",
                "position_pct": 0.10,
                "need_fund_flow": "1d",
                "enable_pool_snapshot": True,
            },
            "1030": {
                "name": "盘中蓄势",
                "query": "主板非ST股票,今日涨跌幅大于-1%小于5%,今日主力资金净流入大于1000万",
                "buy_type": "蓄势",
                "position_pct": 0.08,
                "need_fund_flow": "1d",
                "enable_pool_snapshot": True,
            },
            "1100": {
                "name": "午盘前确认",
                "query": "主板非ST股票,今日涨跌幅大于0%小于6%,今日主力资金净流入大于2000万",
                "buy_type": "确认",
                "position_pct": 0.10,
                "need_fund_flow": "1d",
                "enable_pool_snapshot": True,
            },
            "1330": {
                "name": "午后异动",
                "query": "主板非ST股票,今日涨跌幅大于2%小于7%,今日主力资金净流入大于3000万",
                "buy_type": "午后启动",
                "position_pct": 0.12,
                "need_fund_flow": "1d",
                "enable_pool_snapshot": True,
            },
            "1430": {
                "name": "一夜持股法",
                "query": "主板非ST股票,今日涨跌幅大于-3%小于5%,近5日主力资金净流入大于5000万",
                "buy_type": "隔夜",
                "position_pct": 0.20,
                "need_fund_flow": "5d",
                "enable_pool_snapshot": True,
            },
        },
        "max_candidates_per_scan": 5,      # 每次扫描最多精评几只
        "max_pool_snapshot": 30,           # 池子快照最多查几只
    },

    # === 回测配置 ===
    "backtest": {
        "init_capital": 1000000,           # 初始资金
        "index_benchmark": "000001",       # 基准指数(上证指数)
        "output_dir": None,                # 输出目录
        "output_format": ["console", "csv", "json"],  # 输出格式
        "output_files": {
            "summary": "summary.csv",
            "trades": "trades.csv",
            "daily": "daily_stats.csv",
            "benchmark": "benchmark.csv",
        },
        "enable_mae_mfe": True,            # 启用路径分析
        "enable_regime_analysis": True,    # 启用市场状态分析
        "enable_calibration": True,        # 启用概率校准
    },

    # === 额度控制 ===
    "quota": {
        "ifind_monthly_limit": 5000,       # iFinD 月额度
        "ifind_daily_estimate": 95,        # 预估日消耗
        "alert_threshold": 0.8,            # 额度预警阈值(80%)
    },
}


# ============ 配置管理器 ============

class Config:
    """统一配置管理器"""

    _instance = None
    _config = None

    def __new__(cls, config_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load(config_path)
        return cls._instance

    def _load(self, config_path: str = None):
        """加载配置"""
        # 从默认配置开始
        self._config = deepcopy(DEFAULT_CONFIG)

        # 尝试加载用户配置文件
        path = config_path or DEFAULT_CONFIG_PATH
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                self._merge(self._config, user_config)
                print(f"✅ 已加载配置: {path}")
            except Exception as e:
                print(f"⚠️ 加载配置失败: {e}, 使用默认配置")
        else:
            # 自动创建默认配置文件
            self._save_default(path)
            print(f"📝 已创建默认配置: {path}")

    def _merge(self, base: dict, override: dict):
        """递归合并配置"""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge(base[key], value)
            else:
                base[key] = value

    def _save_default(self, path: str):
        """保存默认配置到文件"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default=None):
        """
        获取配置项（支持点号路径）

        Examples:
            cfg.get("pools.bottom.max_size") → 20
            cfg.get("trading.commission_rate") → 0.00025
        """
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value

    def get_all(self) -> dict:
        """获取完整配置"""
        return deepcopy(self._config)

    def get_pool_config(self, pool_name: str) -> dict:
        """获取指定池子配置"""
        return self._config.get('pools', {}).get(pool_name, {})

    def get_trading_config(self) -> dict:
        """获取交易配置"""
        return self._config.get('trading', {})

    def get_risk_config(self) -> dict:
        """获取风控配置"""
        return self._config.get('risk', {})

    def get_intraday_schedule(self, time_key: str = None) -> dict:
        """获取盘中扫描配置"""
        schedule = self._config.get('intraday', {}).get('schedule', {})
        if time_key:
            return schedule.get(time_key)
        return schedule

    def save(self, path: str = None):
        """保存当前配置到文件"""
        path = path or DEFAULT_CONFIG_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)
        print(f"💾 配置已保存: {path}")


# ============ 便捷函数 ============

# 全局配置实例（首次访问时初始化）
_cfg = None

def get_config(config_path: str = None) -> Config:
    """获取全局配置实例"""
    global _cfg
    if _cfg is None:
        _cfg = Config(config_path)
    return _cfg


def cfg(key: str, default=None):
    """便捷函数：一行获取配置"""
    return get_config().get(key, default)


# ============ 价格 & 交易工具 ============

def calc_trade_cost(price: float, shares: int, is_buy: bool,
                    commission_rate: float = None,
                    stamp_duty_rate: float = None,
                    transfer_fee_rate: float = None,
                    min_commission: float = None) -> dict:
    """
    计算交易成本明细

    Returns:
        {
            'commission': 佣金,
            'stamp_duty': 印花税(卖出才有),
            'transfer_fee': 过户费,
            'total_cost': 总成本,
            'total_value': 成交金额,
        }
    """
    c = get_config()
    commission_rate = commission_rate or c.get('trading.commission_rate', 0.00025)
    stamp_duty_rate = stamp_duty_rate or c.get('trading.stamp_duty_rate', 0.001)
    transfer_fee_rate = transfer_fee_rate or c.get('trading.transfer_fee_rate', 0.00002)
    min_commission = min_commission or c.get('trading.min_commission', 5)

    total_value = price * shares

    # 佣金（买卖都有）
    commission = max(total_value * commission_rate, min_commission)

    # 印花税（仅卖出）
    stamp_duty = total_value * stamp_duty_rate if not is_buy else 0

    # 过户费（买卖都有，沪市）
    transfer_fee = total_value * transfer_fee_rate

    total_cost = commission + stamp_duty + transfer_fee

    return {
        'commission': round(commission, 2),
        'stamp_duty': round(stamp_duty, 2),
        'transfer_fee': round(transfer_fee, 2),
        'total_cost': round(total_cost, 2),
        'total_value': round(total_value, 2),
    }


def apply_slippage(price: float, is_buy: bool, mode: str = None,
                   buy_ratio: float = None, sell_ratio: float = None) -> float:
    """应用滑点"""
    c = get_config()
    mode = mode or c.get('trading.slippage.mode', 'ratio')
    buy_ratio = buy_ratio or c.get('trading.slippage.buy_ratio', 0.001)
    sell_ratio = sell_ratio or c.get('trading.slippage.sell_ratio', 0.001)

    if mode == 'ratio':
        ratio = buy_ratio if is_buy else sell_ratio
        return price * (1 + ratio) if is_buy else price * (1 - ratio)
    return price


def round_price(price: float, precision: float = None) -> float:
    """按价格精度取整（A股都是0.01，但保留扩展性）"""
    c = get_config()
    precision = precision or c.get('trading.price_precision.default', 0.01)
    return round(price / precision) * precision


def is_t0(code: str) -> bool:
    """判断是否支持 T+0"""
    c = get_config()
    # ETF: 51/15/16/58 开头
    if c.get('trading.t_plus.etf_t0', True):
        if code.startswith(('51', '15', '16', '58')):
            return True
    # 可转债: 11/12 开头
    if c.get('trading.t_plus.kfund_t0', True):
        if code.startswith(('11', '12')):
            return True
    return False


if __name__ == "__main__":
    print("=== 配置系统测试 ===")

    # 测试1: 读取默认配置
    print("\n--- 测试1: 读取配置 ---")
    print(f"底部放量池大小: {cfg('pools.bottom.max_size')}")
    print(f"手续费率: {cfg('trading.commission_rate')}")
    print(f"硬止损: {cfg('risk.hard_stop_loss')}")

    # 测试2: 点号路径
    print("\n--- 测试2: 点号路径 ---")
    print(f"1430扫描配置: {cfg('intraday.schedule.1430.name')}")

    # 测试3: 交易成本计算
    print("\n--- 测试3: 交易成本 ---")
    cost = calc_trade_cost(price=100.0, shares=1000, is_buy=True)
    print(f"买入成本: {cost}")
    cost = calc_trade_cost(price=100.0, shares=1000, is_buy=False)
    print(f"卖出成本: {cost}")

    # 测试4: 滑点
    print("\n--- 测试4: 滑点 ---")
    print(f"买入滑点后: {apply_slippage(100.0, is_buy=True)}")
    print(f"卖出滑点后: {apply_slippage(100.0, is_buy=False)}")

    # 测试5: T+0 识别
    print("\n--- 测试5: T+0 识别 ---")
    print(f"600519 是T+0? {is_t0('600519')}")
    print(f"510300 是T+0? {is_t0('510300')}")

    # 测试6: 保存配置
    print("\n--- 测试6: 保存配置 ---")
    config = get_config()
    config.save()
