#!/usr/bin/env python3
"""
enhanced_data_feed.py — 多源备选数据接口（整合 a-stock-data 精华）

数据源优先级：
1. mootdx（通达信 TCP）— K线/五档/逐笔，不封IP
2. 腾讯财经 — 实时价/PE/PB/市值/涨跌停，不封IP
3. 百度股市通 — K线带MA5/10/20
4. 新浪 — 复权因子/分钟K/实时价
5. 东财（限流）— 资金流向/龙虎榜/研报/新闻（独有数据）
6. 同花顺 — 热点/北向/一致预期

防封策略：
- 东财全部走 em_get()，内置串行限流（间隔≥1s+抖动）
- 批量调用时调大 EM_MIN_INTERVAL
"""

import socket
import time
import random
import re
import json
import urllib.request
from pathlib import Path
from typing import Optional
from datetime import datetime

import requests
import pandas as pd
import numpy as np

# ═══════════════════════════════════════════════════════════════
# 0. 通用工具
# ═══════════════════════════════════════════════════════════════

SH_INDEX = {"000300", "000905", "000016", "000688", "000852", "000010"}


def get_prefix(code: str) -> str:
    """6位代码 → 市场前缀（sh/sz/bj）"""
    c = code.lower().strip()
    if c.endswith((".sh", ".sz", ".bj")):
        return c[-2:]
    if c.startswith(("sh", "sz", "bj")):
        return c[:2]
    if c.startswith("92"):
        return "bj"
    if c.startswith(("5", "6", "9")):
        return "sh"
    if c.startswith(("4", "8")):
        return "bj"
    if c in SH_INDEX:
        return "sh"
    return "sz"


_TICKER_RE = re.compile(
    r"^(?:(sh|sz|bj)(\d{6})|(\d{6})(?:\.(sh|sz|bj))?)$", re.IGNORECASE)


def norm_ticker(code: str) -> str:
    """任意写法 → 纯6位数字"""
    raw = str(code).strip()
    m = _TICKER_RE.match(raw)
    if not m:
        raise ValueError(f"无法解析代码: {code}")
    return m.group(2) or m.group(3)


def em_market_code(code: str) -> int:
    """东财市场号：沪=1，深/北=0"""
    return 1 if get_prefix(code) == "sh" else 0


def em_secid(code: str) -> str:
    """东财 secid，如 1.600519"""
    return f"{em_market_code(code)}.{norm_ticker(code)}"


# ═══════════════════════════════════════════════════════════════
# 1. mootdx 通达信客户端
# ═══════════════════════════════════════════════════════════════

try:
    from mootdx.quotes import Quotes

    _TDX_SERVERS = [
        ('119.97.185.59', 7709), ('124.70.133.119', 7709), ('116.205.183.150', 7709),
        ('123.60.73.44', 7709), ('116.205.163.254', 7709), ('121.36.225.169', 7709),
        ('123.60.70.228', 7709), ('124.71.9.153', 7709), ('110.41.147.114', 7709),
        ('124.71.187.122', 7709),
    ]

    def _probe(ip, port, timeout=2.0):
        try:
            with socket.create_connection((ip, port), timeout=timeout):
                return True
        except Exception:
            return False

    def _validate(client, market='std'):
        if market != 'std':
            return True
        try:
            df = client.bars(symbol='000001', frequency=9, offset=1)
            return df is not None and not df.empty
        except Exception:
            return False

    def tdx_client(market='std'):
        for ip, port in _TDX_SERVERS:
            if not _probe(ip, port):
                continue
            try:
                c = Quotes.factory(market=market, server=(ip, port))
                if _validate(c, market):
                    return c
            except Exception:
                continue
        for kwargs in ({'bestip': True}, {}):
            try:
                c = Quotes.factory(market=market, **kwargs)
                if _validate(c, market):
                    return c
            except Exception:
                continue
        raise RuntimeError("所有 mootdx 服务器均无法连接")

except ImportError:
    Quotes = None
    tdx_client = None


# ═══════════════════════════════════════════════════════════════
# 2. 腾讯财经 — 实时行情（不封IP）
# ═══════════════════════════════════════════════════════════════

def tencent_quote(codes: list) -> dict:
    """批量拉取腾讯实时行情。codes: ['688017', '300476']"""
    prefixed = []
    key_of = {}
    for c in codes:
        low = c.lower()
        if low.startswith(("sh", "sz", "bj")):
            p = low
        elif c.startswith("92"):
            p = f"bj{c}"
        elif c in SH_INDEX or c.startswith(("5", "6", "9")):
            p = f"sh{c}"
        elif c.startswith(("4", "8")):
            p = f"bj{c}"
        else:
            p = f"sz{c}"
        prefixed.append(p)
        key_of[p] = c

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key_of.get(key, key[2:])
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "float_mcap_yi": float(vals[44]) if vals[44] else 0,
            "mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
        }
        q = result[code]
        q["is_stale"] = (q["price"] == q["last_close"] and q["price"] > 0)
    return result


# ═══════════════════════════════════════════════════════════════
# 3. 百度股市通 — K线带MA（不封IP）
# ═══════════════════════════════════════════════════════════════

def baidu_kline(code: str, start_time: str = "") -> dict:
    """百度股市通K线 — 返回时自带 ma5/ma10/ma20"""
    url = "https://finance.pae.baidu.com/selfselect/getstockquotation"
    params = {
        "all": "1", "isIndex": "false", "isBk": "false", "isBlock": "false",
        "isFutures": "false", "isStock": "true", "newFormat": "1",
        "group": "quotation_kline_ab", "finClientType": "pc",
        "code": norm_ticker(code), "start_time": start_time, "ktype": "1",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/vnd.finance-web.v1+json",
        "Origin": "https://gushitong.baidu.com",
        "Referer": "https://gushitong.baidu.com/",
    }
    r = requests.get(url, params=params, headers=headers, timeout=10)
    d = r.json()
    result = d.get("Result", {})
    md = result.get("newMarketData", {})
    keys = md.get("keys", [])
    rows = md.get("marketData", "").split(";")
    return {"keys": keys, "rows": [r for r in rows if r]}


# ═══════════════════════════════════════════════════════════════
# 4. 新浪复权因子
# ═══════════════════════════════════════════════════════════════

def sina_adjust_factor(code: str, kind: str = "qfq") -> list:
    """新浪复权因子 — kind='qfq'(前复权) | 'hfq'(后复权)"""
    if kind not in ("qfq", "hfq"):
        raise ValueError(f"kind 只能是 'qfq' 或 'hfq'")
    ticker = norm_ticker(code).zfill(6)
    prefix = get_prefix(ticker)
    url = f"https://finance.sina.com.cn/realstock/company/{prefix}{ticker}/{kind}.js"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    text = r.text
    match = re.search(r'"data":\s*\[(.*?)\]', text, re.S)
    if not match:
        return []
    raw_json = '[%s]' % match.group(1)
    raw_json = raw_json.replace("'", '"')
    return json.loads(raw_json)


def apply_adjust(bars_df: pd.DataFrame, factors: list, kind: str = "qfq") -> pd.DataFrame:
    """将复权因子应用到 mootdx 的不复权K线"""
    df = bars_df.copy()
    if not factors:
        return df
    factor_map = {item['d']: float(item['f']) for item in factors if 'd' in item and 'f' in item}
    if not factor_map:
        return df
    df['factor'] = df['datetime'].astype(str).map(factor_map)
    df['factor'] = df['factor'].fillna(method='ffill').fillna(method='bfill')
    for col in ['open', 'high', 'low', 'close']:
        if kind == 'qfq':
            df[col] = df[col] * df['factor']
        else:
            df[col] = df[col] / df['factor']
    df = df.drop(columns=['factor'])
    return df


# ═══════════════════════════════════════════════════════════════
# 5. 东财 — 统一限流入口（防封）
# ═══════════════════════════════════════════════════════════════

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception:
    pass

EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]


def em_get(url: str, params: dict = None, headers: dict = None, timeout: int = 15, **kwargs):
    """东财统一请求 — 自动节流 + 复用 session"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "-1") -> list:
    """东财数据中心统一查询"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ═══════════════════════════════════════════════════════════════
# 6. 东财 — 个股资金流向（分钟级）
# ═══════════════════════════════════════════════════════════════

def eastmoney_fund_flow_minute(code: str) -> list:
    """个股资金流向 — 分钟级（超大/大/中/小单）"""
    secid = em_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "klt": "1",  # 1=1分钟
    }
    r = em_get(url, params=params, timeout=15)
    d = r.json()
    data = d.get("data", {})
    klines = data.get("klines", [])
    result = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 15:
            result.append({
                "time": parts[0],
                "main_in": float(parts[1]),   # 主力净流入
                "small_in": float(parts[2]),  # 小单净流入
                "super_in": float(parts[5]),  # 超大单净流入
                "big_in": float(parts[6]),    # 大单净流入
                "mid_in": float(parts[7]),    # 中单净流入
            })
    return result


# ═══════════════════════════════════════════════════════════════
# 7. 东财 — 龙虎榜
# ═══════════════════════════════════════════════════════════════

def dragon_tiger_board(code: str, trade_date: str = None, look_back: int = 30) -> dict:
    """个股龙虎榜 — 上榜记录 + 买卖席位 TOP5"""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    ticker = norm_ticker(code)
    filter_str = f'(SECURITY_CODE="{ticker}")'

    data = eastmoney_datacenter(
        "RPT_DMSK_TS", "ALL", filter_str, page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1"
    )
    if not data:
        return {"records": [], "summary": None}

    records = []
    for row in data:
        records.append({
            "date": row.get("TRADE_DATE", ""),
            "close": row.get("CLOSE_PRICE", 0),
            "change_pct": row.get("CHANGE_RATE", 0),
            "reason": row.get("EXPLANATION", ""),
            "net_buy": row.get("NET_BUY_AMT", 0),
            "buy_amt": row.get("BUY_AMT", 0),
            "sell_amt": row.get("SELL_AMT", 0),
        })

    # 买卖席位
    seats = []
    for i in range(1, 6):
        buy = row.get(f"BUY_AMT_{i}", 0)
        sell = row.get(f"SELL_AMT_{i}", 0)
        if buy or sell:
            seats.append({
                "seat": row.get(f"SEAT_NAME_{i}", ""),
                "buy": buy,
                "sell": sell,
            })

    return {
        "records": records,
        "seats": seats,
        "summary": {
            "total_net_buy": sum(r["net_buy"] for r in records),
            "times": len(records),
        }
    }


def daily_dragon_tiger(trade_date: str = None, min_net_buy: float = None) -> list:
    """全市场龙虎榜 — 当日所有上榜股票"""
    if trade_date is None:
        trade_date = datetime.now().strftime("%Y-%m-%d")
    filter_str = f'(TRADE_DATE="{trade_date}")'
    if min_net_buy:
        filter_str += f"(NET_BUY_AMT>={min_net_buy})"

    data = eastmoney_datacenter(
        "RPT_DMSK_TS", "ALL", filter_str, page_size=200,
        sort_columns="NET_BUY_AMT", sort_types="-1"
    )
    result = []
    for row in data:
        result.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "close": row.get("CLOSE_PRICE", 0),
            "change_pct": row.get("CHANGE_RATE", 0),
            "net_buy": row.get("NET_BUY_AMT", 0),
            "reason": row.get("EXPLANATION", ""),
        })
    return result


# ═══════════════════════════════════════════════════════════════
# 8. 同花顺 — 当日强势股 + 题材归因
# ═══════════════════════════════════════════════════════════════

def ths_hot_reason(date: str = None) -> pd.DataFrame:
    """同花顺热点 — 当日强势股 + 题材标签"""
    if date is None:
        date = datetime.now().strftime("%Y%m%d")
    url = "https://dq.10jqka.com.cn/fuyao/hotListData/hotListConcept"
    params = {"date": date}
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://dq.10jqka.com.cn/",
    }
    r = requests.get(url, params=params, headers=headers, timeout=10)
    d = r.json()
    data = d.get("data", {})
    stocks = data.get("list", [])

    rows = []
    for s in stocks:
        rows.append({
            "code": s.get("code", ""),
            "name": s.get("name", ""),
            "price": s.get("price", 0),
            "change_pct": s.get("change", 0),
            "reason": s.get("reason", ""),
            "concept": s.get("concept", ""),
            "hot_rank": s.get("hot_rank", 0),
        })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
# 9. 筹码分布 — 本地推演
# ═══════════════════════════════════════════════════════════════

def chip_distribution(df: pd.DataFrame, grid_size: int = 300, decay: float = 1.0) -> dict:
    """筹码分布 — 基于 OHLC + 换手率 本地推演
    返回: 获利比例/平均成本/90-70成本区间/集中度/筹码峰
    """
    if df.empty or len(df) < 5:
        return {}
    df = df.copy()
    # 需要 close, high, low, turnover_pct 字段
    if 'turnover_pct' not in df.columns:
        return {"error": "缺少 turnover_pct 字段"}

    # 价格网格
    price_min = df['low'].min() * 0.95
    price_max = df['high'].max() * 1.05
    grid = np.linspace(price_min, price_max, grid_size)
    chips = np.zeros(grid_size)

    # 逐日累加筹码
    for _, row in df.iterrows():
        avg_price = (row['high'] + row['low']) / 2
        turnover = row['turnover_pct'] / 100.0
        # 三角分布模拟当日成交筹码
        weights = np.exp(-0.5 * ((grid - avg_price) / ((row['high'] - row['low']) / 4 + 0.01)) ** 2)
        weights = weights / weights.sum() if weights.sum() > 0 else weights
        # 新增筹码 = 当日换手率比例
        chips = chips * (1 - turnover * decay) + weights * turnover * decay

    total = chips.sum()
    if total == 0:
        return {}

    # 获利比例
    current = df['close'].iloc[-1]
    profit_ratio = chips[grid >= current].sum() / total * 100

    # 平均成本
    avg_cost = (grid * chips).sum() / total

    # 90% / 70% 成本区间
    cumsum = np.cumsum(chips) / total
    def percentile_cost(pct):
        idx = np.searchsorted(cumsum, pct)
        return grid[min(idx, grid_size - 1)]

    p90_low, p90_high = percentile_cost(0.05), percentile_cost(0.95)
    p70_low, p70_high = percentile_cost(0.15), percentile_cost(0.85)

    # 集中度
    p90_concentration = (p90_high - p90_low) / (p90_high + p90_low) * 100 if (p90_high + p90_low) > 0 else 0

    # 筹码峰
    peak_idx = np.argmax(chips)
    peak_price = grid[peak_idx]

    return {
        "profit_ratio": round(profit_ratio, 2),
        "avg_cost": round(avg_cost, 2),
        "p90_range": [round(p90_low, 2), round(p90_high, 2)],
        "p70_range": [round(p70_low, 2), round(p70_high, 2)],
        "p90_concentration": round(p90_concentration, 2),
        "peak_price": round(peak_price, 2),
        "current": round(current, 2),
    }


# ═══════════════════════════════════════════════════════════════
# 10. 测试
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== 测试 enhanced_data_feed ===\n")

    # 1. 腾讯实时行情
    print("1. 腾讯实时行情 (600519):")
    quotes = tencent_quote(["600519"])
    for code, q in quotes.items():
        print(f"   {q['name']}({code}): {q['price']}元 PE={q['pe_ttm']} PB={q['pb']} 市值={q['mcap_yi']}亿")

    # 2. 百度K线
    print("\n2. 百度K线 (600519):")
    kl = baidu_kline("600519")
    print(f"   字段: {kl['keys'][:5]}")
    print(f"   最近3根: {kl['rows'][-3:]}")

    # 3. 新浪复权因子
    print("\n3. 新浪复权因子 (600519):")
    factors = sina_adjust_factor("600519")
    print(f"   共 {len(factors)} 条")

    # 4. 东财资金流向
    print("\n4. 东财资金流向 (600519):")
    try:
        flow = eastmoney_fund_flow_minute("600519")
        print(f"   共 {len(flow)} 条分钟数据")
    except Exception as e:
        print(f"   ⚠️ 东财限流: {type(e).__name__}")

    # 5. 同花顺热点
    print("\n5. 同花顺热点:")
    hot = ths_hot_reason()
    if not hot.empty:
        print(f"   共 {len(hot)} 只强势股")
        print(f"   TOP3: {hot[['name', 'change_pct']].head(3).to_string(index=False)}")

    print("\n=== 测试完成 ===")