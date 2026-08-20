#!/usr/bin/env python3
"""
快速验证脚本 — 用本地缓存的K线验证完整流程
"""
import sys, warnings, json, os
from pathlib import Path
from datetime import datetime
warnings.filterwarnings('ignore')

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import pandas as pd
import numpy as np
from v22_engine import run_v22_scoring
from pool_manager import load_pool
from data_source_manager import DataSourceManager

RESULT_DIR = Path('/root/.openclaw/workspace/skills/ifind-momentum-screener/data/daily')
RESULT_DIR.mkdir(parents=True, exist_ok=True)

def is_main_board(code):
    c = code.strip()
    if c.startswith('300') or c.startswith('301') or c.startswith('688'): return False
    if c.startswith('8') or c.startswith('4'): return False
    return True

def normalize_code(code):
    return code.strip().zfill(6)

# 模拟候选池（用本地有缓存的票）
def load_cached_candidates():
    """从本地K线缓存加载候选票"""
    candidates = {}
    import glob
    for f in glob.glob('/tmp/kline_*.csv'):
        code = os.path.basename(f).replace('kline_', '').replace('.csv', '')
        if is_main_board(code):
            candidates[code] = {
                'code': code,
                'name': f'股票{code}',
                'sources': ['缓存测试'],
                'sectors': ['芯片概念', '人工智能'],  # 模拟板块
            }
    return candidates

def build_v22_data(code, info, df):
    """完整版v2.2数据构建（同daily_full_scanner_v3_fast.py）"""
    if df is None or len(df) < 21: return None
    df = df.dropna(subset=['open','high','low','close','volume'])
    if len(df) < 21: return None
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    close = float(latest['close'])
    open_p = float(latest['open'])
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
    gains = np.where(deltas>0, deltas, 0)
    losses = np.where(deltas<0, -deltas, 0)
    if len(gains) >= 6:
        avg_gain = gains[-6:].mean()
        avg_loss = losses[-6:].mean()
        rsi6 = 100-(100/(1+avg_gain/avg_loss)) if avg_loss!=0 else 50
    else:
        rsi6 = 50
    
    lowest_9 = df['low'].rolling(window=9, min_periods=1).min().iloc[-1]
    highest_9 = df['high'].rolling(window=9, min_periods=1).max().iloc[-1]
    rsv = (close-lowest_9)/(highest_9-lowest_9)*100 if highest_9!=lowest_9 else 50
    k = d = rsv
    j = 3*k - 2*d
    
    high_20d = df['high'].iloc[-21:-1].max()
    low_20d = df['low'].iloc[-21:-1].min()
    volume_20d_avg = volumes[-21:-1].mean()
    volume_ratio = volume/volume_20d_avg if volume_20d_avg>0 else 1.0
    
    change_pct = (close-prev_close)/prev_close*100 if prev_close>0 else 0
    amount = volume*close/10000
    
    # 模式检测
    breakout = close > high_20d
    pullback_pct = (high_20d-close)/high_20d*100 if high_20d>0 else 0
    
    pattern = 0
    pattern_name = '-'
    if breakout:
        gap = (close - high_20d) / high_20d * 100 if high_20d > 0 else 0
        if gap > 3:
            pattern = 2.0
            pattern_name = '突破(大幅越过)'
        elif gap > 1:
            pattern = 1.0
            pattern_name = '突破(中等越过)'
        else:
            pattern = 0.5
            pattern_name = '突破(勉强越过)'
    
    ma20_trend = 'up' if len(df)>=21 and ma20 > df['close'].iloc[-21] else 'neutral'
    
    # 战法检测（简化）
    tactic_score = 0
    tactic_names = []
    
    # 涨停回调
    if len(df) >= 10:
        recent5 = df.iloc[-6:-1]
        limit_up_days = []
        for idx, row in recent5.iterrows():
            try:
                o, c = float(row['open']), float(row['close'])
                h = float(row['high'])
                change = (c-o)/o*100 if o>0 else 0
                if change >= 9.5 or (h>0 and abs(h/o-1.1)<0.005):
                    limit_up_days.append({'close':c, 'high':h})
            except: continue
        if limit_up_days:
            latest_close = close
            last_limit = limit_up_days[-1]
            limit_price = last_limit['high']
            pback = (limit_price-latest_close)/limit_price*100 if limit_price>0 else 0
            if 3 <= pback <= 15:
                recent_vol = volume
                avg_vol_5d = df['volume'].iloc[-6:-1].mean()
                if recent_vol < avg_vol_5d*0.8 if avg_vol_5d>0 else False:
                    tactic_score += 1.5
                    tactic_names.append('涨停回调(缩量)')
                else:
                    tactic_score += 1.0
                    tactic_names.append('涨停回调')
    
    return {
        'code': code, 'name': info.get('name',''),
        'close': close, 'open': open_p, 'high': high, 'low': low,
        'prev_close': prev_close, 'volume': volume, 'amount': amount,
        'volume_20d_avg': volume_20d_avg, 'high_20d': high_20d, 'low_20d': low_20d,
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
        'macd': macd, 'rsi6': rsi6, 'kdj_k': k, 'kdj_d': d, 'kdj_j': j,
        'volume_ratio': volume_ratio, 'change_pct': change_pct,
        'is_hot_sector': len(info.get('sectors',[])) > 0,
        'streak_days': 0, 'institution_hold_pct': 0, 'market_cap': 100,
        'beta': 1.0, 'sector_return': 0, 'index_change': 0, 'sector_change': 0,
        'total_position_pct': 0.3, 'rebound_count': 1, 'retail_etf_flow': 0,
        'erp': 0.03, 'margin_status': 0, 'market_breadth': 0.5,
        'sentiment_score': 0, 'fundamental_score': 0, 'news_sentiment': 0,
        'notice_risk': 1, 'date': datetime.now().strftime('%Y%m%d'),
        'high_recent': high_20d, 'volume_rally_avg': volume_20d_avg,
        'has_hammer': False, 'has_engulfing': False,
        'high_5d_ago': df['high'].iloc[-6] if len(df)>=6 else close,
        'days_in_channel': 0, 'volume_trend_down': False,
        'breakout_today': breakout, 'high_cup': high_20d, 'handle_low': low_20d,
        'volume_handle': volume, 'volume_cup_avg': volume_20d_avg,
        'cost_distribution': [], 'auction_strength': 0,
        'pullback_pct': pullback_pct, 'change_pct_2d': 0,
        'has_major_bad_news': False, 'is_news_blacklisted': False,
        'northbound_net_5d': 0, 'main_force_net_5d': 0,
        'is_st': False, 'pe': 20, 'shareholder_change_pct': 0,
        'ma20_trend': ma20_trend, 'friday_index_change': 0,
        'roe': 15, 'gross_margin': 25, 'net_margin': 8,
        'debt_ratio': 45, 'current_ratio': 1.8,
        'tactic_score': tactic_score, 'tactic_names': tactic_names,
        'pattern': pattern, 'pattern_name': pattern_name,
    }

def run_scoring(candidates):
    results = []
    for code, info in candidates.items():
        try:
            df = pd.read_csv(f'/tmp/kline_{code}.csv')
            df = df.dropna(subset=['open','high','low','close','volume'])
            if len(df) < 21: continue
            
            data = build_v22_data(code, info, df)
            if data is None: continue
            
            result = run_v22_scoring(data)
            
            tactic_score = data.get('tactic_score', 0)
            if tactic_score > 0:
                base = result.get('final_score', 0)
                bonus = min(tactic_score * 0.1, 0.15)
                result['final_score'] = min(base + bonus, 1.0)
            
            result.update({
                'code': code, 'name': info.get('name',''),
                'close': data['close'], 'change_pct': data['change_pct'],
                'sources': info.get('sources', []),
                'sectors': info.get('sectors', []),
                'tactic_score': data.get('tactic_score', 0),
                'tactic_names': data.get('tactic_names', []),
                'pattern_name': data.get('pattern_name', '-'),
            })
            results.append(result)
        except Exception as e:
            print(f"⚠️ {code}: {e}")
    
    results.sort(key=lambda x: x.get('final_score',0), reverse=True)
    return results

def fmt_stock(r):
    lines = []
    code, name = r.get('code',''), r.get('name','')
    close = r.get('close',0)
    change = r.get('change_pct',0)
    tier = r.get('tier','X')
    final = r.get('final_score',0)
    overnight = r.get('overnight_score',0)
    overnight_g = r.get('overnight_grade','')
    fusion = r.get('fusion_score',0)
    fusion_g = r.get('fusion_grade','')
    pattern_name = r.get('pattern_name','-')
    tactic_names = r.get('tactic_names',[])
    sectors = r.get('sectors',[])
    strat = r.get('strategy_type',{})
    strat_type = strat.get('type','-') if isinstance(strat,dict) else '-'
    
    reasons = r.get('reasons',[])
    hit_items = []
    if overnight >= 10: hit_items.append(f"过夜{overnight:.0f}分({overnight_g})")
    if fusion >= 6: hit_items.append(f"融合{fusion:.0f}分({fusion_g})")
    if pattern_name and pattern_name != '-': hit_items.append(pattern_name)
    if tactic_names: hit_items.append(f"战法:{'+'.join(tactic_names)}")
    key_signals = [s for s in reasons if any(k in s for k in ['MACD','KDJ','RSI','突破','金叉','倍量'])]
    hit_items.extend(key_signals[:2])
    hit_desc = ' | '.join(hit_items) if hit_items else '技术面共振'
    
    sector_str = ' / '.join(sectors[:3]) if sectors else '未分类'
    
    lines.append(f"┌─ {code} {name} [{tier}] 综合:{final:.2f}")
    lines.append(f"│  🏷️ 板块: {sector_str}")
    lines.append(f"│  📈 涨跌: {change:+.2f}% | 💰 股价: ¥{close:.2f}")
    lines.append(f"│  🎯 命中: {hit_desc}")
    lines.append(f"│  🚀 策略: 【{strat_type}】")
    if tactic_names:
        lines.append(f"│  ⚔️ 战法: {'+'.join(tactic_names)}")
    lines.append(f"└─")
    return lines

def main():
    print("=" * 80)
    print("🔧 快速验证 — 本地缓存K线完整流程测试")
    print("=" * 80)
    
    candidates = load_cached_candidates()
    print(f"\n📊 本地缓存候选: {len(candidates)}只")
    
    results = run_scoring(candidates)
    print(f"✅ 评分完成: {len(results)}只\n")
    
    # 输出Top 5
    print("🏆 Top 5 排名:")
    for r in results[:5]:
        for line in fmt_stock(r):
            print(line)
        print()
    
    # 统计
    tier_s = [r for r in results if r.get('tier')=='S']
    tier_a = [r for r in results if r.get('tier')=='A']
    tier_b = [r for r in results if r.get('tier')=='B']
    tier_x = [r for r in results if r.get('tier')=='X']
    tactics = [r for r in results if r.get('tactic_score',0)>0]
    
    print(f"📈 统计: S:{len(tier_s)} | A:{len(tier_a)} | B:{len(tier_b)} | X:{len(tier_x)}")
    if tactics: print(f"⚔️ 战法: {len(tactics)}只")

if __name__ == '__main__':
    main()
