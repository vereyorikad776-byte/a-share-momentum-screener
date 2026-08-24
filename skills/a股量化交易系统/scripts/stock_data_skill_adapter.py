#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股全栈数据工具包适配器
基于 xuyongfu/a-stock-data-20260526 封装
整合腾讯财经 + 同花顺 + 东财 + 北向资金 + 龙虎榜 + 融资融券
"""

import requests
import pandas as pd
import json
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# ============ 腾讯财经（PE/PB/市值/换手率） ============

def tencent_quote(codes: List[str]) -> Dict[str, Dict]:
    """
    批量拉取腾讯财经实时行情
    codes: ["688017", "300476"]
    返回: {code: {name, price, pe_ttm, pb, mcap, ...}}
    """
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.encoding = 'gbk'
    data = resp.text

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "amount_wan": float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "amplitude_pct": float(vals[43]) if vals[43] else 0,
            "mcap_yi": float(vals[44]) if vals[44] else 0,
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
            "pe_static": float(vals[52]) if vals[52] else 0,
        }
    return result


# ============ 同花顺北向资金 ============

HSGT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Chrome/117.0.0.0 Safari/537.36"
    ),
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}

def hsgt_realtime() -> Optional[pd.DataFrame]:
    """
    沪深股通当日实时分钟流向（262个时间点）
    返回: time, hgt_yi(沪股通), sgt_yi(深股通) 单位: 亿元
    """
    try:
        url = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
        r = requests.get(url, headers=HSGT_HEADERS, timeout=10)
        d = r.json()
        times = d.get("time", [])
        hgt = d.get("hgt", [])
        sgt = d.get("sgt", [])
        n = len(times)
        return pd.DataFrame({
            "time": times,
            "hgt_yi": hgt[:n] + [None] * (n - len(hgt)),
            "sgt_yi": sgt[:n] + [None] * (n - len(sgt)),
        })
    except Exception as e:
        print(f"北向资金获取失败: {e}")
        return None


def hsgt_summary() -> Dict:
    """北向资金当日汇总"""
    df = hsgt_realtime()
    if df is None or df.empty:
        return {}
    last = df.dropna().iloc[-1]
    return {
        "hgt_net": last.get("hgt_yi", 0),  # 沪股通净买入（亿元）
        "sgt_net": last.get("sgt_yi", 0),  # 深股通净买入（亿元）
        "total_net": last.get("hgt_yi", 0) + last.get("sgt_yi", 0),
    }


# ============ 东财数据中心（共用 helper） ============

def eastmoney_datacenter(api_name: str, filter_str: str = "",
                         page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "") -> List[Dict]:
    """东财 datacenter 通用查询"""
    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
    params = {
        "sortColumns": sort_columns or "",
        "sortTypes": sort_types or "",
        "pageSize": page_size,
        "pageNumber": 1,
        "reportName": api_name,
        "columns": "ALL",
        "source": "WEB",
        "client": "WEB",
        "filter": filter_str,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        d = r.json()
        return d.get("result", {}).get("data", []) or []
    except Exception as e:
        print(f"东财查询失败 {api_name}: {e}")
        return []


# ============ 龙虎榜 ============

def dragon_tiger_board(code: str, look_back: int = 30) -> Dict:
    """
    个股龙虎榜数据
    返回: {records: [...], has_institution: bool, latest_net_buy: float}
    """
    today = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=look_back)).strftime("%Y-%m-%d")

    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start}')(TRADE_DATE<='{today}')(SECURITY_CODE=\"{code}\")",
        page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1",
    )
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy_yi": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
        })

    # 最近上榜的席位（买入）
    latest_buy = []
    if records:
        latest_date = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10, sort_columns="BUY", sort_types="-1",
        )
        for row in buy_data[:5]:
            latest_buy.append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_yi": round((row.get("BUY") or 0) / 10000, 1),
                "is_institution": row.get("OPERATEDEPT_CODE", "") == "0",
            })

    has_institution = any(s.get("is_institution") for s in latest_buy)
    latest_net = records[0]["net_buy_yi"] if records else 0

    return {
        "records": records,
        "buy_seats": latest_buy,
        "has_institution": has_institution,
        "latest_net_buy": latest_net,
        "board_count": len(records),
    }


def market_dragon_tiger(date: str = None) -> List[Dict]:
    """全市场当日龙虎榜"""
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE='{date}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    results = []
    for row in data[:50]:  # Top 50
        results.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "net_buy_yi": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "reason": row.get("EXPLANATION", ""),
        })
    return results


# ============ 融资融券 ============

def margin_trade(code: str, days: int = 20) -> List[Dict]:
    """
    融资融券明细
    返回最近N天: [{date, rzye(融资余额), rzmre(买入), rqye(融券余额)}, ...]
    """
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    
    # 融资
    rz_data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ",
        filter_str=f"(scode=\"{code}\")(date>='{start}')(date<='{end}')",
        page_size=days, sort_columns="date", sort_types="-1",
    )
    
    results = []
    for row in rz_data:
        results.append({
            "date": str(row.get("date", "")),
            "rzye": round((row.get("rzye") or 0) / 100000000, 2),  # 亿元
            "rzmre": round((row.get("rzmre") or 0) / 100000000, 2),  # 买入额
            "rqye": round((row.get("rqye") or 0) / 100000000, 2),  # 融券余额
        })
    return results


def margin_summary(code: str) -> Dict:
    """最新融资融券汇总"""
    data = margin_trade(code, days=1)
    if not data:
        return {}
    latest = data[0]
    prev = data[1] if len(data) > 1 else latest
    
    return {
        "rzye_yi": latest.get("rzye", 0),
        "rqye_yi": latest.get("rqye", 0),
        "rz_change": latest.get("rzye", 0) - prev.get("rzye", 0),
        "leverage_ratio": round(latest.get("rzye", 0) / max(latest.get("rqye", 0.01), 0.01), 2),
    }


# ============ 东财资金流向（个股） ============

def fund_flow_minute(code: str) -> Optional[pd.DataFrame]:
    """
    个股分钟级资金流向
    返回: time, main_net(主力净流入), big_net(大单), mid_net(中单), small_net(小单)
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
        params = {
            "secid": f"0.{code}" if code.startswith(("0", "3")) else f"1.{code}",
            "fields1": "f1,f2,f3,f7",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
            "klt": "1",  # 1分钟
            "lmt": "240",
        }
        r = requests.get(url, params=params, timeout=10)
        d = r.json()
        klines = d.get("data", {}).get("klines", [])
        
        rows = []
        for k in klines:
            parts = k.split(",")
            if len(parts) < 8:
                continue
            rows.append({
                "time": parts[0],
                "main_net": float(parts[1]) / 10000,  # 主力净流入(万元)
                "big_net": float(parts[2]) / 10000,
                "mid_net": float(parts[3]) / 10000,
                "small_net": float(parts[4]) / 10000,
            })
        return pd.DataFrame(rows)
    except Exception as e:
        print(f"资金流向获取失败: {e}")
        return None


def fund_flow_daily(code: str, days: int = 20) -> List[Dict]:
    """个股日级资金流向（主力/大单/中单/小单）"""
    try:
        url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
        params = {
            "reportName": "RPT_MUTUAL_STOCK_NORTH",
            "columns": "ALL",
            "pageSize": days,
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "source": "WEB",
            "client": "WEB",
            "filter": f"(SECURITY_CODE=\"{code}\")",
        }
        r = requests.get(url, params=params, timeout=10)
        d = r.json()
        data = d.get("result", {}).get("data", [])
        
        results = []
        for row in data:
            results.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "main_net_yi": round((row.get("MAIN_NET_INFLOW") or 0) / 100000000, 2),
                "big_net_yi": round((row.get("BIG_NET_INFLOW") or 0) / 100000000, 2),
                "mid_net_yi": round((row.get("MID_NET_INFLOW") or 0) / 100000000, 2),
                "small_net_yi": round((row.get("SMALL_NET_INFLOW") or 0) / 100000000, 2),
            })
        return results
    except Exception as e:
        print(f"日级资金流获取失败: {e}")
        return []


# ============ 同花顺热点（当日强势股） ============

THS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/117.0.0.0 Safari/537.36"
    ),
    "Referer": "https://basic.10jqka.com.cn/",
}

def ths_hot_stocks() -> List[Dict]:
    """同花顺当日热点强势股 + 题材归因"""
    try:
        url = "https://d.10jqka.com.cn/v6/time/hs_1a/last.js"
        r = requests.get(url, headers=THS_HEADERS, timeout=10)
        # 解析 JSONP
        text = r.text
        if text.startswith("last("):
            text = text[5:-1]
        data = json.loads(text)
        
        results = []
        for item in data.get("data", []):
            code = item.get("code", "")
            name = item.get("name", "")
            change_pct = item.get("change", 0)
            reasons = item.get("reason", [])
            
            results.append({
                "code": code,
                "name": name,
                "change_pct": change_pct,
                "reasons": reasons,
                "is_limit_up": change_pct > 9.5,
            })
        
        # 按涨幅排序
        results.sort(key=lambda x: x["change_pct"], reverse=True)
        return results[:50]  # Top 50
    except Exception as e:
        print(f"同花顺热点获取失败: {e}")
        return []


# ============ 概念板块归属 ============

def concept_blocks(code: str) -> List[str]:
    """个股所属概念板块"""
    try:
        url = f"https://basic.10jqka.com.cn/api/stockph/concept/{code}"
        r = requests.get(url, headers=THS_HEADERS, timeout=10)
        d = r.json()
        return [item.get("name", "") for item in d.get("data", [])]
    except Exception:
        return []


# ============ 限售解禁 ============

def lockup_calendar(code: str, days_ahead: int = 90) -> List[Dict]:
    """未来N天限售解禁预警"""
    today = datetime.now().strftime("%Y-%m-%d")
    future = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    
    data = eastmoney_datacenter(
        "RPT_CUSTOM_STOCK_POSITION",
        filter_str=f"(SECURITY_CODE=\"{code}\")(FREE_DATE>='{today}')(FREE_DATE<='{future}')",
        page_size=50,
        sort_columns="FREE_DATE", sort_types="1",
    )
    
    results = []
    for row in data:
        results.append({
            "date": str(row.get("FREE_DATE", ""))[:10],
            "shares_wan": round((row.get("FREE_SHARES") or 0) / 10000, 2),
            "ratio": round(float(row.get("TOTAL_RATIO") or 0) * 100, 2),
        })
    return results


# ============ 统一接口 ============

class StockDataSkillAdapter:
    """A股全栈数据工具包适配器"""
    
    def __init__(self):
        self.name = "stock_data_skill"
    
    # --- 行情层 ---
    def get_quote_full(self, code: str) -> Dict:
        """获取完整行情（腾讯财经）"""
        data = tencent_quote([code])
        return data.get(code, {})
    
    # --- 资金层 ---
    def get_northbound(self) -> Dict:
        """北向资金当日汇总"""
        return hsgt_summary()
    
    def get_dragon_tiger(self, code: str) -> Dict:
        """龙虎榜数据"""
        return dragon_tiger_board(code)
    
    def get_margin(self, code: str) -> Dict:
        """融资融券"""
        return margin_summary(code)
    
    def get_fund_flow(self, code: str) -> List[Dict]:
        """日级资金流向"""
        return fund_flow_daily(code)
    
    # --- 信号层 ---
    def get_hot_stocks(self) -> List[Dict]:
        """当日热点"""
        return ths_hot_stocks()
    
    def get_concepts(self, code: str) -> List[str]:
        """概念板块"""
        return concept_blocks(code)
    
    def get_lockup(self, code: str) -> List[Dict]:
        """限售解禁"""
        return lockup_calendar(code)
    
    # --- 市场层 ---
    def get_market_dragon_tiger(self) -> List[Dict]:
        """全市场龙虎榜"""
        return market_dragon_tiger()


# 全局单例
_stock_data_adapter = None

def get_stock_data_adapter() -> StockDataSkillAdapter:
    global _stock_data_adapter
    if _stock_data_adapter is None:
        _stock_data_adapter = StockDataSkillAdapter()
    return _stock_data_adapter


if __name__ == "__main__":
    print("=== A股全栈数据工具包适配器测试 ===\n")
    
    adapter = get_stock_data_adapter()
    
    # 1. 腾讯行情
    print("1. 腾讯财经行情:")
    quote = adapter.get_quote_full("000001")
    print(f"   {quote.get('name')} PE={quote.get('pe_ttm')} PB={quote.get('pb')} 市值={quote.get('mcap_yi')}亿")
    
    # 2. 北向资金
    print("\n2. 北向资金:")
    nb = adapter.get_northbound()
    print(f"   沪股通: {nb.get('hgt_net', 0):.2f}亿 深股通: {nb.get('sgt_net', 0):.2f}亿")
    
    # 3. 龙虎榜
    print("\n3. 龙虎榜(000001):")
    dt = adapter.get_dragon_tiger("000001")
    print(f"   上榜次数: {dt.get('board_count', 0)} 机构参与: {dt.get('has_institution', False)}")
    
    # 4. 热点
    print("\n4. 当日热点Top5:")
    hot = adapter.get_hot_stocks()
    for s in hot[:5]:
        print(f"   {s['name']}({s['code']}): +{s['change_pct']:.2f}% {s['reasons']}")
