#!/usr/bin/env python3
"""
quick_screener.py — 快速选股（指定代码列表）

用法: python3 quick_screener.py 600519,000001,002230,...
"""

import sys
import time
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
from v21_engine import run_v21_pipeline
from kelly_position import calc_kelly_position


def fetch_kline(code, days=25):
    """获取K线"""
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')

    try:
        rs = bs.query_history_k_data_plus(
            code,
            "date,open,high,low,close,volume,amount,turn,pctChg,preclose",
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="3"
        )
        data = []
        while (rs.error_code == '0') & rs.next():
            data.append(rs.get_row_data())

        if len(data) >= 20:
            df = pd.DataFrame(data, columns=['date','open','high','low','close','volume','amount','turn','pctChg','preclose'])
            for col in ['open','high','low','close','volume','amount','turn','pctChg','preclose']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df.dropna()
    except Exception as e:
        print(f"  ⚠️ {code} 获取失败: {e}")
    return None


def calc_technical(df):
    """计算技术指标"""
    if df is None or len(df) < 20:
        return None

    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['volume'].values

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    close = float(latest['close'])
    prev_close = float(prev['close']) if len(df) > 1 else close
    high = float(latest['high'])
    low = float(latest['low'])
    open_price = float(latest['open'])
    volume = float(latest['volume'])

    high_20d = max(highs[-20:])
    low_20d = min(lows[-20:])
    volume_20d_avg = sum(volumes[-20:]) / 20

    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20

    # RSI6
    deltas = [closes[i] - closes[i-1] for i in range(-6, 0)]
    gains = sum(d for d in deltas if d > 0)
    losses = sum(-d for d in deltas if d < 0)
    rsi6 = 100 * gains / (gains + losses) if (gains + losses) > 0 else 50

    # MACD
    macd_hist = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0

    # CCI
    tp = (high + low + close) / 3
    tp_sma = sum((h + l + c) / 3 for h, l, c in zip(highs[-20:], lows[-20:], closes[-20:])) / 20
    mean_dev = sum(abs((h + l + c) / 3 - tp_sma) for h, l, c in zip(highs[-20:], lows[-20:], closes[-20:])) / 20
    cci = (tp - tp_sma) / (0.015 * mean_dev) if mean_dev > 0 else 0

    # ROC
    roc = (close - closes[-10]) / closes[-10] * 100 if closes[-10] > 0 else 0

    # Streak
    streak = 0
    for i in range(-1, -4, -1):
        if closes[i] > closes[i-1]:
            streak += 1
        else:
            break

    return {
        'close': close, 'high': high, 'low': low, 'open': open_price,
        'volume': volume, 'prev_close': prev_close,
        'high_20d': high_20d, 'low_20d': low_20d,
        'volume_20d_avg': volume_20d_avg,
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
        'rsi6': rsi6, 'k': 50, 'd': 50, 'j': 50,
        'macd_hist': macd_hist, 'cci': cci, 'roc': roc,
        'streak_days': streak
    }


def scan_stock(code):
    """扫描单只"""
    df = fetch_kline(code, days=25)
    tech = calc_technical(df)

    if tech is None:
        return None

    code_short = code.replace('sh.', '').replace('sz.', '')

    # 检测突破
    breakout_today = tech['close'] > tech['high_20d']

    result = run_v21_pipeline(
        code=code_short, name=code_short, date=datetime.now().strftime('%Y%m%d'),
        close=tech['close'], high=tech['high'], low=tech['low'],
        open_price=tech['open'], volume=tech['volume'], prev_close=tech['prev_close'],
        high_20d=tech['high_20d'], low_20d=tech['low_20d'],
        volume_20d_avg=tech['volume_20d_avg'],
        macd_hist=tech['macd_hist'], ma5=tech['ma5'], ma10=tech['ma10'], ma20=tech['ma20'],
        rsi6=tech['rsi6'], k=tech['k'], d=tech['d'], j=tech['j'],
        cci=tech['cci'], roc=tech['roc'],
        pe=20, roe=10, revenue_growth=15, market_cap=100,
        org_pct=5, northbound_5d=0, main_fund_5d=0, shareholder_change=0,
        sentiment_score=0.3, has_regulatory_risk=False,
        industry_cycle='up', policy_tailwind=1, supply_demand='tight', liquidity_env='loose',
        volume_rally_avg=tech['volume_20d_avg'], has_hammer_or_engulfing=False,
        high_5d_ago=tech['ma5'], days_in_channel=0, volume_trend_down=False,
        breakout_today=breakout_today,
        high_cup=tech['high_20d'], handle_low=tech['low_20d'],
        volume_handle=tech['volume'], volume_cup_avg=tech['volume_20d_avg'],
        streak_days=tech['streak_days'],
        market_green=True, sector_green=True, trend_green=True,
        price_green=True, position_green=True,
        is_top3_sector=True, is_hot_sector=True, has_multi_concepts=False,
        rebound_count=1, friday_market_drop=False, ma20_trend='neutral',
        log=False
    )

    result['code'] = code_short
    result['breakout'] = breakout_today
    result['close'] = tech['close']
    result['prev_close'] = tech['prev_close']
    return result


def main():
    # 默认扫描的代码（测试用）
    default_codes = [
        'sh.600519',  # 茅台
        'sh.600036',  # 招行
        'sz.000001',  # 平安银行
        'sz.002230',  # 科大讯飞
        'sh.600276',  # 恒瑞医药
        'sz.000858',  # 五粮液
        'sh.601318',  # 中国平安
        'sz.002594',  # 比亚迪
    ]

    # 从命令行获取代码
    if len(sys.argv) > 1:
        codes = []
        for c in sys.argv[1].split(','):
            c = c.strip()
            if c.startswith('6'):
                codes.append(f'sh.{c}')
            else:
                codes.append(f'sz.{c}')
    else:
        codes = default_codes

    print("=" * 60)
    print(f"📊 A股动量选股 v2.2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"扫描: {len(codes)}只")
    print()

    # 登录
    print("🔌 连接Baostock...")
    bs.login()
    print("✅ 已连接")
    print()

    # 扫描
    results = []
    for i, code in enumerate(codes):
        print(f"  [{i+1}/{len(codes)}] {code}...", end=' ')
        result = scan_stock(code)
        time.sleep(1)  # 防超时

        if result:
            print(f"✅ tier={result['tier']} final={result['final_score']:.3f}")
            if result['tier'] in ['S', 'A', 'B']:
                results.append(result)
        else:
            print("❌ 无数据")

    bs.logout()

    # 排序输出
    results.sort(key=lambda x: x['final_score'], reverse=True)

    print()
    print("=" * 60)
    print("🏆 TOP 推荐")
    print("=" * 60)
    print()

    if not results:
        print("⚠️ 未发现符合条件的股票")
        return

    for i, r in enumerate(results[:5], 1):
        kelly = calc_kelly_position(67587, r['tier'])
        stop_price = r['prev_close'] * 0.93 if r.get('prev_close') else r['close'] * 0.93

        print(f"【{i}】{r['code']} {r['name']}")
        print(f"   评级: {r['tier']} | 评分: {r['final_score']:.3f} {'📈突破' if r.get('breakout') else ''}")
        print(f"   隔夜: {r['overnight']:.1f} | 融合: {r['fusion']:.1f} | 辩论: {r['debate']:.2f}")
        print(f"   仓位: {kelly['position_pct']:.1f}% = ¥{kelly['position_value']:.0f}")
        print(f"   止损: ¥{stop_price:.2f} (-7%)")
        print()


if __name__ == "__main__":
    main()
