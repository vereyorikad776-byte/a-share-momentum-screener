#!/usr/bin/env python3
"""
v22 完整版评分脚本 - 2026年修正版
动态日期，不再硬编码
"""

import datetime
import pandas as pd
import glob
import os
import json
import sys
import numpy as np

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')
from v22_engine import run_v22_scoring

# ========== 动态日期 ==========
def get_trade_date():
    today = datetime.date.today()
    # 取最近交易日
    if today.weekday() >= 5:  # 周末
        days_back = today.weekday() - 4
    else:
        days_back = 1
    trade_date = today - datetime.timedelta(days=days_back)
    return trade_date

trade_date = get_trade_date()
TRADE_DATE_STR = trade_date.strftime('%Y-%m-%d')
KLINE_START = (trade_date - datetime.timedelta(days=90)).strftime('%Y-%m-%d')  # 3个月历史

print(f"交易日: {TRADE_DATE_STR}")
print(f"K线范围: {KLINE_START} ~ {TRADE_DATE_STR}")

# ========== 合并2026年K线 ==========
print("\n合并2026年K线...")
all_batches = []
for batch_file in sorted(glob.glob('/tmp/kline2026_*.csv')):
    try:
        df = pd.read_csv(batch_file)
        all_batches.append(df)
    except Exception as e:
        print(f"读取失败 {batch_file}: {e}")

# 也包含kline_2026_*.csv格式
for batch_file in sorted(glob.glob('/tmp/kline_2026_*.csv')):
    try:
        df = pd.read_csv(batch_file)
        all_batches.append(df)
    except Exception as e:
        print(f"读取失败 {batch_file}: {e}")

if not all_batches:
    print("没有2026年K线数据！")
    sys.exit(1)

combined = pd.concat(all_batches, ignore_index=True)
combined = combined.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
print(f"合并后共 {len(combined)} 条记录，{combined['thscode'].nunique()} 只票")

# 拆分单票
for thscode, df in combined.groupby('thscode'):
    code = thscode.split('.')[0]
    df = df.sort_values('time').reset_index(drop=True)
    output_path = f'/tmp/kline_{code}.csv'
    df.to_csv(output_path, index=False)

# ========== 读取候选池 ==========
POOL_DIR = '/root/.openclaw/workspace/skills/ifind-momentum-screener/data/pools'
pools = {}
for pool_name in ['bottom_pool', 'hot_pool', 'main_line_pool', 'strong_pool', 'user_pick_pool', 'limit_up_pool']:
    fpath = os.path.join(POOL_DIR, f'{pool_name}.json')
    if os.path.exists(fpath):
        pools[pool_name.replace('_pool', '')] = json.load(open(fpath))

candidates = {}
for pool_name, stocks in pools.items():
    for s in stocks:
        code = s.get('code', '')
        if not code:
            continue
        code = str(code).zfill(6)
        if code not in candidates:
            candidates[code] = {'code': code, 'name': s.get('name', ''), 'sources': [pool_name],
                               'pct_chg': s.get('pct_chg', s.get('连板高度', 0)), 'amount': s.get('amount', 0)}
        else:
            candidates[code]['sources'].append(pool_name)
            candidates[code]['pct_chg'] = max(candidates[code]['pct_chg'], s.get('pct_chg', 0))

print(f"\n候选池共 {len(candidates)} 只票")

# ========== 读取财务数据（F-Score + Z-Score）==========
all_tickers = [c + ('.SH' if c.startswith('6') else '.SZ') for c in candidates.keys()]

def load_financial_data():
    profit_files = glob.glob("/tmp/fs_profit_*.csv")
    cap_files = glob.glob("/tmp/fs_cap_*.csv")
    liq_files = glob.glob("/tmp/fs_liq_*.csv")
    
    profit_dfs = [pd.read_csv(f) for f in profit_files if os.path.exists(f)]
    cap_dfs = [pd.read_csv(f) for f in cap_files if os.path.exists(f)]
    liq_dfs = [pd.read_csv(f) for f in liq_files if os.path.exists(f)]
    
    profit = pd.concat(profit_dfs, ignore_index=True) if profit_dfs else pd.DataFrame()
    cap = pd.concat(cap_dfs, ignore_index=True) if cap_dfs else pd.DataFrame()
    liq = pd.concat(liq_dfs, ignore_index=True) if liq_dfs else pd.DataFrame()
    
    fin_data = {}
    for code in all_tickers:
        rp = profit[profit['thscode'] == code]
        rc = cap[cap['thscode'] == code]
        rl = liq[liq['thscode'] == code]
        
        fin_data[code] = {
            'roe': rp.iloc[0]['ths_roe_stock'] if len(rp) > 0 else None,
            'gross_margin': rp.iloc[0]['ths_gross_selling_rate_stock'] if len(rp) > 0 else None,
            'net_margin': rp.iloc[0]['ths_net_sales_rate_stock'] if len(rp) > 0 else None,
            'debt_ratio': rc.iloc[0]['ths_asset_liab_ratio_stock'] if len(rc) > 0 else None,
            'current_ratio': rl.iloc[0]['ths_current_ratio_stock'] if len(rl) > 0 else None,
        }
    return fin_data

def load_zscore_data():
    """加载Z-Score需要的资产负债表和利润表数据"""
    bs_files = glob.glob("/tmp/bs_top20_*.csv")
    is_files = glob.glob("/tmp/is_top20_*.csv")
    
    bs_dfs = [pd.read_csv(f) for f in bs_files if os.path.exists(f)]
    is_dfs = [pd.read_csv(f) for f in is_files if os.path.exists(f)]
    
    bs_all = pd.concat(bs_dfs, ignore_index=True) if bs_dfs else pd.DataFrame()
    is_all = pd.concat(is_dfs, ignore_index=True) if is_dfs else pd.DataFrame()
    
    zscore_data = {}
    for code in all_tickers:
        bs_row = bs_all[bs_all['thscode'] == code]
        is_row = is_all[is_all['thscode'] == code]
        
        zscore_data[code] = {
            'balance_sheet': bs_row.iloc[0].to_dict() if len(bs_row) > 0 else None,
            'income_statement': is_row.iloc[0].to_dict() if len(is_row) > 0 else None,
        }
    return zscore_data

fin_data = load_financial_data()
zscore_data = load_zscore_data()
print(f"已加载 {len(fin_data)} 只票F-Score财务数据")
print(f"已加载 {len(zscore_data)} 只票Z-Score财务数据")

# ========== 批量评分 ==========
print("\n运行v22完整版评分...")
results = []

for code, info in candidates.items():
    kline_file = f'/tmp/kline_{code}.csv'
    if not os.path.exists(kline_file):
        continue
    try:
        df = pd.read_csv(kline_file)
        df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
        if len(df) < 21:
            continue
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        close = float(latest['close'])
        open_price = float(latest['open'])
        high = float(latest['high'])
        low = float(latest['low'])
        volume = float(latest['volume'])
        prev_close = float(prev['close'])
        
        closes = df['close'].values
        volumes = df['volume'].values
        
        ma5 = closes[-5:].mean()
        ma10 = closes[-10:].mean()
        ma20 = closes[-20:].mean()
        
        ema12 = pd.Series(closes).ewm(span=12, adjust=False).mean().iloc[-1]
        ema26 = pd.Series(closes).ewm(span=26, adjust=False).mean().iloc[-1]
        macd = ema12 - ema26
        
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        if len(gains) >= 6:
            avg_gain = gains[-6:].mean()
            avg_loss = losses[-6:].mean()
            rsi6 = 100 - (100 / (1 + avg_gain / avg_loss)) if avg_loss != 0 else 50
        else:
            rsi6 = 50
        
        lowest_9 = df['low'].rolling(window=9, min_periods=1).min().iloc[-1]
        highest_9 = df['high'].rolling(window=9, min_periods=1).max().iloc[-1]
        rsv = (close - lowest_9) / (highest_9 - lowest_9) * 100 if highest_9 != lowest_9 else 50
        k = d = rsv
        j = 3 * k - 2 * d
        
        # 关键：20日数据不含最新一天
        high_20d = df['high'].iloc[-21:-1].max()
        low_20d = df['low'].iloc[-21:-1].min()
        volume_20d_avg = volumes[-21:-1].mean()
        volume_ratio = volume / volume_20d_avg if volume_20d_avg > 0 else 1.0
        
        streak = 0
        for i in range(1, min(10, len(closes))):
            if closes[-i] > closes[-i-1]:
                streak += 1
            else:
                break
        
        change_pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0
        amount = volume * close / 10000
        
        ma20_trend = 'up' if len(df) >= 21 and ma20 > df['close'].iloc[-21] else 'neutral'
        
        # 阳线吞噬
        has_engulfing = False
        if len(df) >= 3:
            p1 = df.iloc[-2]
            if float(p1['close']) < float(p1['open']) and close > open_price and close > float(p1['open']) and open_price < float(p1['close']):
                has_engulfing = True
        
        # 锤子线
        body = abs(close - open_price)
        upper_shadow = high - max(close, open_price)
        lower_shadow = min(close, open_price) - low
        has_hammer = body > 0 and lower_shadow > body * 2 and upper_shadow < body * 0.5
        
        # 获取财务数据
        ticker = code + ('.SH' if code.startswith('6') else '.SZ')
        fin = fin_data.get(ticker, {})
        zs = zscore_data.get(ticker, {})
        
        data = {
            'code': code, 'name': info['name'], 'close': close, 'open': open_price,
            'high': high, 'low': low, 'prev_close': prev_close, 'volume': volume,
            'amount': amount, 'volume_20d_avg': volume_20d_avg, 'high_20d': high_20d,
            'low_20d': low_20d, 'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
            'macd': macd, 'rsi6': rsi6, 'kdj_k': k, 'kdj_d': d, 'kdj_j': j,
            'volume_ratio': volume_ratio, 'change_pct': change_pct, 'streak_days': streak,
            'is_hot_sector': 'hot' in info['sources'] or 'main_line' in info['sources'],
            'institution_hold_pct': 0, 'market_cap': 0, 'beta': 1.0,
            'sector_return': 0, 'index_change': 0, 'sector_change': 0,
            'total_position_pct': 0.3, 'rebound_count': 1, 'retail_etf_flow': 0,
            'erp': 0.03, 'margin_status': 0, 'market_breadth': 0.5,
            'sentiment_score': 0, 'fundamental_score': 0, 'news_sentiment': 0,
            'notice_risk': 1, 'date': TRADE_DATE_STR.replace('-', ''), 'high_recent': high_20d,
            'volume_rally_avg': volume_20d_avg, 'has_hammer': has_hammer,
            'has_engulfing': has_engulfing, 'high_5d_ago': df['high'].iloc[-6] if len(df) >= 6 else close,
            'days_in_channel': 0, 'volume_trend_down': False,
            'breakout_today': close > high_20d,
            'high_cup': high_20d, 'handle_low': low_20d, 'volume_handle': volume,
            'volume_cup_avg': volume_20d_avg, 'cost_distribution': [],
            'auction_strength': 0,
            'pullback_pct': (high_20d - close) / high_20d * 100 if high_20d > 0 else 0,
            'change_pct_2d': 0, 'has_major_bad_news': False,
            'is_news_blacklisted': False, 'northbound_net_5d': 0,
            'main_force_net_5d': 0, 'is_st': False, 'pe': 0,
            'shareholder_change_pct': 0, 'ma20_trend': ma20_trend,
            'friday_index_change': 0,
            # ★ F-Score财务数据
            'roe': fin.get('roe'),
            'gross_margin': fin.get('gross_margin'),
            'net_margin': fin.get('net_margin'),
            'debt_ratio': fin.get('debt_ratio'),
            'current_ratio': fin.get('current_ratio'),
            # ★ Z-Score财务数据
            'balance_sheet': zs.get('balance_sheet'),
            'income_statement': zs.get('income_statement'),
        }
        
        result = run_v22_scoring(data)
        result.update({'code': code, 'name': info['name'], 'sources': info['sources'],
                      'close': close, 'change_pct': change_pct, 'amount': amount})
        results.append(result)
        
    except Exception as e:
        print(f"评分失败 {code}: {e}")

results.sort(key=lambda x: x['final_score'], reverse=True)

# ====== 过滤：只保留沪深主板票 ======
# 主板：沪市600/601/603/605，深市000/001/002
# 剔除：创业板300/301，科创板688，新三板等
def is_main_board(code):
    """判断是否沪深主板"""
    c = str(code).zfill(6)
    return c[:3] in ['600','601','603','605','000','001','002']

main_board_results = [r for r in results if is_main_board(r['code'])]
print(f"\n全市场评分 {len(results)} 只，其中主板 {len(main_board_results)} 只")
print(f"剔除创业板/科创板: {len(results) - len(main_board_results)} 只")

# 用过滤后的主板票替换results用于后续输出
results = main_board_results

print(f"\n成功评分 {len(results)} 只主板票")
print("=" * 80)
print(f"Top 20 完整版评分榜 ({TRADE_DATE_STR} 盘后)")
print("=" * 80)

for i, r in enumerate(results[:20], 1):
    sources = '/'.join(r['sources'])
    # 多池覆盖标记
    source_count = len(r['sources'])
    source_tag = f"【{source_count}池覆盖】" if source_count >= 3 else ""
    
    # 核心逻辑提炼
    core_logics = []
    # 模式
    if r['pattern'] >= 1.0:
        core_logics.append("突破20日新高+放量")
    elif r['pattern'] >= 0.5:
        core_logics.append("突破20日新高")
    elif r['pattern'] > 0:
        core_logics.append("尝试突破")
    # 趋势
    if any("MA20趋势向上" in reason for reason in r.get('reasons', [])):
        core_logics.append("MA20趋势向上")
    # 多池共振
    if source_count >= 3:
        core_logics.append("多池共振")
    elif source_count >= 2:
        core_logics.append("双池覆盖")
    # 低价
    if r['close'] < 10:
        core_logics.append(f"低价¥{r['close']:.2f}")
    # 涨幅
    if r['change_pct'] > 7:
        core_logics.append(f"强势+{r['change_pct']:.1f}%")
    elif r['change_pct'] > 4:
        core_logics.append(f"活跃+{r['change_pct']:.1f}%")
    # 过夜分高
    if r['overnight'] >= 14:
        core_logics.append("过夜分极高")
    elif r['overnight'] >= 12:
        core_logics.append("过夜分优秀")
    
    core_logic_str = " | ".join(core_logics) if core_logics else "趋势向好"
    
    print(f"\n{i}. {r['code']} {r['name']} {source_tag}")
    print(f"   来源池子: {sources}")
    print(f"   核心逻辑: {core_logic_str}")
    print(f"   评级: {r['tier']} | 综合得分: {r['final_score']:.3f}")
    print(f"   模式分: {r['pattern']:.2f} | 过夜分: {r['overnight']:.1f}/20 | 融合分: {r['fusion']:.1f}/15 | 辩论分: {r['debate']:.2f}")
    print(f"   收盘价: ¥{r['close']:.2f} | 涨跌幅: {r['change_pct']:+.2f}%")
    if r['reasons']:
        print(f"   理由: {'; '.join(r['reasons'][:5])}")

# 保存
output = {'date': TRADE_DATE_STR, 'total_scored': len(results), 'top20': results[:20], 'all_results': results}
output_path = f'/root/.openclaw/workspace/skills/ifind-momentum-screener/data/top20_{TRADE_DATE_STR}.json'
with open(output_path, 'w') as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)

print(f"\n✓ 结果已保存到 {output_path}")
