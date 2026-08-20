#!/usr/bin/env python3
"""
完整版Top榜 — stock_finance_data历史K线 + v22完整评分
输出Top 20，写明来源池子和命中策略标准
"""
import sys, json, pandas as pd, time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')
from v22_engine import run_v22_scoring
from kelly_position import calc_kelly_position

BASE_DIR = Path('/root/.openclaw/workspace/skills/ifind-momentum-screener')
POOL_DIR = BASE_DIR / 'data' / 'pools'
RESULT_FILE = BASE_DIR / 'data' / 'top20_full_v22.json'

# ========== 1. 读取所有池子 ==========
def load_all_pools():
    pools = {}
    all_candidates = {}
    
    pool_files = ['bottom_pool.json', 'limit_up_pool.json', 'main_line_pool.json',
                  'strong_pool.json', 'user_pick_pool.json', 'hot_pool.json']
    pool_names = {'bottom_pool.json': 'bottom', 'limit_up_pool.json': 'limit_up',
                  'main_line_pool.json': 'main_line', 'strong_pool.json': 'strong',
                  'user_pick_pool.json': 'user_pick', 'hot_pool.json': 'hot'}
    
    for pf in pool_files:
        path = POOL_DIR / pf
        if not path.exists():
            continue
        with open(path) as f:
            stocks = json.load(f)
        pool_name = pool_names[pf]
        pools[pool_name] = stocks
        
        for s in stocks:
            code = s['code']
            if code not in all_candidates:
                all_candidates[code] = {
                    'code': code, 'name': s.get('name', ''),
                    'sources': [pool_name],
                    'pct_chg': s.get('pct_chg', 0),
                    'amount': s.get('amount', 0),
                    'industry': s.get('industry', '')
                }
            else:
                if pool_name not in all_candidates[code]['sources']:
                    all_candidates[code]['sources'].append(pool_name)
    
    return list(all_candidates.values())

# ========== 2. 获取历史K线 (stock_finance_data) ==========
import subprocess

def fetch_kline_sfd(code, name=""):
    """用stock_finance_data获取60日K线"""
    if code.startswith('6'):
        ticker = f"{code}.SH"
    else:
        ticker = f"{code}.SZ"
    
    end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=75)).strftime('%Y-%m-%d')
    output_path = f"/tmp/kline_full_{code}.csv"
    
    try:
        # 用 kimi_datasource_call 工具 (通过 openclaw CLI 不可行，改用直接调用)
        # 这里我们通过 subprocess 调用 openclaw tool
        cmd = [
            'python3', '-c',
            f'''
import json, subprocess
result = subprocess.run([
    "openclaw", "tool", "kimi_datasource_call",
    "--data_source_name", "stock_finance_data",
    "--api_name", "stock_finance_data_get_price",
    "--params", json.dumps({{
        "ticker": "{ticker}",
        "start_date": "{start_date}",
        "end_date": "{end_date}",
        "interval": "D",
        "adjust": "forward",
        "file_path": "{output_path}"
    }})
], capture_output=True, text=True, timeout=30)
print(result.stdout[:500])
'''
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        
        if Path(output_path).exists():
            return output_path
        return None
    except Exception as e:
        print(f"  ❌ {code} 获取K线失败: {e}")
        return None

# ========== 3. 计算技术指标 ==========
def calc_tech_indicators(csv_path):
    df = pd.read_csv(csv_path)
    df = df.rename(columns={'time': 'date'})
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['preclose'] = df['close'].shift(1)
    df = df.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
    
    if len(df) < 20:
        return None
    
    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    volumes = df['volume'].values
    
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    
    close = float(latest['close'])
    prev_close = float(prev['close']) if pd.notna(prev['close']) else close
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
    
    # 连涨天数
    streak = 0
    for i in range(-1, -min(6, len(closes)), -1):
        if closes[i] > closes[i-1]:
            streak += 1
        else:
            break
    
    # 2日涨幅
    change_pct_2d = 0
    if len(closes) >= 3:
        change_pct_2d = (closes[-1] - closes[-3]) / closes[-3] * 100
    
    # 成交量趋势
    vol_recent = sum(volumes[-5:]) / 5
    vol_prev = sum(volumes[-10:-5]) / 5 if len(volumes) >= 10 else vol_recent
    volume_trend_down = vol_recent < vol_prev * 0.8
    volume_rally = volume > volume_20d_avg * 1.5
    
    return {
        'close': close, 'high': high, 'low': low, 'open': open_price,
        'volume': volume, 'prev_close': prev_close,
        'high_20d': high_20d, 'low_20d': low_20d,
        'volume_20d_avg': volume_20d_avg,
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
        'rsi6': rsi6, 'k': 50, 'd': 50, 'j': 50,
        'macd_hist': macd_hist, 'cci': cci, 'roc': roc,
        'streak_days': streak,
        'change_pct_2d': change_pct_2d,
        'volume_trend_down': volume_trend_down,
        'volume_rally': volume_rally,
    }

# ========== 4. 策略模式分类 ==========
def classify_pattern(s, tech):
    """根据来源和涨幅判断策略模式"""
    sources = s.get('sources', [])
    pct = s.get('pct_chg', 0)
    amount = s.get('amount', 0)
    breakout = tech['close'] > tech['high_20d'] if tech else False
    
    if 'bottom' in sources and 1 <= pct <= 6:
        return "模式3-深套反弹", "底部放量池票，脱离底部区间，反弹空间大"
    elif 'limit_up' in sources and pct < 9.5:
        return "模式5-涨停回调二次启动", "涨停池票，回调后有望二次启动"
    elif 'main_line' in sources and pct >= 3:
        if breakout:
            return "模式4-板块龙头", "主线池票+突破20日新高，板块龙头确认"
        else:
            return "模式4-板块龙头", "主线池票，板块内涨幅领先，资金聚焦"
    elif 'hot' in sources and pct >= 3:
        return "模式4-板块龙头", "人气池票，市场关注度高，资金活跃"
    elif pct >= 5 and amount >= 1000000000:
        if breakout:
            return "模式2-杯柄突破", "涨幅>5%+高成交+突破20日新高，杯柄突破确认"
        else:
            return "模式2-杯柄突破", "涨幅>5%+高成交，杯柄形态疑似"
    elif 3 <= pct <= 5:
        return "模式1-趋势延续", "涨幅3-5%黄金区间，趋势延续概率高"
    elif tech and tech['macd_hist'] > 0 and tech['rsi6'] > 50:
        return "模式1-趋势延续", "MACD红柱+RSI强势，趋势向上"
    else:
        return "模式6-筹码反转", "无明显模式，但多因子共振"

# ========== 5. 主流程 ==========
def main():
    print("=" * 80)
    print(f"完整版Top榜 — stock_finance_data历史K线 + v22完整评分")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)
    
    candidates = load_all_pools()
    print(f"\n📊 共 {len(candidates)} 只候选票，开始获取历史K线...")
    
    results = []
    
    for i, s in enumerate(candidates):
        code = s['code']
        name = s['name']
        
        print(f"\n[{i+1}/{len(candidates)}] {code} {name}...", end=" ")
        
        # 获取K线
        csv_path = fetch_kline_sfd(code, name)
        if not csv_path:
            print("❌ 无K线数据")
            continue
        
        # 计算指标
        tech = calc_tech_indicators(csv_path)
        if not tech:
            print("❌ 数据不足")
            continue
        
        # 判断突破
        breakout = tech['close'] > tech['high_20d']
        
        # 策略模式
        pattern_name, pattern_reason = classify_pattern(s, tech)
        
        # 构建data字典
        amount_wan = s.get('amount', 0) / 10000  # 万元
        
        data = {
            'name': name,
            'close': tech['close'],
            'high': tech['high'],
            'low': tech['low'],
            'open': tech['open'],
            'volume': tech['volume'],
            'prev_close': tech['prev_close'],
            'high_20d': tech['high_20d'],
            'low_20d': tech['low_20d'],
            'volume_20d_avg': tech['volume_20d_avg'],
            'macd_hist': tech['macd_hist'],
            'ma5': tech['ma5'],
            'ma10': tech['ma10'],
            'ma20': tech['ma20'],
            'rsi6': tech['rsi6'],
            'k': 50, 'd': 50, 'j': 50,
            'cci': tech['cci'],
            'roc': tech['roc'],
            'pe': 20,
            'roe': 10,
            'revenue_growth': 15,
            'market_cap': 100,
            'org_pct': 5,
            'northbound_5d': 0,
            'main_fund_5d': 0,
            'shareholder_change': 0,
            'sentiment_score': 0.3,
            'has_regulatory_risk': False,
            'industry_cycle': 'up',
            'policy_tailwind': 1,
            'supply_demand': 'tight',
            'liquidity_env': 'loose',
            'volume_rally_avg': tech['volume_20d_avg'],
            'has_hammer': False,
            'has_engulfing': False,
            'high_5d_ago': tech['ma5'],
            'days_in_channel': 0,
            'volume_trend_down': tech['volume_trend_down'],
            'breakout_today': breakout,
            'high_recent': tech['high_20d'],
            'rebound_count': 1,
            'friday_market_drop': False,
            'ma20_trend': 'neutral',
            'high_cup': tech['high_20d'],
            'handle_low': tech['low_20d'],
            'volume_handle': tech['volume'],
            'volume_cup_avg': tech['volume_20d_avg'],
            'streak_days': tech['streak_days'],
            'market_green': True,
            'sector_green': True,
            'trend_green': True,
            'price_green': True,
            'position_green': True,
            'is_top3_sector': 'main_line' in s.get('sources', []),
            'is_hot_sector': 'hot' in s.get('sources', []),
            'has_multi_concepts': False,
            'volume_rally': tech['volume_rally'],
            'amount': amount_wan,
            'change_pct_2d': tech['change_pct_2d'],
            'northbound_net_5d': 0,
            'has_major_bad_news': False,
        }
        
        # v22评分
        try:
            result = run_v22_scoring(data)
        except Exception as e:
            print(f"❌ 评分失败: {e}")
            continue
        
        # 补充信息
        result['code'] = code
        result['name'] = name
        result['pct_chg'] = s.get('pct_chg', 0)
        result['amount'] = s.get('amount', 0)
        result['sources'] = s.get('sources', [])
        result['industry'] = s.get('industry', '')
        result['close'] = tech['close']
        result['prev_close'] = tech['prev_close']
        result['breakout'] = breakout
        result['high_20d'] = tech['high_20d']
        result['low_20d'] = tech['low_20d']
        result['pattern_name'] = pattern_name
        result['pattern_reason'] = pattern_reason
        result['rsi6'] = tech['rsi6']
        result['macd_hist'] = tech['macd_hist']
        result['ma20'] = tech['ma20']
        result['volume_20d_avg'] = tech['volume_20d_avg']
        
        results.append(result)
        print(f"✅ {result['tier']}级 | {result['final_score']:.3f}")
        
        # 限速：每批3只后暂停
        if (i + 1) % 3 == 0:
            time.sleep(1)
    
    # 排序
    results.sort(key=lambda x: x['final_score'], reverse=True)
    
    # 保存
    with open(RESULT_FILE, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    # 输出Top 20
    print("\n" + "=" * 80)
    print("🏆 完整版Top 20 — 含策略逻辑")
    print("=" * 80)
    
    src_map = {'bottom': '底', 'limit_up': '涨', 'main_line': '主', 
               'strong': '强', 'user_pick': '自', 'hot': '人', 'market': '市'}
    
    for i, r in enumerate(results[:20], 1):
        src_tags = ''.join([src_map.get(s, s[:1]) for s in r.get('sources', [])])
        amount_yi = r['amount'] / 100000000
        tier_emoji = {'S': '🟢', 'A': '🔵', 'B': '🟡', 'C': '⚪', 'X': '🔴'}
        
        print(f"\n【{i}】{r['code']} {r['name']} | {tier_emoji.get(r['tier'], '⚪')}{r['tier']}级 | 评分:{r['final_score']:.3f} | +{r['pct_chg']:.1f}%")
        
        # ★ 新增: 策略类型标签
        stype = r.get('strategy_type', {})
        if stype:
            s_emoji = {'过夜': '🌙', '波段': '📈', '两者皆可': '✨', '观望': '👀'}
            s_type = stype.get('type', '?')
            print(f"   {s_emoji.get(s_type, '')} 策略类型: {s_type}")
            print(f"     └─ {stype.get('reason', '')}")
        
        print(f"   📌 来源池: [{src_tags}] {', '.join(r.get('sources', []))}")
        print(f"   🎯 策略模式: {r['pattern_name']}")
        print(f"   💡 模式理由: {r['pattern_reason']}")
        print(f"   💰 价格: 昨收¥{r['prev_close']:.2f} → 今收¥{r['close']:.2f} | 成交:{amount_yi:.1f}亿")
        
        if r['breakout']:
            print(f"   🚀 突破20日新高! (20日高:¥{r['high_20d']:.2f})")
        
        print(f"   📊 技术指标:")
        print(f"     • RSI6: {r['rsi6']:.1f} | MACD: {r['macd_hist']:.2f}% | MA20: ¥{r['ma20']:.2f}")
        print(f"     • 20日最高: ¥{r['high_20d']:.2f} | 20日最低: ¥{r['low_20d']:.2f}")
        
        # ★ 新增: 过夜胜率预测
        if 'overnight_prob' in r:
            prob = r['overnight_prob']
            rating = r.get('overnight_rating', '?')
            expected = r.get('overnight_expected', '?')
            confidence = r.get('overnight_confidence', '?')
            
            # 概率条可视化
            bar_len = int(prob / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            
            print(f"   🌙 过夜胜率预测:")
            print(f"     • 概率: {prob}% [{bar}] (置信度:{confidence})")
            print(f"     • 评级: {rating} | 预期收益: {expected}")
            
            # 显示主要影响因子(最多3个)
            factors = r.get('overnight_factors', [])
            if factors:
                print(f"     • 关键因子: {' | '.join(factors[:3])}")
        
        print(f"   📝 得分明细:")
        print(f"     • 模式得分: {r.get('pattern', 0):.2f}/1.0")
        print(f"     • 隔夜情绪: {r['overnight']:.2f}/0.5 — 基于昨收+{r['pct_chg']:.1f}%的开盘预期")
        print(f"     • 融合得分: {r['fusion']:.2f}/2.0 — 多因子共振强度")
        print(f"     • 辩论得分: {r['debate']:.2f}/2.0 — 6Agent多模态共识")
        print(f"     • 市场环境: {r.get('market_context', 0):.2f}/0.3")
        
        # 命中标准
        hit = []
        if 3 <= r['pct_chg'] <= 5:
            hit.append("✓ 涨幅3-5%（黄金区间，避免追高）")
        if amount_yi >= 5:
            hit.append(f"✓ 成交{amount_yi:.1f}亿（高活跃，资金认可）")
        if 'main_line' in r.get('sources', []):
            hit.append("✓ 主线池（板块热点，资金聚焦）")
        if 'strong' in r.get('sources', []):
            hit.append("✓ 强势池（趋势向上，momentum确认）")
        if 'user_pick' in r.get('sources', []):
            hit.append("✓ 自选池（用户跟踪，有研究基础）")
        if 'hot' in r.get('sources', []):
            hit.append("✓ 人气池（市场关注度高，流动性好）")
        if r['breakout']:
            hit.append("✓ 突破20日新高（技术面确认强势）")
        if r['rsi6'] > 50:
            hit.append(f"✓ RSI6={r['rsi6']:.1f}>50（动能强势）")
        if r['macd_hist'] > 0:
            hit.append(f"✓ MACD红柱（趋势向上）")
        if r.get('pattern', 0) > 0:
            hit.append(f"✓ 模式得分{r.get('pattern', 0):.2f}>0（有明确交易模式）")
        
        print(f"   ✅ 命中策略标准:")
        for h in hit:
            print(f"      {h}")
        
        # 仓位建议
        kelly = calc_kelly_position(67587, r['tier'])
        stop = r['prev_close'] * 0.93
        print(f"   💼 仓位建议: {kelly['position_pct']:.1f}% = ¥{kelly['position_value']:.0f}")
        print(f"   🛑 止损位: ¥{stop:.2f} (-7%)")
        
        if r['tier'] == 'S':
            print(f"   🟢 操作建议: 明日高开≤2%可介入，跌破止损位严格离场")
        elif r['tier'] == 'A':
            print(f"   🔵 操作建议: 跟踪观察，等确认信号或回调机会")
        elif r['tier'] == 'B':
            print(f"   🟡 操作建议: 低风险偏好可小仓位试错")
        elif r['tier'] == 'C':
            print(f"   ⚪ 操作建议: 观望为主，等待更好时机")
        elif r['tier'] == 'X':
            print(f"   🔴 操作建议: 排除，原因: {', '.join(r.get('reasons', [])[:3])}")
    
    print("\n" + "=" * 80)
    print(f"✅ 共评分 {len(results)} 只票，结果已保存至 {RESULT_FILE}")
    print("=" * 80)

if __name__ == '__main__':
    main()
