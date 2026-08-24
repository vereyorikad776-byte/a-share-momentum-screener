#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股全栈数据工具包适配器 v2.0
经过实测筛选，只保留可用的数据源

已确认可用:
✅ 腾讯财经 - PE/PB/市值/换手率/量比/振幅/涨跌停价
✅ 新浪A股 - 实时行情+五档盘口(需Referer)
✅ 同花顺北向资金 - 分钟级262时间点
✅ Baostock - 历史K线+复权(需login)
✅ 巨潮资讯 - 公告搜索+PDF下载
✅ 新浪港股 - 港股通实时行情

已确认不可用(被反爬/下架):
❌ 东财datacenter/push2 - IP被封
❌ 同花顺热点/概念 - 接口变更
❌ 百度股市通 - 返回空
❌ AKShare - 依赖东财，同样被封
"""

import requests
import json
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# ============ 腾讯财经（全字段） ============

def tencent_quote(codes: List[str]) -> Dict[str, Dict]:
    """批量拉取腾讯财经实时行情"""
    prefixed = []
    for c in codes:
        c = c.strip()
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    resp.encoding = 'gbk'

    result = {}
    for line in resp.text.strip().split(";"):
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
            # 五档买卖盘
            "bid1": float(vals[9]) if vals[9] else 0,
            "bid1_vol": int(vals[10]) if vals[10] else 0,
            "ask1": float(vals[19]) if vals[19] else 0,
            "ask1_vol": int(vals[20]) if vals[20] else 0,
        }
    return result


# ============ 新浪A股（实时+五档） ============

SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn"
}

def sina_quote(codes: List[str]) -> Dict[str, Dict]:
    """新浪A股实时行情（含五档盘口）"""
    prefixed = []
    for c in codes:
        c = c.strip()
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "http://hq.sinajs.cn/list=" + ",".join(prefixed)
    resp = requests.get(url, headers=SINA_HEADERS, timeout=10)
    resp.encoding = 'gbk'

    result = {}
    for line in resp.text.strip().split(";"):
        if not line.strip() or "var hq_str_" not in line:
            continue
        code = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split(",")
        if len(vals) < 33:
            continue
        
        market = code[:2]
        code_num = code[2:]
        
        result[code_num] = {
            "name": vals[0],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[2]) if vals[2] else 0,
            "open": float(vals[1]) if vals[1] else 0,
            "high": float(vals[4]) if vals[4] else 0,
            "low": float(vals[5]) if vals[5] else 0,
            "change_pct": round((float(vals[3]) - float(vals[2])) / float(vals[2]) * 100, 2) if vals[2] and float(vals[2]) > 0 else 0,
            "volume": int(vals[8]) if vals[8] else 0,
            "amount": float(vals[9]) if vals[9] else 0,
            "date": vals[30] if len(vals) > 30 else "",
            "time": vals[31] if len(vals) > 31 else "",
            # 五档买盘
            "bid1": float(vals[11]) if len(vals) > 11 and vals[11] else 0,
            "bid1_vol": int(vals[10]) if len(vals) > 10 and vals[10] else 0,
            "bid2": float(vals[13]) if len(vals) > 13 and vals[13] else 0,
            "bid2_vol": int(vals[12]) if len(vals) > 12 and vals[12] else 0,
            "bid3": float(vals[15]) if len(vals) > 15 and vals[15] else 0,
            "bid3_vol": int(vals[14]) if len(vals) > 14 and vals[14] else 0,
            "bid4": float(vals[17]) if len(vals) > 17 and vals[17] else 0,
            "bid4_vol": int(vals[16]) if len(vals) > 16 and vals[16] else 0,
            "bid5": float(vals[19]) if len(vals) > 19 and vals[19] else 0,
            "bid5_vol": int(vals[18]) if len(vals) > 18 and vals[18] else 0,
            # 五档卖盘
            "ask1": float(vals[21]) if len(vals) > 21 and vals[21] else 0,
            "ask1_vol": int(vals[20]) if len(vals) > 20 and vals[20] else 0,
            "ask2": float(vals[23]) if len(vals) > 23 and vals[23] else 0,
            "ask2_vol": int(vals[22]) if len(vals) > 22 and vals[22] else 0,
            "ask3": float(vals[25]) if len(vals) > 25 and vals[25] else 0,
            "ask3_vol": int(vals[24]) if len(vals) > 24 and vals[24] else 0,
            "ask4": float(vals[27]) if len(vals) > 27 and vals[27] else 0,
            "ask4_vol": int(vals[26]) if len(vals) > 26 and vals[26] else 0,
            "ask5": float(vals[29]) if len(vals) > 29 and vals[29] else 0,
            "ask5_vol": int(vals[28]) if len(vals) > 28 and vals[28] else 0,
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
    """沪深股通当日实时分钟流向（262个时间点）"""
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
        "hgt_net": last.get("hgt_yi", 0),
        "sgt_net": last.get("sgt_yi", 0),
        "total_net": last.get("hgt_yi", 0) + last.get("sgt_yi", 0),
    }


# ============ Baostock历史K线 ============

_baostock_logged_in = False

def baostock_kline(code: str, start_date: str, end_date: str = None,
                   frequency: str = "d", fields: str = None) -> pd.DataFrame:
    """
    Baostock历史K线
    code: "sh.600519" or "sz.000001"
    frequency: "d"日线 "w"周线 "m"月线
    """
    global _baostock_logged_in
    try:
        import baostock as bs
        if not _baostock_logged_in:
            lg = bs.login()
            if lg.error_code != '0':
                return pd.DataFrame()
            _baostock_logged_in = True
        
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        if fields is None:
            fields = "date,code,open,high,low,close,preclose,volume,amount,turn,pctChg"
        
        rs = bs.query_history_k_data_plus(
            code, fields,
            start_date=start_date, end_date=end_date,
            frequency=frequency, adjustflag="3"  # 前复权
        )
        
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
        
        if not data_list:
            return pd.DataFrame()
        
        df = pd.DataFrame(data_list, columns=rs.fields)
        # 转换数值类型
        for col in ['open', 'high', 'low', 'close', 'preclose', 'volume', 'amount', 'turn', 'pctChg']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        return df
    except Exception as e:
        print(f"Baostock获取失败: {e}")
        return pd.DataFrame()


def baostock_logout():
    """登出Baostock"""
    global _baostock_logged_in
    try:
        import baostock as bs
        bs.logout()
        _baostock_logged_in = False
    except:
        pass


# ============ 巨潮资讯公告 ============

def cninfo_search(keyword: str, max_num: int = 10) -> List[Dict]:
    """巨潮资讯公司搜索"""
    try:
        url = "http://www.cninfo.com.cn/new/information/topSearch/query"
        payload = {"keyWord": keyword, "maxNum": max_num}
        r = requests.post(url, data=payload, timeout=10)
        return r.json()
    except Exception as e:
        print(f"巨潮搜索失败: {e}")
        return []


def cninfo_announcements(stock_code: str, org_id: str = None,
                         page_size: int = 10, category: str = None) -> List[Dict]:
    """
    获取巨潮公告列表
    category: category_ndbg_szsh(年报) category_bndbg_szsh(半年报) category_yjdbg_szsh(一季报)
    """
    try:
        # 如果没有orgId，先搜索
        if org_id is None:
            results = cninfo_search(stock_code, max_num=1)
            if results:
                org_id = results[0].get('orgId')
            else:
                return []
        
        url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
        payload = {
            "pageNum": 1,
            "pageSize": page_size,
            "tabName": "fulltext",
            "column": "sse" if stock_code.startswith("6") else "szse",
            "stock": f"{stock_code},{org_id}",
            "plate": "sh" if stock_code.startswith("6") else "sz",
        }
        if category:
            payload["category"] = category
        
        r = requests.post(url, data=payload, timeout=10)
        d = r.json()
        return d.get("announcements", []) or []
    except Exception as e:
        print(f"巨潮公告获取失败: {e}")
        return []


def cninfo_download_pdf(adjunct_url: str) -> bytes:
    """下载巨潮公告PDF"""
    try:
        url = f"http://static.cninfo.com.cn/{adjunct_url}"
        r = requests.get(url, timeout=30)
        return r.content
    except Exception as e:
        print(f"PDF下载失败: {e}")
        return b""


# ============ 新浪港股 ============

def sina_hk_quote(codes: List[str]) -> Dict[str, Dict]:
    """新浪港股实时行情"""
    prefixed = [f"rt_hk{c.lstrip('0')}" for c in codes]
    url = "https://hq.sinajs.cn/list=" + ",".join(prefixed)
    resp = requests.get(url, headers=SINA_HEADERS, timeout=10)
    resp.encoding = 'gbk'

    result = {}
    for line in resp.text.strip().split(";"):
        if not line.strip() or "var hq_str_" not in line:
            continue
        code = line.split("=")[0].split("_")[-1].replace("rt_hk", "")
        vals = line.split('"')[1].split(",")
        if len(vals) < 10:
            continue
        result[code] = {
            "name": vals[0],
            "price": float(vals[2]) if vals[2] else 0,
            "last_close": float(vals[3]) if vals[3] else 0,
            "open": float(vals[4]) if vals[4] else 0,
            "high": float(vals[5]) if vals[5] else 0,
            "low": float(vals[6]) if vals[6] else 0,
            "change_pct": float(vals[8]) if vals[8] else 0,
        }
    return result


# ============ 统一接口 ============

class StockDataSkillAdapter:
    """A股全栈数据工具包适配器 v2.0"""
    
    def __init__(self):
        self.name = "stock_data_skill_v2"
    
    def get_quote_tencent(self, code: str) -> Dict:
        """腾讯全字段行情"""
        data = tencent_quote([code])
        return data.get(code, {})
    
    def get_quote_sina(self, code: str) -> Dict:
        """新浪实时行情+五档"""
        data = sina_quote([code])
        return data.get(code, {})
    
    def get_northbound(self) -> Dict:
        """北向资金当日汇总"""
        return hsgt_summary()
    
    def get_kline_baostock(self, code: str, days: int = 60) -> pd.DataFrame:
        """Baostock历史K线"""
        end = datetime.now()
        start = end - timedelta(days=days)
        
        # 确定市场前缀
        if code.startswith(("6", "9")):
            bs_code = f"sh.{code}"
        elif code.startswith("8"):
            bs_code = f"sh.{code}"
        else:
            bs_code = f"sz.{code}"
        
        return baostock_kline(bs_code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    
    def get_announcements(self, code: str, category: str = None) -> List[Dict]:
        """巨潮公告"""
        return cninfo_announcements(code, category=category)
    
    def get_hk_quote(self, code: str) -> Dict:
        """港股实时行情"""
        data = sina_hk_quote([code])
        return data.get(code.lstrip("0"), {})
    
    def close(self):
        """清理资源"""
        baostock_logout()


# 全局单例
_stock_data_adapter = None

def get_stock_data_adapter() -> StockDataSkillAdapter:
    global _stock_data_adapter
    if _stock_data_adapter is None:
        _stock_data_adapter = StockDataSkillAdapter()
    return _stock_data_adapter


if __name__ == "__main__":
    print("=== A股全栈数据工具包适配器 v2.0 测试 ===\n")
    
    adapter = get_stock_data_adapter()
    
    # 1. 腾讯
    print("1. 腾讯财经:")
    q = adapter.get_quote_tencent("000001")
    print(f"   {q.get('name')} PE={q.get('pe_ttm')} PB={q.get('pb')} 市值={q.get('mcap_yi')}亿")
    
    # 2. 新浪
    print("\n2. 新浪A股(含五档):")
    s = adapter.get_quote_sina("000001")
    print(f"   {s.get('name')} 价格={s.get('price')} 买1={s.get('bid1')} 卖1={s.get('ask1')}")
    
    # 3. 北向
    print("\n3. 北向资金:")
    nb = adapter.get_northbound()
    print(f"   沪股通={nb.get('hgt_net', 0):.2f}亿 深股通={nb.get('sgt_net', 0):.2f}亿")
    
    # 4. Baostock K线
    print("\n4. Baostock K线:")
    df = adapter.get_kline_baostock("600519", days=5)
    if not df.empty:
        print(f"   近5日K线: {len(df)}条")
        print(f"   最新: 收={df.iloc[-1]['close']} 涨={df.iloc[-1]['pctChg']}%")
    
    # 5. 巨潮公告
    print("\n5. 巨潮公告:")
    anns = adapter.get_announcements("600519", category="category_ndbg_szsh")
    print(f"   年报数: {len(anns)}")
    if anns:
        print(f"   最新: {anns[0].get('announcementTitle', 'N/A')[:40]}")
    
    # 6. 港股
    print("\n6. 新浪港股:")
    hk = adapter.get_hk_quote("00700")
    print(f"   腾讯控股 价格={hk.get('price')} 涨跌={hk.get('change_pct')}%")
    
    adapter.close()
    print("\n✅ 全部测试完成")
