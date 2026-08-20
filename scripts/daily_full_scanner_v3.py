#!/usr/bin/env python3
"""
daily_full_scanner_v3.py — 新版完整选股流程 v3.2
用户要求:
1. iFinD主力资金流入前30（主板only）
2. 自动提取近一周热点板块TOP5（从涨幅前50股票的概念中统计频率）
3. 六池合并去重
4. 先历史K线 → 再实时K线 → 完整版评分
5. 完整版v2.2精筛（资金/技术/基本面/消息/情绪/战法）
6. 战法：涨停回调、龙头首阴、首板断板
7. 输出: 标的名称/所属概念板块/今日涨跌幅/当前股价/策略逻辑命中项/操作策略
"""

import sys, warnings, json, os, time, re
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
warnings.filterwarnings('ignore')

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import pandas as pd
import numpy as np
from v22_engine import run_v22_scoring
from pool_manager import load_pool
from ifind_call import call as ifind_call
from data_source_manager import DataSourceManager

# ─── 配置 ───
RESULT_DIR = Path('/root/.openclaw/workspace/skills/ifind-momentum-screener/data/daily')
RESULT_DIR.mkdir(parents=True, exist_ok=True)


def is_main_board(code: str) -> bool:
    c = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '').strip()
    if c.startswith('300') or c.startswith('301') or c.startswith('688'):
        return False
    if c.startswith('8') or c.startswith('4') or c.startswith('920'):
        return False
    return True
        return False
    return True


def normalize_code(code: str) -> str:
    c = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '').strip()
    return c.zfill(6)


# ═══════════════════════════════════════════════════════════════
# iFinD解析
# ═══════════════════════════════════════════════════════════════

def parse_ifind_search_result(result: dict) -> list:
    """解析iFinD search_stocks返回的JSON，提取股票+所属概念"""
    stocks = []
    try:
        content = result.get('data', {}).get('result', {}).get('content', [])
        if not content:
            return stocks
        
        text = content[0].get('text', '{}')
        data = json.loads(text)
        
        if data.get('code') != 1:
            return stocks
        
        inner = json.loads(data.get('data', '{}'))
        answer = inner.get('answer', '')
        
        lines = answer.split('\n')
        in_table = False
        headers = []
        
        for line in lines:
            line = line.strip()
            if not line or '---' in line:
                continue
            if line.startswith('| 股票代码') or line.startswith('|股票代码'):
                in_table = True
                headers = [h.strip() for h in line.split('|') if h.strip()]
                continue
            if in_table and line.startswith('|'):
                cols = [c.strip() for c in line.split('|')]
                cols = [c for c in cols if c]
                if len(cols) >= 2 and '股票代码' not in cols[0]:
                    code = cols[0].strip()
                    name = cols[1].strip() if len(cols) > 1 else ''
                    # 查找所属概念列
                    concepts = ''
                    for i, h in enumerate(headers):
                        if '所属概念' in h or '概念' in h:
                            if i < len(cols):
                                concepts = cols[i]
                                break
                    
                    if code and '.' in code:
                        stocks.append({
                            'code': normalize_code(code),
                            'name': name,
                            'raw_code': code,
                            'concepts': concepts,
                        })
        
        return stocks
    except Exception as e:
        print(f"  解析失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# Step 1: iFinD主力资金流入前30
# ═══════════════════════════════════════════════════════════════

def fetch_main_force_top30() -> list:
    """拉取iFinD主力资金流入前30（主板only，带上所属概念）"""
    print("\n[Step 1] iFinD主力资金流入Top30...")
    
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '今日主力资金净流入排名前30的股票，显示所属概念板块'
        })
        
        if not result.get('ok'):
            print(f"  ❌ iFinD调用失败: {result.get('error', '未知错误')}")
            return []
        
        stocks = parse_ifind_search_result(result)
        main_board = [s for s in stocks if is_main_board(s['code'])]
        
        for s in main_board:
            s['source'] = '主力流入'
        
        print(f"  ✅ 主力资金流入Top30: {len(stocks)}只 -> 主板{len(main_board)}只")
        for s in main_board[:10]:
            print(f"    {s['code']} {s['name']}")
        
        return main_board[:30]
        
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# Step 2: 自动提取热点板块 + 查询成分股
# ═══════════════════════════════════════════════════════════════

def fetch_hot_sectors_auto() -> tuple:
    """
    自动提取近一周热点板块TOP5：
    1. 查近一周涨幅前50的股票
    2. 提取它们的所属概念
    3. 统计概念出现频率
    4. 取Top 5概念板块
    5. 查询每个板块的主板成分股（前6只）
    
    返回: (热门板块名称列表, 板块成分股列表)
    """
    print("\n[Step 2] 自动提取热点板块Top5...")
    
    # 2A: 查近一周涨幅前50的股票（带上所属概念）
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '近一周涨幅排名前50的股票，显示所属概念板块'
        })
        
        if not result.get('ok'):
            print(f"  ❌ 查询失败: {result.get('error', '未知错误')}")
            return [], []
        
        stocks = parse_ifind_search_result(result)
        print(f"  ✅ 近一周涨幅前50: {len(stocks)}只")
        
    except Exception as e:
        print(f"  ❌ 获取失败: {e}")
        return [], []
    
    # 2B: 从所属概念中提取高频概念（过滤通用标签）
    concept_counter = Counter()
    
    # 要过滤掉的通用概念（几乎每个股票都有）
    GENERIC_CONCEPTS = {
        '融资融券', '深股通', '沪股通', '全部A股', '全部AB股', '全部上市公司',
        '沪深A股', '沪深AB股', '上证A股', '上证AB股', '深证A股', '深证AB股',
        '上证上市公司', '深证上市公司', '沪深主板A股', '上证主板A股',
        '全部A股(非ST)', '全部A股(非金融)', '注册制次新股', '新股与次新股',
        '科创板', '创业板', '北证A股', '北证上市公司', '创业板(注册制)',
        '同花顺出海50', '同花顺漂亮100', '同花顺果指数',
    }
    
    for s in stocks:
        concepts_str = s.get('concepts', '')
        if concepts_str:
            concepts = [c.strip() for c in re.split(r'[;；,，]', concepts_str) if c.strip()]
            for c in concepts:
                # 过滤通用概念和太短/太长的
                if c in GENERIC_CONCEPTS:
                    continue
                if len(c) < 2 or len(c) > 20:
                    continue
                if '股票' in c or '板块' in c or 'A股' in c:
                    continue
                concept_counter[c] += 1
    
    # 取Top 5概念板块
    top_concepts = [concept for concept, count in concept_counter.most_common(5)]
    
    print(f"  📊 热点板块Top5: {top_concepts}")
    
    # 2C: 查询每个热点板块的主板成分股（前6只）
    all_sector_stocks = []
    
    for concept in top_concepts:
        try:
            print(f"    查询 [{concept}] 成分股...", end=' ')
            result = ifind_call('stock', 'search_stocks', {
                'query': f'{concept}概念股'
            })
            
            if result.get('ok'):
                sector_stocks = parse_ifind_search_result(result)
                main_board = [s for s in sector_stocks if is_main_board(s['code'])]
                
                for s in main_board[:6]:
                    s['source'] = f'板块:{concept}'
                    s['sector'] = concept
                    all_sector_stocks.append(s)
                
                print(f"✅ 主板{len(main_board[:6])}只")
            else:
                print(f"❌")
                
        except Exception as e:
            print(f"❌ {e}")
    
    print(f"  ✅ 热点板块成分股合计: {len(all_sector_stocks)}只")
    return top_concepts, all_sector_stocks


# ═══════════════════════════════════════════════════════════════
# Step 3: 六池读取
# ═══════════════════════════════════════════════════════════════

def load_all_pools_v3() -> dict:
    """读取六池数据并标准化"""
    print("\n[Step 3] 读取六池数据...")
    
    pools = {}
    pool_names = ['bottom', 'limit_up', 'main_line', 'strong', 'user_pick', 'hot']
    
    for name in pool_names:
        data = load_pool(name)
        filtered = []
        for item in data:
            code = normalize_code(item.get('code', ''))
            if is_main_board(code):
                item['code'] = code
                item['source'] = item.get('source', name)
                filtered.append(item)
        pools[name] = filtered
        print(f"  📂 {name}: {len(filtered)}只")
    
    return pools


# ═══════════════════════════════════════════════════════════════
# Step 4: 合并去重
# ═══════════════════════════════════════════════════════════════

def merge_candidates(main_force_30: list, sector_stocks: list, pools: dict) -> dict:
    """合并所有来源，去重"""
    print("\n[Step 4] 合并去重...")
    
    candidates = {}
    
    # 1. 主力资金流入
    for s in main_force_30:
        code = s['code']
        # 从concepts提取板块信息
        sectors = []
        concepts_str = s.get('concepts', '')
        if concepts_str:
            all_concepts = [c.strip() for c in re.split(r'[;；,，]', concepts_str) if c.strip()]
            # 过滤通用概念，保留有意义的板块
            GENERIC = {'融资融券', '深股通', '沪股通', '全部A股', '全部AB股', '全部上市公司',
                       '沪深A股', '沪深AB股', '上证A股', '上证AB股', '深证A股', '深证AB股',
                       '上证上市公司', '深证上市公司', '沪深主板A股', '上证主板A股',
                       '全部A股(非ST)', '全部A股(非金融)', '注册制次新股', '新股与次新股',
                       '科创板', '创业板', '北证A股', '北证上市公司'}
            sectors = [c for c in all_concepts if c not in GENERIC and len(c) >= 2 and len(c) <= 20]
        
        candidates[code] = {
            'code': code,
            'name': s.get('name', ''),
            'sources': [s.get('source', '主力流入')],
            'sectors': sectors[:3],  # 最多保留3个板块
        }
    
    # 2. 热点板块成分股
    for s in sector_stocks:
        code = s['code']
        sector = s.get('sector', '')
        if code in candidates:
            if '热点板块' not in candidates[code]['sources']:
                candidates[code]['sources'].append('热点板块')
            if sector and sector not in candidates[code]['sectors']:
                candidates[code]['sectors'].append(sector)
        else:
            candidates[code] = {
                'code': code,
                'name': s.get('name', ''),
                'sources': [s.get('source', '热点板块')],
                'sectors': [sector] if sector else [],
            }
    
    # 3. 六池
    for pool_name, stocks in pools.items():
        for s in stocks:
            code = s.get('code', '')
            if not is_main_board(code):
                continue
            if code in candidates:
                if pool_name not in candidates[code]['sources']:
                    candidates[code]['sources'].append(pool_name)
            else:
                candidates[code] = {
                    'code': code,
                    'name': s.get('name', ''),
                    'sources': [pool_name],
                    'sectors': [],
                }
    
    print(f"  ✅ 合并后候选池: {len(candidates)}只")
    return candidates


# ═══════════════════════════════════════════════════════════════
# Step 5: 先拉历史K线（日线）
# ═══════════════════════════════════════════════════════════════

def fetch_historical_klines(candidates: dict) -> dict:
    """先拉历史K线（日线，用于过夜分/融合分等历史依赖指标）"""
    print(f"\n[Step 5] 拉取历史K线（日线）...")
    
    dsm = DataSourceManager()
    kline_data = {}
    need_fetch = []
    
    # 先检查本地已有数据
    for code in candidates.keys():
        local_file = f"/tmp/kline_{code}.csv"
        if os.path.exists(local_file):
            try:
                df = pd.read_csv(local_file)
                df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
                if len(df) >= 21:
                    kline_data[code] = df
                    continue
            except:
                pass
        need_fetch.append(code)
    
    print(f"  ✅ 本地缓存: {len(kline_data)}只")
    
    # 缺失的用Baostock拉取
    if need_fetch:
        print(f"  📥 需拉取: {len(need_fetch)}只")
        end_date = datetime.now().strftime('%Y-%m-%d')
        
        for i, code in enumerate(need_fetch):
            print(f"    [{i+1}/{len(need_fetch)}] {code}...", end=' ', flush=True)
            try:
                df = dsm.fetch_history_kline(code, days=60, end_date=end_date)
                if df is not None and len(df) >= 21:
                    kline_data[code] = df
                    print(f"✅ {len(df)}条")
                else:
                    print(f"⚠️ 仅{len(df) if df is not None else 0}条")
            except Exception as e:
                print(f"❌ {e}")
            time.sleep(0.2)
    
    print(f"  ✅ 历史K线就绪: {len(kline_data)}/{len(candidates)}只")
    return kline_data


# ═══════════════════════════════════════════════════════════════
# Step 6: 补实时K线（1分钟/5分钟，盘中用）
# ═══════════════════════════════════════════════════════════════

def fetch_intraday_klines(candidates: dict, kline_data: dict) -> dict:
    """补充实时1分钟K线（盘中用）——当前为盘后，跳过"""
    print(f"\n[Step 6] 补充实时K线...")
    
    now = datetime.now()
    hour = now.hour
    
    if not (9 <= hour <= 11 or 13 <= hour <= 15):
        print(f"  ⏰ 当前{hour}:00，非交易时间，跳过实时K线")
        return kline_data
    
    print(f"  📊 交易时间，拉取1分钟K线...")
    return kline_data


# ═══════════════════════════════════════════════════════════════
# 战法检测
# ═══════════════════════════════════════════════════════════════

def detect_limit_up_pullback(df: pd.DataFrame) -> tuple:
    """检测涨停回调模式"""
    if len(df) < 10:
        return False, '', 0
    
    recent5 = df.iloc[-6:-1]
    limit_up_days = []
    
    for idx, row in recent5.iterrows():
        try:
            open_p = float(row['open'])
            close = float(row['close'])
            high = float(row['high'])
            change_pct = (close - open_p) / open_p * 100 if open_p > 0 else 0
            if change_pct >= 9.5 or (high > 0 and abs(high/open_p - 1.1) < 0.005):
                limit_up_days.append({'close': close, 'high': high})
        except:
            continue
    
    if not limit_up_days:
        return False, '', 0
    
    latest = df.iloc[-1]
    latest_close = float(latest['close'])
    last_limit = limit_up_days[-1]
    limit_price = last_limit['high']
    
    pullback_pct = (limit_price - latest_close) / limit_price * 100 if limit_price > 0 else 0
    
    if 3 <= pullback_pct <= 15:
        recent_volume = float(latest['volume'])
        avg_volume_5d = df['volume'].iloc[-6:-1].mean()
        volume_shrink = recent_volume < avg_volume_5d * 0.8 if avg_volume_5d > 0 else False
        
        if volume_shrink:
            return True, '涨停回调(缩量)', 1.5
        else:
            return True, '涨停回调', 1.0
    
    return False, '', 0


def detect_dragon_first_yin(df: pd.DataFrame) -> tuple:
    """检测龙头首阴模式"""
    if len(df) < 5:
        return False, '', 0
    
    recent = df.iloc[-5:]
    consecutive_limits = 0
    
    for idx in range(len(recent) - 1):
        try:
            row = recent.iloc[idx]
            open_p = float(row['open'])
            close = float(row['close'])
            change_pct = (close - open_p) / open_p * 100 if open_p > 0 else 0
            
            if change_pct >= 9.5:
                consecutive_limits += 1
            else:
                if consecutive_limits >= 2:
                    break
                consecutive_limits = 0
        except:
            continue
    
    if consecutive_limits < 2:
        return False, '', 0
    
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    try:
        latest_close = float(latest['close'])
        latest_open = float(latest['open'])
        prev_close = float(prev['close'])
        
        is_yin = latest_close < latest_open
        drop_pct = (prev_close - latest_close) / prev_close * 100 if prev_close > 0 else 0
        
        if is_yin and drop_pct < 5:
            return True, '龙头首阴', 1.5
    except:
        pass
    
    return False, '', 0


def detect_first_board_break(df: pd.DataFrame) -> tuple:
    """检测首板断板模式"""
    if len(df) < 4:
        return False, '', 0
    
    recent3 = df.iloc[-4:-1]
    
    try:
        day1 = recent3.iloc[0]
        d1_open = float(day1['open'])
        d1_close = float(day1['close'])
        d1_change = (d1_close - d1_open) / d1_open * 100 if d1_open > 0 else 0
        
        if d1_change < 9.5:
            return False, '', 0
        
        day2 = recent3.iloc[1]
        d2_close = float(day2['close'])
        d2_open = float(day2['open'])
        d2_change = (d2_close - d2_open) / d2_open * 100 if d2_open > 0 else 0
        
        if d2_change >= 9.5:
            return False, '', 0
        
        latest = df.iloc[-1]
        l_close = float(latest['close'])
        l_open = float(latest['open'])
        
        body_pct = abs(l_close - l_open) / l_open * 100 if l_open > 0 else 0
        
        if body_pct < 3 or l_close > l_open:
            if l_close > d1_open:
                return True, '首板断板(承接)', 1.0
    except:
        pass
    
    return False, '', 0


# ═══════════════════════════════════════════════════════════════
# Step 7: 完整版v2.2评分（加入战法）
# ═══════════════════════════════════════════════════════════════

def build_v22_data_with_tactics(code: str, info: dict, kline_df: pd.DataFrame) -> dict:
    """构建v22引擎数据 + 战法检测"""
    
    if kline_df is None or len(kline_df) < 21:
        return None
    
    df = kline_df.copy()
    df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
    
    if len(df) < 21:
        return None
    
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
    
    high_20d = df['high'].iloc[-21:-1].max()
    low_20d = df['low'].iloc[-21:-1].min()
    volume_20d_avg = volumes[-21:-1].mean()
    volume_ratio = volume / volume_20d_avg if volume_20d_avg > 0 else 1.0
    
    change_pct = (close - prev_close) / prev_close * 100 if prev_close > 0 else 0
    amount = volume * close / 10000
    
    has_engulfing = False
    if len(df) >= 3:
        p1 = df.iloc[-2]
        if float(p1['close']) < float(p1['open']) and close > open_price and close > float(p1['open']) and open_price < float(p1['close']):
            has_engulfing = True
    
    body = abs(close - open_price)
    upper_shadow = high - max(close, open_price)
    lower_shadow = min(close, open_price) - low
    has_hammer = body > 0 and lower_shadow > body * 2 and upper_shadow < body * 0.5
    
    ma20_trend = 'up' if len(df) >= 21 and ma20 > df['close'].iloc[-21] else 'neutral'
    breakout = close > high_20d
    pullback_pct = (high_20d - close) / high_20d * 100 if high_20d > 0 else 0
    
    # ─── 战法检测 ───
    is_limit_up_pullback, pullback_name, pullback_score = detect_limit_up_pullback(df)
    is_dragon_yin, dragon_name, dragon_score = detect_dragon_first_yin(df)
    is_first_break, break_name, break_score = detect_first_board_break(df)
    
    tactic_score = 0
    tactic_names = []
    if is_limit_up_pullback:
        tactic_score += pullback_score
        tactic_names.append(pullback_name)
    if is_dragon_yin:
        tactic_score += dragon_score
        tactic_names.append(dragon_name)
    if is_first_break:
        tactic_score += break_score
        tactic_names.append(break_name)
    
    data = {
        'code': code,
        'name': info.get('name', ''),
        'close': close,
        'open': open_price,
        'high': high,
        'low': low,
        'prev_close': prev_close,
        'volume': volume,
        'amount': amount,
        'volume_20d_avg': volume_20d_avg,
        'high_20d': high_20d,
        'low_20d': low_20d,
        'ma5': ma5,
        'ma10': ma10,
        'ma20': ma20,
        'macd': macd,
        'rsi6': rsi6,
        'kdj_k': k,
        'kdj_d': d,
        'kdj_j': j,
        'volume_ratio': volume_ratio,
        'change_pct': change_pct,
        'streak_days': 0,
        'is_hot_sector': len(info.get('sectors', [])) > 0 or 'hot' in info.get('sources', []) or 'main_line' in info.get('sources', []),
        'institution_hold_pct': 0,
        'market_cap': 100,
        'beta': 1.0,
        'sector_return': 0,
        'index_change': 0,
        'sector_change': 0,
        'total_position_pct': 0.3,
        'rebound_count': 1,
        'retail_etf_flow': 0,
        'erp': 0.03,
        'margin_status': 0,
        'market_breadth': 0.5,
        'sentiment_score': 0,
        'fundamental_score': 0,
        'news_sentiment': 0,
        'notice_risk': 1,
        'date': datetime.now().strftime('%Y%m%d'),
        'high_recent': high_20d,
        'volume_rally_avg': volume_20d_avg,
        'has_hammer': has_hammer,
        'has_engulfing': has_engulfing,
        'high_5d_ago': df['high'].iloc[-6] if len(df) >= 6 else close,
        'days_in_channel': 0,
        'volume_trend_down': False,
        'breakout_today': breakout,
        'high_cup': high_20d,
        'handle_low': low_20d,
        'volume_handle': volume,
        'volume_cup_avg': volume_20d_avg,
        'cost_distribution': [],
        'auction_strength': 0,
        'pullback_pct': pullback_pct,
        'change_pct_2d': 0,
        'has_major_bad_news': False,
        'is_news_blacklisted': False,
        'northbound_net_5d': 0,
        'main_force_net_5d': 0,
        'is_st': False,
        'pe': 20,
        'shareholder_change_pct': 0,
        'ma20_trend': ma20_trend,
        'friday_index_change': 0,
        'roe': 15,
        'gross_margin': 25,
        'net_margin': 8,
        'debt_ratio': 45,
        'current_ratio': 1.8,
        'tactic_score': tactic_score,
        'tactic_names': tactic_names,
        'is_limit_up_pullback': is_limit_up_pullback,
        'is_dragon_first_yin': is_dragon_yin,
        'is_first_board_break': is_first_break,
    }
    
    return data


def run_full_scoring_with_tactics(candidates: dict, kline_data: dict) -> list:
    """对候选票运行完整版v2.2评分 + 战法"""
    print(f"\n[Step 7] 完整版v2.2评分 + 战法...")
    
    results = []
    
    for code, info in candidates.items():
        kline_df = kline_data.get(code)
        if kline_df is None:
            continue
        
        try:
            data = build_v22_data_with_tactics(code, info, kline_df)
            if data is None:
                continue
            
            result = run_v22_scoring(data)
            
            tactic_score = data.get('tactic_score', 0)
            if tactic_score > 0:
                base_score = result.get('final_score', 0)
                bonus = min(tactic_score * 0.1, 0.15)
                result['final_score'] = min(base_score + bonus, 1.0)
                result['tactic_score'] = tactic_score
                result['tactic_names'] = data.get('tactic_names', [])
            else:
                result['tactic_score'] = 0
                result['tactic_names'] = []
            
            result.update({
                'code': code,
                'name': info.get('name', ''),
                'close': data['close'],
                'change_pct': data['change_pct'],
                'sources': info.get('sources', []),
                'sectors': info.get('sectors', []),
            })
            results.append(result)
            
        except Exception as e:
            print(f"  ⚠️ {code} 评分失败: {e}")
            continue
    
    results.sort(key=lambda x: x.get('final_score', 0), reverse=True)
    print(f"  ✅ 评分完成: {len(results)}只")
    return results


# ═══════════════════════════════════════════════════════════════
# Step 8: 输出结果（用户指定格式）
# ═══════════════════════════════════════════════════════════════

def format_output(results: list) -> str:
    """格式化输出结果（用户指定格式）"""
    
    lines = []
    lines.append("=" * 90)
    lines.append(f"🎯 A股动量选股系统 v3.2 — 完整版评分结果")
    lines.append(f"📅 日期: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"📊 数据源: iFinD主力 + 自动热点板块 + 历史K线 + 六池合并")
    lines.append("=" * 90)
    lines.append("")
    
    tier_s = [r for r in results if r.get('tier') == 'S']
    tier_a = [r for r in results if r.get('tier') == 'A']
    tier_b = [r for r in results if r.get('tier') == 'B']
    tier_x = [r for r in results if r.get('tier') == 'X']
    
    if tier_s:
        lines.append("🔥🔥🔥 Tier S — 强烈推荐 🔥🔥🔥")
        for r in tier_s[:5]:
            lines.extend(_format_stock_v32(r))
        lines.append("")
    
    if tier_a:
        lines.append("⭐⭐ Tier A — 推荐关注 ⭐⭐")
        for r in tier_a[:10]:
            lines.extend(_format_stock_v32(r))
        lines.append("")
    
    if tier_b:
        lines.append("⭐ Tier B — 观察 Tier B ⭐")
        for r in tier_b[:10]:
            lines.extend(_format_stock_v32(r))
        lines.append("")
    
    # 战法专区
    tactic_stocks = [r for r in results if r.get('tactic_score', 0) > 0]
    if tactic_stocks:
        lines.append("⚔️ 战法专区 — 涨停回调/龙头首阴/首板断板 ⚔️")
        for r in tactic_stocks[:5]:
            lines.extend(_format_tactic_stock(r))
        lines.append("")
    
    lines.append("📈 统计:")
    lines.append(f"   Tier S: {len(tier_s)} | Tier A: {len(tier_a)} | Tier B: {len(tier_b)} | Tier X: {len(tier_x)}")
    if tactic_stocks:
        lines.append(f"   战法触发: {len(tactic_stocks)}只")
    lines.append("")
    
    return "\n".join(lines)


def _format_stock_v32(r: dict) -> list:
    """
    格式化单只股票 v3.2 — 用户指定格式：
    - 标的名称
    - 所属概念板块
    - 今日涨跌幅
    - 当前股价
    - 策略逻辑命中项（说明高评分原由）
    - 操作策略（过夜/波段）
    """
    lines = []
    
    code = r.get('code', '')
    name = r.get('name', '')
    close = r.get('close', 0)
    change_pct = r.get('change_pct', 0)
    tier = r.get('tier', 'X')
    final = r.get('final_score', 0)
    overnight = r.get('overnight_score', 0)
    overnight_g = r.get('overnight_grade', '')
    fusion = r.get('fusion_score', 0)
    fusion_g = r.get('fusion_grade', '')
    pattern = r.get('pattern', 0)
    pattern_name = r.get('pattern_name', '')
    tactic_names = r.get('tactic_names', [])
    sectors = r.get('sectors', [])
    
    strat = r.get('strategy_type', {})
    strat_type = strat.get('type', '-') if isinstance(strat, dict) else '-'
    
    # 策略逻辑命中项
    reasons = r.get('reasons', [])
    # 从reasons提取关键信号，但排除已包含在pattern_name里的内容（避免重复）
    key_signals = []
    for s in reasons:
        if any(k in s for k in ['MACD', 'KDJ', 'RSI', '金叉', '绿灯', '倍量']):
            # 如果信号里已经包含pattern_name的内容，跳过
            if pattern_name and pattern_name != '-' and pattern_name in s:
                continue
            key_signals.append(s)
    
    # 组装命中项说明
    hit_items = []
    if overnight >= 10:
        hit_items.append(f"过夜分{overnight:.0f}分({overnight_g})")
    if fusion >= 6:
        hit_items.append(f"融合分{fusion:.0f}分({fusion_g})")
    if pattern > 0:
        hit_items.append(f"{pattern_name}")
    if tactic_names:
        hit_items.append(f"战法:{'+'.join(tactic_names)}")
    hit_items.extend(key_signals[:2])
    
    hit_description = ' | '.join(hit_items) if hit_items else '技术面共振'
    
    # 所属概念板块
    sector_str = ' / '.join(sectors[:3]) if sectors else '未分类'
    
    lines.append(f"")
    lines.append(f"┌─ {code} {name} [{tier}] 综合:{final:.2f}")
    lines.append(f"│  🏷️ 板块: {sector_str}")
    lines.append(f"│  📈 涨跌: {change_pct:+.2f}% | 💰 股价: ¥{close:.2f}")
    lines.append(f"│  🎯 命中: {hit_description}")
    lines.append(f"│  🚀 策略: 【{strat_type}】")
    if tactic_names:
        lines.append(f"│  ⚔️ 战法: {' + '.join(tactic_names)}")
    lines.append(f"└─")
    
    return lines


def _format_tactic_stock(r: dict) -> list:
    """格式化战法股票"""
    lines = []
    
    code = r.get('code', '')
    name = r.get('name', '')
    close = r.get('close', 0)
    change_pct = r.get('change_pct', 0)
    tier = r.get('tier', 'X')
    final = r.get('final_score', 0)
    tactic_names = r.get('tactic_names', [])
    sectors = r.get('sectors', [])
    sector_str = ' / '.join(sectors[:2]) if sectors else '未分类'
    
    lines.append(f"")
    lines.append(f"┌─ {code} {name} [{tier}] 综合:{final:.2f}")
    lines.append(f"│  🏷️ 板块: {sector_str}")
    lines.append(f"│  📈 涨跌: {change_pct:+.2f}% | 💰 股价: ¥{close:.2f}")
    lines.append(f"│  ⚔️ 战法: {' + '.join(tactic_names)}")
    lines.append(f"└─")
    
    return lines


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("A股动量选股系统 v3.2 — 完整版启动")
    print("=" * 80)
    
    start = time.time()
    
    # Step 1: iFinD主力流入
    main_force = fetch_main_force_top30()
    
    # Step 2: 自动提取热点板块 + 成分股
    hot_sectors, sector_stocks = fetch_hot_sectors_auto()
    
    # Step 3: 六池
    pools = load_all_pools_v3()
    
    # Step 4: 合并
    candidates = merge_candidates(main_force, sector_stocks, pools)
    
    if not candidates:
        print("\n❌ 候选池为空")
        return
    
    # Step 5: 历史K线
    kline_data = fetch_historical_klines(candidates)
    
    # Step 6: 实时K线补充（盘中用）
    kline_data = fetch_intraday_klines(candidates, kline_data)
    
    # Step 7: 完整版评分 + 战法
    results = run_full_scoring_with_tactics(candidates, kline_data)
    
    # Step 8: 输出
    output = format_output(results)
    print(output)
    
    # 保存
    date_str = datetime.now().strftime('%Y%m%d')
    out_file = RESULT_DIR / f'result_v32_{date_str}.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n💾 已保存: {out_file}")
    print(f"⏱️ 总耗时: {time.time() - start:.1f}秒")


if __name__ == '__main__':
    main()
