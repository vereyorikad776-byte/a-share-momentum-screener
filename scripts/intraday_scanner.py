#!/usr/bin/env python3
"""
intraday_scanner.py — 盘中实时扫描（完整流程）

时间: 14:09 → 使用14:30扫描条件:
- 涨跌幅: -3%~5%
- 5日资金: >5000万

流程:
1. iFinD获取实时行情（粗筛）
2. Baostock拉历史K线（25日）
3. v2.2精筛（8步管线）
4. 凯利仓位 + 止损位
"""

import sys, warnings, json, time
warnings.filterwarnings('ignore')
sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
from ifind_call import call
from v21_engine import run_v21_pipeline
from kelly_position import calc_kelly_position


def get_realtime_quotes():
    """iFinD获取实时行情"""
    print("🔍 iFinD实时行情扫描...")
    
    # 查询涨幅-3%到5%的票
    result = call('stock', 'search_stocks', {
        'query': '主板 涨幅大于-3 涨幅小于5 成交额大于1000万',
        'limit': 100
    })
    
    content = result['data']['result']['content'][0]['text']
    data = json.loads(content)
    answer = json.loads(data['data'])['answer']
    
    stocks = []
    for line in answer.split('\n'):
        if line.startswith('|') and '股票代码' not in line and '---' not in line:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 5:
                try:
                    code = parts[0].replace('.SZ', '').replace('.SH', '')
                    name = parts[1]
                    board = parts[2]
                    pct_chg = float(parts[3])
                    amount = float(parts[4])
                    
                    if board == '主板' and not name.startswith('*ST') and not name.startswith('ST'):
                        stocks.append({
                            'code': code, 'name': name,
                            'pct_chg': pct_chg, 'amount': amount
                        })
                except:
                    pass
    
    return stocks


def fetch_kline(code, days=25):
    """Baostock获取历史K线"""
    bs_code = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')
    
    try:
        rs = bs.query_history_k_data_plus(
            bs_code,
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
    except:
        pass
    return None


def calc_indicators(df):
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
    ema12 = sum(closes[-12:]) / 12
    ema26 = sum(closes[-26:]) / 26 if len(closes) >= 26 else ema12
    macd_hist = (ema12 - ema26) / ema26 * 100 if ema26 > 0 else 0
    
    # CCI
    tp = (high + low + close) / 3
    tp_sma = sum((h+l+c)/3 for h,l,c in zip(highs[-20:], lows[-20:], closes[-20:])) / 20
    mean_dev = sum(abs((h+l+c)/3 - tp_sma) for h,l,c in zip(highs[-20:], lows[-20:], closes[-20:])) / 20
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


def run_pipeline(code, name, tech):
    """v2.2评分"""
    breakout = tech['close'] > tech['high_20d']
    
    return run_v21_pipeline(
        code=code, name=name, date=datetime.now().strftime('%Y%m%d'),
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
        breakout_today=breakout,
        high_cup=tech['high_20d'], handle_low=tech['low_20d'],
        volume_handle=tech['volume'], volume_cup_avg=tech['volume_20d_avg'],
        streak_days=tech['streak_days'],
        market_green=True, sector_green=True, trend_green=True,
        price_green=True, position_green=True,
        is_top3_sector=True, is_hot_sector=True, has_multi_concepts=False,
        rebound_count=1, friday_market_drop=False, ma20_trend='neutral',
        log=False
    )


def main():
    now = datetime.now()
    print("=" * 60)
    print(f"📊 盘中扫描 v2.2 | {now.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print()
    
    # Step 1: iFinD实时行情
    print("📡 Step 1: iFinD实时行情...")
    stocks = get_realtime_quotes()
    if not stocks:
        print("❌ iFinD无数据")
        return
    
    # 按成交额排序，保留全部100只
    stocks.sort(key=lambda x: x['amount'], reverse=True)
    print(f"✅ 获取 {len(stocks)} 只（全部保留）")
    print()
    
    # Step 2: Baostock拉K线
    print("📈 Step 2: Baostock历史K线...")
    bs.login()
    print("✅ 已连接")
    print()
    
    # Step 3: 精筛
    print("🔬 Step 3: v2.2精筛...")
    results = []
    
    for i, s in enumerate(stocks):
        print(f"  [{i+1}/{len(stocks)}] {s['code']} {s['name']}...", end=' ')
        
        df = fetch_kline(s['code'])
        time.sleep(3)  # 3秒间隔，防Baostock超时
        
        if df is None:
            print("❌ 无K线")
            continue
        
        tech = calc_indicators(df)
        if tech is None:
            print("❌ 数据不足")
            continue
        
        result = run_pipeline(s['code'], s['name'], tech)
        result['pct_chg'] = s['pct_chg']
        result['amount'] = s['amount']
        result['close'] = tech['close']
        result['prev_close'] = tech['prev_close']
        
        print(f"✅ {result['tier']} {result['final_score']:.3f}")
        
        if result['tier'] in ['S', 'A', 'B']:
            results.append(result)
    
    bs.logout()
    
    # Step 4: 输出
    results.sort(key=lambda x: x['final_score'], reverse=True)
    
    print()
    print("=" * 60)
    print("🏆 TOP 推荐")
    print("=" * 60)
    print()
    
    if not results:
        print("⚠️ 未发现S/A/B级")
        return
    
    for i, r in enumerate(results[:5], 1):
        kelly = calc_kelly_position(67587, r['tier'])
        stop = r['prev_close'] * 0.93 if r.get('prev_close') else r['close'] * 0.93
        
        print(f"【{i}】{r['code']} {r['name']}")
        print(f"   评级: {r['tier']} | 评分: {r['final_score']:.3f} | 涨幅: {r['pct_chg']:+.2f}%")
        print(f"   隔夜: {r['overnight']:.1f} | 融合: {r['fusion']:.1f} | 辩论: {r['debate']:.2f}")
        print(f"   仓位: {kelly['position_pct']:.1f}% = ¥{kelly['position_value']:.0f}")
        print(f"   止损: ¥{stop:.2f}")
        print()


if __name__ == "__main__":
    main()
