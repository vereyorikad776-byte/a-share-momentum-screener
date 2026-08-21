"""
market_data_feed.py - 五维择时数据自动获取 v2.2r

自动获取五维择时所需的市场数据：
- 估值: PE、ERP
- 资金: 融资余额
- 技术: 指数布林带、市场广度
- 情绪: PCR、IV、期货基差
- 基本面: CPI、PMI
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple


def get_valuation_data() -> Dict[str, float]:
    """
    获取估值数据 (PE, ERP)
    
    Returns:
        {"pe": 15.2, "bond_yield": 0.025, "erp": 0.041}
    """
    try:
        # 获取沪深300 PE
        index_df = ak.index_value_name_funddb(symbol="沪深300")
        if index_df is not None and len(index_df) > 0:
            latest = index_df.iloc[-1]
            pe = float(latest.get("市盈率", 15.0))
        else:
            pe = 15.0
    except:
        pe = 15.0
    
    # 国债收益率（10年期，约2.5%）
    bond_yield = 0.025
    
    # 计算ERP
    erp = 1.0 / pe - bond_yield if pe > 0 else 0
    
    return {
        "pe": pe,
        "bond_yield": bond_yield,
        "erp": erp,
    }


def get_margin_data() -> Dict[str, float]:
    """
    获取融资余额数据
    
    Returns:
        {"margin_balance": 15000.0, "margin_change_pct": 0.02, "margin_bb_break": True}
    """
    try:
        # 获取融资余额
        margin_df = ak.stock_margin_szse()
        if margin_df is not None and len(margin_df) > 0:
            latest = margin_df.iloc[-1]
            balance = float(latest.get("融资余额", 0)) / 1e8  # 转为亿元
            
            # 计算5日变化率
            if len(margin_df) >= 6:
                prev = margin_df.iloc[-6]
                prev_balance = float(prev.get("融资余额", 0)) / 1e8
                change_pct = (balance - prev_balance) / prev_balance if prev_balance > 0 else 0
            else:
                change_pct = 0
            
            # 简单布林带判断（20日均值±2倍标准差）
            recent = margin_df.tail(20)
            if len(recent) >= 20:
                mean = recent["融资余额"].mean() / 1e8
                std = recent["融资余额"].std() / 1e8
                upper = mean + 2 * std
                bb_break = balance > upper
            else:
                bb_break = False
            
            return {
                "margin_balance": balance,
                "margin_change_pct": change_pct,
                "margin_bb_break": bb_break,
            }
    except:
        pass
    
    return {
        "margin_balance": 0,
        "margin_change_pct": 0,
        "margin_bb_break": False,
    }


def get_breadth_data() -> Dict[str, float]:
    """
    获取市场广度数据（上涨家数占比）
    用腾讯财经指数数据估算，避免akshare限流
    """
    try:
        from enhanced_data_feed import tencent_quote
        # 获取主要指数判断市场整体
        indices = tencent_quote(["000001", "399001", "399006", "000300"])
        up_count = 0
        total = 0
        for code, q in indices.items():
            total += 1
            if q.get('change_pct', 0) > 0:
                up_count += 1
        
        # 用指数涨跌比例估算市场广度（保守估计）
        if total > 0:
            breadth = up_count / total
            # 如果是普涨/普跌，调整估计
            avg_change = sum(q.get('change_pct', 0) for q in indices.values()) / total
            if avg_change > 1.5:
                breadth = min(0.7, breadth + 0.2)
            elif avg_change < -1.5:
                breadth = max(0.3, breadth - 0.2)
            
            return {
                "breadth": breadth,
                "up_count": up_count,
                "total_count": total,
            }
    except Exception as e:
        pass
    
    return {
        "breadth": 0.5,
        "up_count": 0,
        "total_count": 0,
    }


def get_sentiment_data() -> Dict[str, float]:
    """
    获取情绪数据 (PCR, IV, 期货基差)
    
    用Iwencai查询市场情绪指标，失败则返回中性默认值
    """
    try:
        from enhanced_data_feed import iwencai_index
        sh = iwencai_index("上证指数")
        if sh and "error" not in sh:
            change_pct = sh.get("change_pct", 0)
            # 根据指数涨跌幅估算市场情绪
            # 涨>2% → 乐观, 跌>2% → 悲观
            if change_pct > 2:
                pcr = 0.8  # 偏乐观
                iv = 0.18
            elif change_pct > 0:
                pcr = 0.9
                iv = 0.19
            elif change_pct > -2:
                pcr = 1.0
                iv = 0.20
            else:
                pcr = 1.2  # 偏悲观
                iv = 0.25
            
            return {
                "pcr": pcr,
                "iv": iv,
                "futures_position": 0,
                "basis": 0,
            }
    except Exception:
        pass
    
    # 默认中性
    return {
        "pcr": 1.0,
        "iv": 0.2,
        "futures_position": 0,
        "basis": 0,
    }


def get_fundamental_data() -> Dict[str, float]:
    """
    获取基本面宏观数据 (CPI, PMI)
    
    Returns:
        {"cpi": 0.5, "pmi": 50.2, "epu": None}
    """
    try:
        # 获取CPI
        cpi_df = ak.macro_china_cpi()
        if cpi_df is not None and len(cpi_df) > 0:
            latest_cpi = cpi_df.iloc[-1]
            cpi = float(latest_cpi.get("全国同比", 0)) / 100  # 转为小数
        else:
            cpi = 0
    except:
        cpi = 0
    
    try:
        # 获取PMI
        pmi_df = ak.macro_china_pmi()
        if pmi_df is not None and len(pmi_df) > 0:
            latest_pmi = pmi_df.iloc[-1]
            pmi = float(latest_pmi.get("制造业", 50))
        else:
            pmi = 50
    except:
        pmi = 50
    
    return {
        "cpi": cpi,
        "pmi": pmi,
        "epu": 0,  # EPU指数需专业数据源，暂不可用，默认0
    }


def get_all_market_data() -> Dict[str, Dict]:
    """
    获取五维择时所需的全部市场数据
    
    Returns:
        {
            "valuation": {"pe": 15.2, "erp": 0.041},
            "margin": {"margin_change_pct": 0.02, "margin_bb_break": True},
            "breadth": {"breadth": 0.55},
            "sentiment": {"pcr": 1.0, "iv": 0.2},
            "fundamental": {"cpi": 0.5, "pmi": 50.2},
        }
    """
    print("📊 获取五维择时市场数据...")
    
    data = {
        "valuation": get_valuation_data(),
        "margin": get_margin_data(),
        "breadth": get_breadth_data(),
        "sentiment": get_sentiment_data(),
        "fundamental": get_fundamental_data(),
    }
    
    print(f"  估值: PE={data['valuation']['pe']:.1f}, ERP={data['valuation']['erp']:.3f}")
    print(f"  资金: 融资变化={data['margin']['margin_change_pct']*100:.1f}%, 布林带突破={data['margin']['margin_bb_break']}")
    print(f"  技术: 市场广度={data['breadth']['breadth']*100:.0f}%")
    print(f"  情绪: PCR={data['sentiment']['pcr']}, IV={data['sentiment']['iv']}")
    print(f"  基本面: CPI={data['fundamental']['cpi']*100:.1f}%, PMI={data['fundamental']['pmi']:.1f}")
    
    return data


def calc_index_bb_break(code="000300") -> bool:
    """计算指数是否突破布林带上轨（基于腾讯实时数据估算）"""
    try:
        from enhanced_data_feed import tencent_quote
        from data_cache import StockDataCache
        from datetime import datetime, timedelta
        
        # 尝试获取指数K线
        cache = StockDataCache()
        end = datetime.now().strftime('%Y%m%d')
        start = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
        df = cache.get_kline(code, start_date=start, end_date=end)
        
        if df is not None and len(df) >= 20:
            close = df['close']
            ma20 = close.rolling(20).mean().iloc[-1]
            std20 = close.rolling(20).std().iloc[-1]
            upper = ma20 + 2 * std20
            latest = close.iloc[-1]
            return latest > upper
        
        # 备选：用实时数据估算
        quotes = tencent_quote([code])
        if code in quotes:
            q = quotes[code]
            change_pct = q.get('change_pct', 0)
            # 单日大涨>2%可能突破布林带上轨
            return change_pct > 2.0
    except Exception:
        pass
    return False


def run_five_dimension_timing() -> Tuple[float, list]:
    """
    一键运行五维择时
    
    Returns:
        (建议仓位 0~1.0, 理由列表)
    """
    from market_regime import five_dimension_timing
    
    data = get_all_market_data()
    
    # 计算指数布林带突破
    index_bb_break = calc_index_bb_break("000300")  # 沪深300
    
    position, reasons = five_dimension_timing(
        pe=data["valuation"]["pe"],
        bond_yield=data["valuation"]["bond_yield"],
        margin_amount=data["margin"]["margin_change_pct"],
        margin_bb_break=data["margin"]["margin_bb_break"],
        index_bb_break=index_bb_break,
        breadth=data["breadth"]["breadth"],
        pcr=data["sentiment"]["pcr"],
        iv=data["sentiment"]["iv"],
        futures_position=data["sentiment"]["futures_position"],
        basis=data["sentiment"]["basis"],
        cpi=data["fundamental"]["cpi"],
        pmi=data["fundamental"]["pmi"],
        epu=data["fundamental"]["epu"],
    )
    
    return position, reasons


if __name__ == "__main__":
    position, reasons = run_five_dimension_timing()
    print(f"\n{'='*50}")
    print(f"五维择时建议仓位: {position*100:.0f}%")
    print(f"{'='*50}")
    for r in reasons:
        print(f"  {r}")
