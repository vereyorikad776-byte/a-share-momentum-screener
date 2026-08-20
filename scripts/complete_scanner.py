#!/usr/bin/env python3
"""
complete_scanner.py — 完整选股流程 v2.2.1
支持6大池子：底部放量/涨停/主线/强势/自选/人气
"""

import sys, warnings, json, time
from pathlib import Path
warnings.filterwarnings('ignore')
sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
from ifind_call import call
from v21_engine import run_v21_pipeline
from kelly_position import calc_kelly_position
from feedback_learning import log_prediction, update_pattern_stats

# ─── 多数据源配置 ───
BAOSTOCK_PRIMARY = True   # Baostock是否作为主历史数据源
SIMPLIFIED_MODE = False   # 是否使用简化评分（无历史K线）

# 检测Baostock可用性
def check_baostock():
    """检测Baostock是否可用"""
    try:
        import baostock as bs
        lg = bs.login()
        if lg.error_code == '0':
            bs.logout()
            return True
        try:
            bs.logout()
        except:
            pass
    except:
        pass
    return False

# 全局检测一次
BAOSTOCK_AVAILABLE = check_baostock()
if not BAOSTOCK_AVAILABLE:
    print("⚠️ Baostock不可用（黑名单），启用简化评分模式")
    SIMPLIFIED_MODE = True
    BAOSTOCK_PRIMARY = False
else:
    print("✅ Baostock可用，启用完整评分模式")

# ─── 简化评分函数（iFinD纯数据） ───
def simple_score_v22(s):
    """v2.2简化评分（纯iFinD实时数据，无历史K线）"""
    score = 0.0
    reasons = []
    
    pct = s.get('pct_chg', 0)
    amount = s.get('amount', 0)
    sources = s.get('sources', [])
    
    # 涨幅得分 (0-0.4)
    if 3 <= pct <= 5:
        score += 0.35
        reasons.append('涨幅3-5%(黄金区间)')
    elif 5 < pct <= 8:
        score += 0.30
        reasons.append('涨幅5-8%(偏强)')
    elif 1 <= pct < 3:
        score += 0.20
        reasons.append('涨幅1-3%(温和)')
    elif pct > 8:
        score += 0.10
        reasons.append('涨幅>8%(追高)')
    elif -3 <= pct < 0:
        score += 0.05
        reasons.append('微跌(潜在低吸)')
    else:
        score -= 0.15
        reasons.append('跌幅过大(排除)')
    
    # 成交额得分 (0-0.3)
    if amount >= 1000000000:  # 10亿
        score += 0.30
        reasons.append('成交>10亿(极高活跃)')
    elif amount >= 500000000:  # 5亿
        score += 0.25
        reasons.append('成交>5亿(高活跃)')
    elif amount >= 100000000:  # 1亿
        score += 0.15
        reasons.append('成交>1亿(活跃)')
    elif amount >= 50000000:  # 5000万
        score += 0.10
        reasons.append('成交>5000万')
    
    # 量价齐升
    if pct > 3 and amount > 100000000:
        score += 0.15
        reasons.append('量价齐升')
    
    # 涨停排除
    if pct > 9.5:
        score -= 0.40
        reasons.append('涨停(无法买入)')
    
    # 池子来源加分
    if 'bottom' in sources:
        score += 0.15
        reasons.append('[底部放量池]')
    if 'user_pick' in sources:
        score += 0.10
        reasons.append('[自选池]')
    if 'limit_up' in sources:
        score += 0.05
        reasons.append('[涨停池]')
    if 'main_line' in sources:
        score += 0.05
        reasons.append('[主线池]')
    if 'hot' in sources:
        score += 0.05
        reasons.append('[人气池]')
    if 'strong' in sources:
        score += 0.05
        reasons.append('[强势池]')
    
    s['score'] = score
    s['reasons'] = reasons
    
    if score >= 0.7:
        s['tier'] = 'S'
    elif score >= 0.5:
        s['tier'] = 'A'
    elif score >= 0.3:
        s['tier'] = 'B'
    elif score >= 0.1:
        s['tier'] = 'C'
    else:
        s['tier'] = 'X'
    
    return s

# ─── 池子配置 ───
POOL_DIR = Path('/root/.openclaw/workspace/skills/ifind-momentum-screener/data/pools')
CAPITAL = 67587

# 6大池子配置
POOL_CONFIG = {
    'bottom': {'file': 'bottom_pool.json', 'name': '底部放量池', 'max_size': 20},
    'limit_up': {'file': 'limit_up_pool.json', 'name': '涨停池', 'max_size': 20},
    'main_line': {'file': 'main_line_pool.json', 'name': '主线池', 'max_size': 20},
    'strong': {'file': 'strong_pool.json', 'name': '强势池', 'max_size': 20},
    'user_pick': {'file': 'user_pick_pool.json', 'name': '自选池', 'max_size': 20},
    'hot': {'file': 'hot_pool.json', 'name': '人气池', 'max_size': 20},
}


def load_pools():
    """读取6大池子"""
    pools = {}
    all_codes = set()
    
    for pool_key, config in POOL_CONFIG.items():
        pool_file = POOL_DIR / config['file']
        try:
            with open(pool_file) as f:
                data = json.load(f)
            
            # 兼容两种格式
            if isinstance(data, list):
                entries = data
            else:
                entries = data.get('codes', [])
            
            # 提取代码
            codes = []
            for entry in entries:
                if isinstance(entry, dict):
                    code = entry.get('code', '')
                    name = entry.get('name', '')
                else:
                    code = str(entry)
                    name = ''
                if code:
                    code = code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
                    codes.append({'code': code, 'name': name, 'source': pool_key})
                    all_codes.add(code)
            
            pools[pool_key] = codes
            print(f"  ✅ {config['name']}: {len(codes)}只")
        except Exception as e:
            print(f"  ⚠️ {config['name']}读取失败: {e}")
            pools[pool_key] = []
    
    return pools, all_codes


def fetch_limit_up_stocks():
    """自动抓取今日涨停票"""
    print("  🔍 抓取涨停池...")
    try:
        result = call('stock', 'search_stocks', {
            'query': '主板 涨幅大于9.5 成交额大于1000万',
            'limit': 30
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
                        
                        if board == '主板' and not name.startswith('*ST') and not name.startswith('ST'):
                            stocks.append({
                                'code': code, 'name': name,
                                'pct_chg': pct_chg,
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'source': 'limit_up'
                            })
                    except:
                        pass
        
        # 保存到limit_up_pool.json
        with open(POOL_DIR / 'limit_up_pool.json', 'w') as f:
            json.dump(stocks[:20], f, ensure_ascii=False, indent=2)
        
        print(f"  ✅ 涨停池更新: {len(stocks)}只")
        return stocks
    except Exception as e:
        print(f"  ❌ 抓取涨停池失败: {e}")
        return []


def fetch_main_line_stocks():
    """自动抓取主线热点票（基于iFinD板块资金流）"""
    print("  🔍 抓取主线池...")
    try:
        # 获取热点板块
        result = call('stock', 'search_stocks', {
            'query': '板块资金净流入排名前10',
            'limit': 10
        })
        
        # 简化：扫描涨幅靠前+成交活跃的票作为主线候选
        result = call('stock', 'search_stocks', {
            'query': '主板 涨幅大于3 成交额大于5000万',
            'limit': 50
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
                                'pct_chg': pct_chg, 'amount': amount,
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'source': 'main_line'
                            })
                    except:
                        pass
        
        # 保存到main_line_pool.json
        with open(POOL_DIR / 'main_line_pool.json', 'w') as f:
            json.dump(stocks[:20], f, ensure_ascii=False, indent=2)
        
        print(f"  ✅ 主线池更新: {len(stocks)}只")
        return stocks
    except Exception as e:
        print(f"  ❌ 抓取主线池失败: {e}")
        return []


def fetch_hot_stocks():
    """抓取人气票（龙虎榜+活跃票）"""
    print("  🔍 抓取人气池...")
    try:
        # 扫描换手率高的活跃票
        result = call('stock', 'search_stocks', {
            'query': '主板 换手率大于5 成交额大于3000万',
            'limit': 30
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
                                'pct_chg': pct_chg, 'amount': amount,
                                'date': datetime.now().strftime('%Y-%m-%d'),
                                'source': 'hot'
                            })
                    except:
                        pass
        
        # 保存到hot_pool.json
        with open(POOL_DIR / 'hot_pool.json', 'w') as f:
            json.dump(stocks[:20], f, ensure_ascii=False, indent=2)
        
        print(f"  ✅ 人气池更新: {len(stocks)}只")
        return stocks
    except Exception as e:
        print(f"  ❌ 抓取人气池失败: {e}")
        return []


def market_scan():
    """iFinD市场粗筛"""
    print("\n📡 Step 2: iFinD市场扫描...")
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
                            'pct_chg': pct_chg, 'amount': amount,
                            'source': 'market'
                        })
                except:
                    pass
    
    print(f"✅ 市场扫描: {len(stocks)}只")
    return stocks


def merge_candidates(pools, market_stocks):
    """合并6大池子+市场，去重"""
    print("\n🔄 Step 3: 合并去重...")
    all_candidates = {}
    
    # 先加池子里的（优先级高）
    for pool_name, entries in pools.items():
        for entry in entries:
            code = entry['code']
            if code not in all_candidates:
                all_candidates[code] = {
                    'code': code,
                    'name': entry.get('name', ''),
                    'sources': [pool_name],
                    'source': pool_name
                }
            else:
                if pool_name not in all_candidates[code]['sources']:
                    all_candidates[code]['sources'].append(pool_name)
    
    # 再加市场的
    for s in market_stocks:
        code = s['code']
        if code in all_candidates:
            all_candidates[code]['sources'].append('market')
            if 'pct_chg' not in all_candidates[code]:
                all_candidates[code]['pct_chg'] = s['pct_chg']
            if 'amount' not in all_candidates[code]:
                all_candidates[code]['amount'] = s['amount']
        else:
            all_candidates[code] = {
                'code': code,
                'name': s['name'],
                'pct_chg': s['pct_chg'],
                'amount': s['amount'],
                'sources': ['market'],
                'source': 'market'
            }
    
    return list(all_candidates.values())


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
    
    deltas = [closes[i] - closes[i-1] for i in range(-6, 0)]
    gains = sum(d for d in deltas if d > 0)
    losses = sum(-d for d in deltas if d < 0)
    rsi6 = 100 * gains / (gains + losses) if (gains + losses) > 0 else 50
    
    ema12 = sum(closes[-12:]) / 12
    ema26 = sum(closes[-26:]) / 26 if len(closes) >= 26 else ema12
    macd_hist = (ema12 - ema26) / ema26 * 100 if ema26 > 0 else 0
    
    tp = (high + low + close) / 3
    tp_sma = sum((h+l+c)/3 for h,l,c in zip(highs[-20:], lows[-20:], closes[-20:])) / 20
    mean_dev = sum(abs((h+l+c)/3 - tp_sma) for h,l,c in zip(highs[-20:], lows[-20:], closes[-20:])) / 20
    cci = (tp - tp_sma) / (0.015 * mean_dev) if mean_dev > 0 else 0
    
    roc = (close - closes[-10]) / closes[-10] * 100 if closes[-10] > 0 else 0
    
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
    print(f"📊 A股动量选股 v2.2 — 6大池子完整流程")
    print(f"时间: {now.strftime('%Y-%m-%d %H:%M')}")
    if SIMPLIFIED_MODE:
        print("⚠️ 简化模式 (Baostock不可用，使用iFinD纯数据评分)")
    else:
        print("✅ 完整模式 (Baostock历史K线 + v22评分)")
    print("=" * 60)
    print()
    
    # Step 1: 读取6大池子
    print("📦 Step 1: 读取6大池子...")
    
    # 自动更新可自动抓取的池子
    fetch_limit_up_stocks()
    fetch_main_line_stocks()
    fetch_hot_stocks()
    
    # 重新加载所有池子
    pools, pool_codes = load_pools()
    total_pool = sum(len(v) for v in pools.values())
    print(f"\n✅ 池子共 {total_pool} 只")
    print()
    
    # Step 2: iFinD市场扫描
    market_stocks = market_scan()
    print()
    
    # Step 3: 合并去重
    candidates = merge_candidates(pools, market_stocks)
    print(f"✅ 合并后: {len(candidates)}只（去重）")
    print()
    
    # Step 4 & 5: 评分
    results = []
    
    if not SIMPLIFIED_MODE:
        # ===== 完整模式: Baostock历史K线 + v22评分 =====
        print("📈 Step 4: Baostock历史K线...")
        bs.login()
        print("✅ 已连接")
        print()
        print("🔬 Step 5: v2.2精筛...")
        
        for i, c in enumerate(candidates):
            code = c['code']
            name = c.get('name', '')
            sources = c.get('sources', [])
            
            print(f"  [{i+1}/{len(candidates)}] {code} {name or '?'}...", end=' ')
            
            df = fetch_kline(code)
            time.sleep(3)  # 防超时
            
            if df is None:
                print("❌ 无K线")
                continue
            
            tech = calc_indicators(df)
            if tech is None:
                print("❌ 数据不足")
                continue
            
            if 'pct_chg' not in c:
                c['pct_chg'] = ((tech['close'] - tech['prev_close']) / tech['prev_close'] * 100) if tech['prev_close'] else 0
            
            result = run_pipeline(code, name, tech)
            result['pct_chg'] = c.get('pct_chg', 0)
            result['amount'] = c.get('amount', 0)
            result['close'] = tech['close']
            result['prev_close'] = tech['prev_close']
            result['sources'] = sources
            
            tier_icon = "🟢" if result['tier'] == 'S' else "🟡" if result['tier'] == 'A' else "🟡" if result['tier'] == 'B' else "⚪"
            print(f"✅ {tier_icon} {result['tier']} {result['final_score']:.3f}")
            
            results.append(result)
        
        bs.logout()
        
    else:
        # ===== 简化模式: iFinD纯数据 + 简化评分 =====
        print("📈 Step 4: 简化评分模式 (iFinD纯数据)")
        print("🔬 Step 5: v2.2简化评分...")
        
        for i, c in enumerate(candidates):
            code = c['code']
            name = c.get('name', '')
            
            print(f"  [{i+1}/{len(candidates)}] {code} {name or '?'}...", end=' ')
            
            simple_score_v22(c)
            
            tier_icon = "🟢" if c['tier'] == 'S' else "🟡" if c['tier'] == 'A' else "🟡" if c['tier'] == 'B' else "⚪"
            print(f"✅ {tier_icon} {c['tier']} {c['score']:.2f}")
            
            results.append(c)
    
    # ★ 反馈学习: 记录预测日志
    today = datetime.now().strftime('%Y%m%d')
    for r in results:
        if r.get('tier') in ['S', 'A', 'B']:
            try:
                pred = {
                    'overnight_score': r.get('overnight_score', 0),
                    'fusion_score': r.get('fusion_score', 0),
                    'debate_score': r.get('debate_score', 0),
                    'pattern': r.get('pattern_name', '无'),
                    'tier': r.get('tier', 'X'),
                    'strategy_type': r.get('strategy_type', {}).get('type', '?'),
                    'overnight_prob': r.get('overnight_prob', 50),
                }
                log_prediction(r.get('code', ''), r.get('name', ''), pred, date=today)
            except Exception as e:
                print(f"⚠️ 预测日志记录失败: {e}")
    
    # Step 6: 排序输出
    if not SIMPLIFIED_MODE:
        results.sort(key=lambda x: x['final_score'], reverse=True)
        score_key = 'final_score'
    else:
        results.sort(key=lambda x: x['score'], reverse=True)
        score_key = 'score'
    
    s_a_b = [r for r in results if r['tier'] in ['S', 'A', 'B']]
    
    print()
    print("=" * 60)
    print("🏆 TOP 推荐（S/A/B级）")
    print("=" * 60)
    
    # ★ 反馈学习: 显示命中率
    try:
        from feedback_learning import calc_hit_rate
        hit_stats = calc_hit_rate(days=20)
        if hit_stats['total'] > 0:
            print(f"📊 近20日命中率: {hit_stats['hit_rate']}% ({hit_stats['hit']}/{hit_stats['total']})")
    except Exception:
        pass
    
    print()
    
    if not s_a_b:
        print("⚠️ 未发现S/A/B级股票")
        print("\n📋 C级备选:")
        for i, r in enumerate(results[:10], 1):
            src = ', '.join(r.get('sources', ['unknown']))
            score_val = r.get('final_score', r.get('score', 0))
            print(f"  {i}. {r['code']} {r['name']}: C级 {score_val:.3f} ({src})")
    else:
        for i, r in enumerate(s_a_b[:10], 1):
            kelly = calc_kelly_position(CAPITAL, r['tier'])
            stop = r.get('prev_close', r.get('close', 0)) * 0.93
            src = ', '.join(r.get('sources', ['unknown']))
            score_val = r.get('final_score', r.get('score', 0))
            
            print(f"【{i}】{r['code']} {r['name']}")
            print(f"   评级: {r['tier']} | 评分: {score_val:.3f} | 涨幅: {r['pct_chg']:+.2f}%")
            print(f"   来源: {src}")
            
            if not SIMPLIFIED_MODE:
                print(f"   隔夜: {r.get('overnight', 0):.1f} | 融合: {r.get('fusion', 0):.1f} | 辩论: {r.get('debate', 0):.2f}")
                # ★ 新增: 过夜胜率
                if 'overnight_prob' in r:
                    prob = r['overnight_prob']
                    rating = r.get('overnight_rating', '?')
                    print(f"   🌙 过夜胜率: {prob}% [{rating}] 预期:{r.get('overnight_expected', '?')}")
            else:
                reasons = r.get('reasons', [])
                print(f"   逻辑: {', '.join(reasons[:3])}")
                # 简化模式也显示过夜胜率
                if 'overnight_prob' in r:
                    print(f"   🌙 过夜胜率: {r['overnight_prob']}% [{r.get('overnight_rating', '?')}]")
            
            print(f"   仓位: {kelly['position_pct']:.1f}% = ¥{kelly['position_value']:.0f}")
            if stop > 0:
                print(f"   止损: ¥{stop:.2f}")
            print()
    
    # 按来源统计
    print("=" * 60)
    print("📊 来源统计")
    print("=" * 60)
    source_stats = {}
    for r in results:
        for src in r.get('sources', []):
            if src not in source_stats:
                source_stats[src] = {'count': 0, 's_a_b': 0}
            source_stats[src]['count'] += 1
            if r['tier'] in ['S', 'A', 'B']:
                source_stats[src]['s_a_b'] += 1
    
    for src, stats in source_stats.items():
        pool_name = POOL_CONFIG.get(src, {}).get('name', src)
        print(f"  {pool_name}: {stats['count']}只 (S/A/B: {stats['s_a_b']}只)")


if __name__ == "__main__":
    main()
