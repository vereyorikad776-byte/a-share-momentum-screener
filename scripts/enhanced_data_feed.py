#!/usr/bin/env python3
"""
enhanced_data_feed.py — 多源备选数据接口

数据源：
1. mootdx（通达信 TCP）— K线/五档/逐笔
2. 腾讯财经 — 实时价/PE/PB/市值/涨跌停
3. 百度股市通 — K线带MA5/10/20
4. 新浪 — 复权因子/分钟K/实时价
5. 财联社 — 7×24实时电报
6. Iwencai SkillHub — 25个官方API（新闻/公告/研报/板块/调研等）
7. iFinD（付费保底）— 独有财务/资金流/龙虎榜
"""

import socket
import time
import random
import re
import json
import urllib.request
import hashlib
import os
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
# 5. 龙虎榜 — 东财已移除，待接入iFinD替代
# ═══════════════════════════════════════════════════════════════

def dragon_tiger_board(code: str, trade_date: str = None, look_back: int = 30) -> dict:
    """个股龙虎榜 — 东财已移除，待接入iFinD替代"""
    return {"records": [], "summary": None, "note": "东财限流已移除，待iFinD接入"}

def daily_dragon_tiger(trade_date: str = None, min_net_buy: float = None) -> list:
    """全市场龙虎榜 — 东财已移除，待接入iFinD替代"""
    return []

# ═══════════════════════════════════════════════════════════════
# 8. 财联社 — 7×24 实时电报（已测试 ✅ 正常）
# ═══════════════════════════════════════════════════════════════

def cls_telegraph(keyword: str = None, page_size: int = 50) -> list:
    """财联社电报 — 零key，本地签名"""
    params = {"appName": "CailianpressWeb", "os": "web", "sv": "7.7.5",
              "refresh_type": "1", "rn": str(page_size)}
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    sign = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
    url = f"https://www.cls.cn/v1/roll/get_roll_list?{qs}&sign={sign}"
    headers = {"User-Agent": UA, "Referer": "https://www.cls.cn/"}
    r = requests.get(url, headers=headers, timeout=10)
    d = r.json()
    rows = []
    for item in (d.get("data") or {}).get("roll_data") or []:
        ts = item.get("ctime")
        t = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""
        title = item.get("title", "") or item.get("brief", "")
        content = item.get("content", "") or item.get("brief", "")
        # 按关键词过滤
        if keyword and keyword not in title + content:
            continue
        rows.append({"title": title, "content": content, "time": t})
    return rows


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


# ═══════════════════════════════════════════════════════════════
# 11. Iwencai SkillHub — 同花顺问财官方API（25个技能统一封装）
# ═══════════════════════════════════════════════════════════════

import subprocess as _subprocess

_IWENCAI_BASE = os.environ.get("IWENCAI_BASE_URL", "https://openapi.iwencai.com")
_IWENCAI_KEY = os.environ.get("IWENCAI_API_KEY", "")
_SKILL_DIR = Path("/root/.openclaw/workspace/skills")

_IWENCAI_SKILL_MAP = {
    "news-search": "news-search/scripts/news_search.py",
    "announcement-search": "announcement-search/scripts/announcement_search.py",
    "report-search": "report-search/scripts/report_search.py",
    "hithink-zhishu-query": "hithink-zhishu-query/scripts/cli.py",
    "hithink-sector-selector": "hithink-sector-selector/scripts/cli.py",
    "hithink-management-query": "hithink-management-query/scripts/cli.py",
    "hithink-macro-query": "hithink-macro-query/scripts/cli.py",
    "hithink-usstock-selector": "hithink-usstock-selector/scripts/cli.py",
    "hithink-market-query": "hithink-market-query/scripts/cli.py",
    "hithink-insresearch-query": "hithink-insresearch-query/scripts/cli.py",
    "hithink-industry-query": "hithink-industry-query/scripts/cli.py",
    "hithink-hkstock-selector": "hithink-hkstock-selector/scripts/cli.py",
    "hithink-futures-selector": "hithink-futures-selector/scripts/cli.py",
    "hithink-futures-query": "hithink-futures-query/scripts/cli.py",
    "hithink-fund-selector": "hithink-fund-selector/scripts/cli.py",
    "hithink-fundmanager-selector": "hithink-fundmanager-selector/scripts/cli.py",
    "hithink-fundcompany-selector": "hithink-fundcompany-selector/scripts/cli.py",
    "hithink-fund-query": "hithink-fund-query/scripts/cli.py",
    "hithink-finance-query": "hithink-finance-query/scripts/cli.py",
    "hithink-event-query": "hithink-event-query/scripts/cli.py",
    "hithink-business-query": "hithink-business-query/scripts/cli.py",
    "hithink-etf-selector": "hithink-etf-selector/scripts/cli.py",
    "hithink-cb-selector": "hithink-cb-selector/scripts/cli.py",
    "hithink-astock-selector": "hithink-astock-selector/scripts/cli.py",
    "hithink-basicinfo-query": "hithink-basicinfo-query/scripts/cli.py",
}


def iwencai_query(skill_name: str, query: str, limit: int = 10, **extra) -> dict:
    """通用Iwencai SkillHub调用器 — 返回结构化JSON"""
    api_key = os.environ.get("IWENCAI_API_KEY", _IWENCAI_KEY)
    if not api_key:
        return {"success": False, "data": [], "error": "IWENCAI_API_KEY 未配置"}
    script_rel = _IWENCAI_SKILL_MAP.get(skill_name)
    if not script_rel:
        return {"success": False, "data": [], "error": f"未知skill: {skill_name}"}
    script_path = _SKILL_DIR / script_rel
    if not script_path.exists():
        return {"success": False, "data": [], "error": f"脚本不存在: {script_path}"}
    if "cli.py" in str(script_path):
        cmd = ["python3", str(script_path), "--query", query]
        if limit != 10:
            cmd += ["--limit", str(limit)]
    else:
        cmd = ["python3", str(script_path), query]
        if limit != 10:
            cmd += ["--size", str(limit)]
    env = os.environ.copy()
    env["IWENCAI_BASE_URL"] = _IWENCAI_BASE
    env["IWENCAI_API_KEY"] = _IWENCAI_KEY
    try:
        result = _subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=env,
            cwd=str(script_path.parent)
        )
        if result.returncode != 0:
            return {"success": False, "data": [], "error": result.stderr[:500]}
        output = result.stdout.strip()
        json_start = output.find("{")
        if json_start >= 0:
            output = output[json_start:]
        data = json.loads(output)
        if "status_code" in data:
            success = data.get("status_code") == 0
            return {"success": success, "data": data.get("data", []),
                    "error": None if success else data.get("status_msg", "")}
        elif "success" in data:
            return {"success": data["success"], "data": data.get("datas", []),
                    "error": data.get("empty_data_tip", None)}
        else:
            return {"success": True, "data": data, "error": None}
    except json.JSONDecodeError as e:
        return {"success": False, "data": [], "error": f"JSON解析失败: {e}"}
    except Exception as e:
        return {"success": False, "data": [], "error": f"调用异常: {type(e).__name__}: {e}"}


def iwencai_news(stock_name: str, keyword: str = None, limit: int = 5) -> list:
    q = f"{stock_name} {keyword}" if keyword else stock_name
    r = iwencai_query("news-search", q, limit)
    return r.get("data", []) if r["success"] else []


def iwencai_announcement(stock_name: str, keyword: str = None, limit: int = 5) -> list:
    q = f"{stock_name} {keyword}" if keyword else stock_name
    r = iwencai_query("announcement-search", q, limit)
    return r.get("data", []) if r["success"] else []


def iwencai_report(stock_name: str, limit: int = 3) -> list:
    r = iwencai_query("report-search", f"{stock_name} 研报", limit)
    return r.get("data", []) if r["success"] else []


def iwencai_sector_ranking(period: str = "近一周", limit: int = 10) -> list:
    r = iwencai_query("hithink-sector-selector", f"{period}涨幅最大的板块", limit)
    return r.get("data", []) if r["success"] else []


def iwencai_macro(indicator: str = "GDP同比增长率") -> list:
    r = iwencai_query("hithink-macro-query", f"中国最新{indicator}")
    return r.get("data", []) if r["success"] else []


def iwencai_index(name: str = "上证指数") -> dict:
    r = iwencai_query("hithink-zhishu-query", f"{name}最新点位")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_stock_screen(query: str, limit: int = 20) -> list:
    r = iwencai_query("hithink-astock-selector", query, limit)
    return r.get("data", []) if r["success"] else []


def iwencai_us_stock(name: str) -> dict:
    r = iwencai_query("hithink-usstock-selector", f"{name}股价")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_hk_stock(name: str) -> dict:
    r = iwencai_query("hithink-hkstock-selector", f"{name}股价")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_futures(name: str) -> dict:
    r = iwencai_query("hithink-futures-selector", f"{name}主力合约")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_fund(name: str) -> dict:
    r = iwencai_query("hithink-fund-query", f"{name}基金净值")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_industry_pe(industry: str) -> dict:
    r = iwencai_query("hithink-industry-query", f"{industry}行业估值")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_management(stock_name: str) -> list:
    r = iwencai_query("hithink-management-query", f"{stock_name}管理层变动")
    return r.get("data", []) if r["success"] else []


def iwencai_insresearch(stock_name: str) -> list:
    r = iwencai_query("hithink-insresearch-query", f"{stock_name}机构调研")
    return r.get("data", []) if r["success"] else []


def iwencai_etf(query: str, limit: int = 10) -> list:
    r = iwencai_query("hithink-etf-selector", query, limit)
    return r.get("data", []) if r["success"] else []


def iwencai_cb(query: str, limit: int = 10) -> list:
    r = iwencai_query("hithink-cb-selector", query, limit)
    return r.get("data", []) if r["success"] else []


def iwencai_event(stock_name: str) -> list:
    r = iwencai_query("hithink-event-query", f"{stock_name}重大事项")
    return r.get("data", []) if r["success"] else []


def iwencai_business(stock_name: str) -> dict:
    r = iwencai_query("hithink-business-query", f"{stock_name}主营业务")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_finance(stock_name: str) -> dict:
    r = iwencai_query("hithink-finance-query", f"{stock_name}财务数据")
    data = r.get("data", [])
    return data[0] if data and r["success"] else {}


def iwencai_fundmanager(name: str = None) -> list:
    q = name if name else "明星基金经理"
    r = iwencai_query("hithink-fundmanager-selector", q)
    return r.get("data", []) if r["success"] else []


def iwencai_fundcompany(limit: int = 10) -> list:
    r = iwencai_query("hithink-fundcompany-selector", "规模排名前10的基金公司", limit)
    return r.get("data", []) if r["success"] else []


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
    print("\n4. 东财资金流向: 已移除（限流）")
    # 5. 财联社电报
    print("\n5. 财联社电报:")
    try:
        news = cls_telegraph(page_size=5)
        print(f"   共 {len(news)} 条")
        for n in news[:3]:
            print(f"   {n['time']} | {n['title'][:40]}")
    except Exception as e:
        print(f"   ⚠️ 财联社: {type(e).__name__}")

    # 6. Iwencai SkillHub
    print("\n6. Iwencai SkillHub:")
    try:
        news = iwencai_news("贵州茅台", "提价")
        print(f"   新闻: {len(news)}条")
        ann = iwencai_announcement("贵州茅台", "分红")
        print(f"   公告: {len(ann)}条")
        sectors = iwencai_sector_ranking("近一周")
        print(f"   板块TOP3: {[s['指数简称'] for s in sectors[:3]]}")
        idx = iwencai_index("上证指数")
        print(f"   上证指数: {idx.get('最新价', 'N/A')}")
    except Exception as e:
        print(f"   ⚠️ Iwencai: {type(e).__name__}: {e}")

    print("\n=== 测试完成 ===")