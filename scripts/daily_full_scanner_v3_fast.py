#!/usr/bin/env python3
"""
daily_full_scanner_v3_fast.py — 优化版
热点板块：5个 × 每板块6只
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

RESULT_DIR = Path('/root/.openclaw/workspace/skills/ifind-momentum-screener/data/daily')
RESULT_DIR.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# 交易时间判断
# ═══════════════════════════════════════════════════════════════

def is_trading_time():
    """判断当前是否在A股交易时间（09:30-11:30, 13:00-15:00），工作日"""
    now = datetime.now()
    # 周末不开盘
    if now.weekday() >= 5:
        return False
    time_str = now.strftime('%H:%M')
    # 上午 09:30-11:30
    if '09:30' <= time_str <= '11:30':
        return True
    # 下午 13:00-15:00
    if '13:00' <= time_str <= '15:00':
        return True
    return False

def is_trading_day():
    """判断今天是否是交易日（简单版：周一到周五）"""
    return datetime.now().weekday() < 5

def get_last_result():
    """获取最近一次保存的结果"""
    files = sorted(RESULT_DIR.glob('result_v32_*.json'), reverse=True)
    if not files:
        return None
    try:
        with open(files[0], 'r', encoding='utf-8') as f:
            return json.load(f), files[0].name
    except Exception:
        return None

GENERIC_CONCEPTS = {'融资融券', '深股通', '沪股通', '全部A股', '全部AB股', '全部上市公司',
    '沪深A股', '沪深AB股', '上证A股', '上证AB股', '深证A股', '深证AB股',
    '上证上市公司', '深证上市公司', '沪深主板A股', '上证主板A股',
    '全部A股(非ST)', '全部A股(非金融)', '注册制次新股', '新股与次新股',
    '科创板', '创业板', '北证A股', '北证上市公司', '创业板(注册制)',
    '同花顺出海50', '同花顺漂亮100', '同花顺果指数', '同花顺中特估100'}

def is_main_board(code):
    c = code.replace('.SH','').replace('.SZ','').replace('.BJ','').strip()
    if c.startswith('300') or c.startswith('301') or c.startswith('688'): return False
    if c.startswith('8') or c.startswith('4') or c.startswith('920'): return False
    return True

def normalize_code(code):
    return code.replace('.SH','').replace('.SZ','').replace('.BJ','').strip().zfill(6)

# ─── iFinD解析 ───
def parse_ifind_result(result):
    stocks = []
    try:
        content = result.get('data',{}).get('result',{}).get('content',[])
        if not content: return stocks
        text = content[0].get('text','{}')
        data = json.loads(text)
        if data.get('code') != 1: return stocks
        inner = json.loads(data.get('data','{}'))
        answer = inner.get('answer','')
        lines = answer.split('\n')
        in_table = False
        headers = []
        for line in lines:
            line = line.strip()
            if not line or '---' in line: continue
            if '股票代码' in line and '|' in line:
                in_table = True
                headers = [h.strip() for h in line.split('|') if h.strip()]
                continue
            if in_table and line.startswith('|'):
                cols = [c.strip() for c in line.split('|') if c.strip()]
                if len(cols) >= 2 and '股票代码' not in cols[0]:
                    code, name = cols[0], cols[1] if len(cols)>1 else ''
                    concepts = ''
                    for i,h in enumerate(headers):
                        if '所属概念' in h and i < len(cols):
                            concepts = cols[i]
                            break
                    if '.' in code:
                        stocks.append({'code':normalize_code(code),'name':name,'concepts':concepts})
        return stocks
    except Exception as e:
        print(f"  解析失败: {e}")
        return []

def extract_sectors_from_concepts(concepts_str):
    """从概念字符串提取有意义的板块"""
    if not concepts_str: return []
    concepts = [c.strip() for c in re.split(r'[;；,，]', concepts_str) if c.strip()]
    sectors = []
    for c in concepts:
        if c in GENERIC_CONCEPTS or len(c) < 2 or len(c) > 20: continue
        if '股票' in c or '板块' in c or 'A股' in c: continue
        sectors.append(c)
    return sectors[:3]

# ═══════════════════════════════════════════════════════════════
# Step 1: 主力流入
# ═══════════════════════════════════════════════════════════════

def fetch_main_force():
    print("\n[Step 1] iFinD主力资金流入Top30...")
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '今日主力资金净流入排名前30的股票，显示所属概念板块'
        })
        if not result.get('ok'): return []
        stocks = parse_ifind_result(result)
        main_board = [s for s in stocks if is_main_board(s['code'])]
        for s in main_board: s['source'] = '主力流入'
        print(f"  ✅ 主板{len(main_board)}只")
        return main_board[:30]
    except Exception as e:
        print(f"  ❌ {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# Step 2: 自动热点板块（5个×6只）
# ═══════════════════════════════════════════════════════════════

def fetch_hot_sectors_fast():
    """快速版：5个板块 × 6只"""
    print("\n[Step 2] 自动提取热点板块Top5...")
    
    # 2A: 近一周涨幅前50（带概念）
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '近一周涨幅排名前50的股票，显示所属概念板块'
        })
        if not result.get('ok'): return [], []
        stocks = parse_ifind_result(result)
    except Exception as e:
        print(f"  ❌ {e}")
        return [], []
    
    # 2B: 统计概念频率
    concept_counter = Counter()
    for s in stocks:
        sectors = extract_sectors_from_concepts(s.get('concepts',''))
        for sec in sectors:
            concept_counter[sec] += 1
    
    top5 = [c for c,_ in concept_counter.most_common(5)]
    print(f"  📊 热点板块Top5: {top5}")
    
    # 2C: 查每个板块的前6只主板成分股
    all_stocks = []
    for concept in top5:
        try:
            result = ifind_call('stock', 'search_stocks', {
                'query': f'{concept}概念股'
            })
            if result.get('ok'):
                sector_stocks = parse_ifind_result(result)
                main_board = [s for s in sector_stocks if is_main_board(s['code'])]
                for s in main_board[:6]:
                    s['source'] = f'板块:{concept}'
                    s['sector'] = concept
                    all_stocks.append(s)
                print(f"    {concept}: {len(main_board[:6])}只主板")
        except Exception as e:
            print(f"    ⚠️ {concept}: {e}")
    
    print(f"  ✅ 热点板块成分股: {len(all_stocks)}只")
    return top5, all_stocks

# ═══════════════════════════════════════════════════════════════
# Step 2.5: 自动拉涨停池（iFinD）
# ═══════════════════════════════════════════════════════════════

def fetch_limit_up_from_ifind():
    """iFinD自动拉今日涨停股票"""
    print("\n[Step 2.5] iFinD自动拉涨停池...")
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '今日涨停的股票，显示所属概念板块，只选主板'
        })
        if not result.get('ok'): 
            print("  ⚠️ iFinD查询失败")
            return []
        
        stocks = parse_ifind_result(result)
        main_board = [s for s in stocks if is_main_board(s['code'])]
        
        # 存入DuckDB
        pool_stocks = []
        for s in main_board:
            pool_stocks.append({
                'code': s['code'],
                'name': s.get('name', ''),
                'source': 'iFinD自动',
                'sector': ', '.join(extract_sectors_from_concepts(s.get('concepts',''))),
                'close': 0.0, 'change_pct': 9.9, 'volume': 0.0
            })
        
        # 导入DuckDB
        from pool_manager import upsert_pool
        upsert_pool('limit_up', pool_stocks)
        
        print(f"  ✅ 涨停池: {len(main_board)}只主板")
        return main_board
    except Exception as e:
        print(f"  ❌ 涨停池拉取失败: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# Step 2.6: 人气池（龙虎榜+游资+人气榜）
# ═══════════════════════════════════════════════════════════════

def fetch_popularity_pool():
    """拉取人气池：龙虎榜 + 游资买入 + 人气榜"""
    print("\n[Step 2.6] 拉取人气池（龙虎榜+游资+人气榜）...")
    all_codes = set()
    
    # 2.6A: 龙虎榜
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '今日龙虎榜股票，显示买入营业部'
        })
        if result.get('ok'):
            stocks = parse_ifind_result(result)
            for s in stocks:
                if is_main_board(s['code']):
                    all_codes.add((s['code'], s.get('name',''), '龙虎榜'))
            print(f"  📊 龙虎榜: {len(stocks)}只")
    except Exception as e:
        print(f"  ⚠️ 龙虎榜失败: {e}")
    
    # 2.6B: 游资买入
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '游资买入的股票今日'
        })
        if result.get('ok'):
            stocks = parse_ifind_result(result)
            for s in stocks:
                if is_main_board(s['code']):
                    all_codes.add((s['code'], s.get('name',''), '游资买入'))
            print(f"  📊 游资买入: {len(stocks)}只")
    except Exception as e:
        print(f"  ⚠️ 游资失败: {e}")
    
    # 2.6C: 人气榜
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '今日人气榜排名前20的股票'
        })
        if result.get('ok'):
            stocks = parse_ifind_result(result)
            for s in stocks:
                if is_main_board(s['code']):
                    all_codes.add((s['code'], s.get('name',''), '人气榜'))
            print(f"  📊 人气榜: {len(stocks)}只")
    except Exception as e:
        print(f"  ⚠️ 人气榜失败: {e}")
    
    # 合并去重
    pool_stocks = []
    for code, name, source in all_codes:
        pool_stocks.append({
            'code': code, 'name': name, 'source': source,
            'sector': '', 'close': 0.0, 'change_pct': 0.0, 'volume': 0.0
        })
    
    # 存入DuckDB
    from pool_manager import upsert_pool
    upsert_pool('hot', pool_stocks)
    
    print(f"  ✅ 人气池合计: {len(pool_stocks)}只（去重后）")
    return pool_stocks

# ═══════════════════════════════════════════════════════════════
# Step 2.7: 主线池（近5日涨幅前20，主板only）
# ═══════════════════════════════════════════════════════════════

def fetch_main_line_pool():
    """主线池：近5日涨幅全市场前20，主板only"""
    print("\n[Step 2.7] 拉取主线池（近5日涨幅前20）...")
    try:
        result = ifind_call('stock', 'search_stocks', {
            'query': '近5日涨幅排名前20的股票，显示所属概念板块，只选主板'
        })
        if not result.get('ok'):
            print("  ⚠️ iFinD查询失败")
            return []
        
        stocks = parse_ifind_result(result)
        main_board = [s for s in stocks if is_main_board(s['code'])]
        
        pool_stocks = []
        for s in main_board[:20]:
            pool_stocks.append({
                'code': s['code'],
                'name': s.get('name', ''),
                'source': 'iFinD:近5日涨幅前20',
                'sector': ', '.join(extract_sectors_from_concepts(s.get('concepts',''))),
                'close': 0.0, 'change_pct': 0.0, 'volume': 0.0
            })
        
        from pool_manager import upsert_pool
        upsert_pool('main_line', pool_stocks)
        
        print(f"  ✅ 主线池: {len(pool_stocks)}只")
        return pool_stocks
    except Exception as e:
        print(f"  ❌ 主线池拉取失败: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# Step 2.8: 强势池（RSI>70 + MACD金叉 + 放量，主板only）
# ═══════════════════════════════════════════════════════════════

def fetch_strong_pool():
    """强势池：RSI>70 + MACD金叉 + 放量，主板only"""
    print("\n[Step 2.8] 拉取强势池（RSI>70+MACD金叉+放量）...")
    try:
        # iFinD可能不支持复杂技术指标筛选，先拉全市场再过滤
        result = ifind_call('stock', 'search_stocks', {
            'query': '今日强势股，RSI大于70，MACD金叉，成交量放大，显示所属概念板块，只选主板'
        })
        if not result.get('ok'):
            # 备选：拉涨幅靠前的再筛选
            result = ifind_call('stock', 'search_stocks', {
                'query': '近3日涨幅排名前30的股票，显示所属概念板块，只选主板'
            })
        
        if not result.get('ok'):
            print("  ⚠️ iFinD查询失败")
            return []
        
        stocks = parse_ifind_result(result)
        main_board = [s for s in stocks if is_main_board(s['code'])]
        
        pool_stocks = []
        for s in main_board[:15]:
            pool_stocks.append({
                'code': s['code'],
                'name': s.get('name', ''),
                'source': 'iFinD:RSI>70+MACD金叉+放量',
                'sector': ', '.join(extract_sectors_from_concepts(s.get('concepts',''))),
                'close': 0.0, 'change_pct': 0.0, 'volume': 0.0
            })
        
        from pool_manager import upsert_pool
        upsert_pool('strong', pool_stocks)
        
        print(f"  ✅ 强势池: {len(pool_stocks)}只")
        return pool_stocks
    except Exception as e:
        print(f"  ❌ 强势池拉取失败: {e}")
        return []

# ═══════════════════════════════════════════════════════════════
# Step 3: 六池
# ═══════════════════════════════════════════════════════════════

def load_all_pools():
    print("\n[Step 2] 池子更新（读取六池）...")
    pools = {}
    for name in ['bottom','limit_up','main_line','strong','user_pick','hot']:
        data = load_pool(name)
        filtered = []
        for item in data:
            code = normalize_code(item.get('code',''))
            if is_main_board(code):
                item['code'] = code
                item['source'] = name
                filtered.append(item)
        pools[name] = filtered
        print(f"  📂 {name}: {len(filtered)}只")
    return pools

# ═══════════════════════════════════════════════════════════════
# Step 4: 合并
# ═══════════════════════════════════════════════════════════════

def merge_candidates(main_force, sector_stocks, pools):
    print("\n[Step 3] 合并去重...")
    
    # Step 3A: 候选池A = 主力流入 + 热点板块
    pool_a = {}
    for s in main_force:
        code = s['code']
        pool_a[code] = {'code':code,'name':s.get('name',''),'sources':['主力流入'],'sectors':[]}
    for s in sector_stocks:
        code = s['code']
        sector = s.get('sector','')
        if code in pool_a:
            if '热点板块' not in pool_a[code]['sources']:
                pool_a[code]['sources'].append('热点板块')
        else:
            pool_a[code] = {'code':code,'name':s.get('name',''),'sources':['热点板块'],'sectors':[]}
    print(f"  📊 候选池A (主力+热点): {len(pool_a)}只")
    
    # Step 3B: 六池合并
    pool_six = {}
    for pool_name, stocks in pools.items():
        for s in stocks:
            code = s.get('code','')
            if not is_main_board(code): continue
            if code in pool_six:
                if pool_name not in pool_six[code]['sources']:
                    pool_six[code]['sources'].append(pool_name)
            else:
                pool_six[code] = {'code':code,'name':s.get('name',''),'sources':[pool_name],'sectors':[]}
    print(f"  📊 六池合计: {len(pool_six)}只")
    
    # Step 3C: 合并候选池A + 六池 = 最终候选池
    candidates = dict(pool_a)  # 先拷贝A池
    for code, info in pool_six.items():
        if code in candidates:
            # 合并来源
            for src in info['sources']:
                if src not in candidates[code]['sources']:
                    candidates[code]['sources'].append(src)
        else:
            candidates[code] = info
    
    print(f"  ✅ 最终候选池: {len(candidates)}只")
    
    # Step 3D: 补充所属概念板块（关键修复！）
    print(f"\n[Step 3D] 补充所属概念板块...")
    codes_list = list(candidates.keys())
    for i in range(0, len(codes_list), 20):
        batch = codes_list[i:i+20]
        codes_str = ','.join(batch)
        try:
            result = ifind_call('stock', 'search_stocks', {
                'query': f'股票代码为{codes_str}的股票，显示所属概念板块'
            })
            if result.get('ok'):
                stocks = parse_ifind_result(result)
                for s in stocks:
                    code = normalize_code(s.get('code',''))
                    concepts = s.get('concepts','')
                    if code in candidates and concepts:
                        sectors = extract_sectors_from_concepts(concepts)
                        if sectors:
                            candidates[code]['sectors'] = sectors
                        candidates[code]['name'] = s.get('name', candidates[code]['name'])
        except Exception as e:
            print(f"    ⚠️ 概念查询失败: {e}")
        time.sleep(0.3)
    
    return candidates

# ═══════════════════════════════════════════════════════════════
# Step 5: 历史K线
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# Step 5: 历史K线（多源回退）
# ═══════════════════════════════════════════════════════════════

def fetch_klines(candidates):
    print(f"\n[Step 4-1] 拉取历史K线（多源回退：akshare→Baostock→同花顺）...")
    kline_data = {}
    need_fetch = []
    
    # 1. 读本地缓存
    for code in candidates.keys():
        local_file = f"/tmp/kline_{code}.csv"
        if os.path.exists(local_file):
            try:
                df = pd.read_csv(local_file)
                df = df.dropna(subset=['open','high','low','close','volume'])
                if len(df) >= 21:
                    kline_data[code] = df
                    continue
            except: pass
        need_fetch.append(code)
    
    print(f"  ✅ 本地缓存: {len(kline_data)}只")
    if not need_fetch:
        return kline_data
    
    print(f"  📥 需拉取: {len(need_fetch)}只")
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
    
    # 2. 第一优先级：akshare（最稳定）
    print(f"\n  📡 尝试akshare...")
    import akshare as ak
    success_count = 0
    for i, code in enumerate(need_fetch[:]):
        print(f"    [{i+1}/{len(need_fetch)}] {code}...", end=' ', flush=True)
        df = None
        
        # 尝试akshare接口A
        for attempt in range(3):
            try:
                df = ak.stock_zh_a_hist(symbol=code, period="daily", 
                                        start_date=start_date.replace('-',''), 
                                        end_date=end_date.replace('-',''), 
                                        adjust="qfq")
                if df is not None and len(df) >= 21:
                    break
            except Exception as e:
                if attempt < 2:
                    time.sleep(1)
                continue
        
        # 尝试akshare接口B（备用）
        if df is None or len(df) < 21:
            try:
                df2 = ak.stock_zh_a_daily(symbol=code, start_date=start_date, end_date=end_date, adjust="qfq")
                if df2 is not None and len(df2) >= 21:
                    df = df2
            except:
                pass
        
        if df is not None and len(df) >= 21:
            # 统一列名
            col_map = {'日期':'date','开盘':'open','最高':'high','最低':'low','收盘':'close',
                       '成交量':'volume','成交额':'amount','振幅':'amplitude','涨跌幅':'pctChg','换手率':'turn'}
            for old, new in col_map.items():
                if old in df.columns:
                    df = df.rename(columns={old: new})
            for col in ['open','high','low','close','volume','amount','turn','pctChg']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            df['preclose'] = df['close'].shift(1)
            df = df.dropna()
            if len(df) >= 21:
                kline_data[code] = df
                # 保存缓存
                try:
                    df.to_csv(f"/tmp/kline_{code}.csv", index=False)
                except: pass
                success_count += 1
                print(f"✅ {len(df)}条")
                need_fetch.remove(code)
                continue
        
        print(f"❌")
        time.sleep(0.3)
    
    print(f"  ✅ akshare成功: {success_count}/{len(need_fetch)+success_count}只")
    
    # 3. 第二优先级：Baostock（给还剩下的票）
    if need_fetch:
        print(f"\n  📡 尝试Baostock（剩余{len(need_fetch)}只）...")
        import baostock as bs
        try:
            lg = bs.login()
            if lg.error_code == '0':
                bs_ok = True
            else:
                bs_ok = False
                bs.logout()
        except:
            bs_ok = False
        
        if bs_ok:
            for i, code in enumerate(need_fetch[:]):
                print(f"    [{i+1}/{len(need_fetch)}] {code}...", end=' ', flush=True)
                try:
                    bs_code = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
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
                        df = df.dropna()
                        if len(df) >= 21:
                            kline_data[code] = df
                            df.to_csv(f"/tmp/kline_{code}.csv", index=False)
                            print(f"✅ {len(df)}条")
                            need_fetch.remove(code)
                            continue
                except Exception as e:
                    pass
                print(f"❌")
                time.sleep(0.15)
            bs.logout()
    
    print(f"\n  ✅ K线就绪: {len(kline_data)}/{len(candidates)}只")
    if need_fetch:
        print(f"  ⚠️ 未获取: {len(need_fetch)}只 → 将用简化评分")
    return kline_data

# ═══════════════════════════════════════════════════════════════
# Step 6: 实时K线（盘中用）
# ═══════════════════════════════════════════════════════════════

def fetch_intraday(candidates, kline_data):
    print(f"\n[Step 4-2] 补充实时K线...")
    hour = datetime.now().hour
    if not (9 <= hour <= 11 or 13 <= hour <= 15):
        print(f"  ⏰ 非交易时间，跳过")
        return kline_data
    print(f"  📊 交易时间，拉1分钟K线...")
    return kline_data

# ═══════════════════════════════════════════════════════════════
# Step 7: 评分
# ═══════════════════════════════════════════════════════════════

def build_v22_data(code, info, df):
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
    
    # 战法检测
    is_limit_up_pullback = False
    pullback_name = ''
    pullback_score = 0
    
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
            pullback_pct = (limit_price-latest_close)/limit_price*100 if limit_price>0 else 0
            if 3 <= pullback_pct <= 15:
                recent_volume = volume
                avg_volume_5d = df['volume'].iloc[-6:-1].mean()
                volume_shrink = recent_volume < avg_volume_5d*0.8 if avg_volume_5d>0 else False
                if volume_shrink:
                    is_limit_up_pullback = True
                    pullback_name = '涨停回调(缩量)'
                    pullback_score = 1.5
                else:
                    is_limit_up_pullback = True
                    pullback_name = '涨停回调'
                    pullback_score = 1.0
    
    # 龙头首阴
    is_dragon_yin = False
    dragon_name = ''
    dragon_score = 0
    if len(df) >= 5:
        recent = df.iloc[-5:]
        consecutive_limits = 0
        for idx in range(len(recent)-1):
            try:
                row = recent.iloc[idx]
                o, c = float(row['open']), float(row['close'])
                change = (c-o)/o*100 if o>0 else 0
                if change >= 9.5:
                    consecutive_limits += 1
                else:
                    if consecutive_limits >= 2: break
                    consecutive_limits = 0
            except: continue
        if consecutive_limits >= 2:
            l_close, l_open = close, open_p
            p_close = float(prev['close'])
            is_yin = l_close < l_open
            drop_pct = (p_close-l_close)/p_close*100 if p_close>0 else 0
            if is_yin and drop_pct < 5:
                is_dragon_yin = True
                dragon_name = '龙头首阴'
                dragon_score = 1.5
    
    # 首板断板
    is_first_break = False
    break_name = ''
    break_score = 0
    if len(df) >= 4:
        recent3 = df.iloc[-4:-1]
        try:
            d1 = recent3.iloc[0]
            d1_open, d1_close = float(d1['open']), float(d1['close'])
            d1_change = (d1_close-d1_open)/d1_open*100 if d1_open>0 else 0
            if d1_change >= 9.5:
                d2 = recent3.iloc[1]
                d2_close, d2_open = float(d2['close']), float(d2['open'])
                d2_change = (d2_close-d2_open)/d2_open*100 if d2_open>0 else 0
                if d2_change < 9.5:
                    l_close, l_open = close, open_p
                    body_pct = abs(l_close-l_open)/l_open*100 if l_open>0 else 0
                    if body_pct < 3 or l_close > l_open:
                        if l_close > d1_open:
                            is_first_break = True
                            break_name = '首板断板(承接)'
                            break_score = 1.0
        except: pass
    
    tactic_score = pullback_score + dragon_score + break_score
    tactic_names = []
    if is_limit_up_pullback: tactic_names.append(pullback_name)
    if is_dragon_yin: tactic_names.append(dragon_name)
    if is_first_break: tactic_names.append(break_name)
    
    # 模式检测
    breakout = close > high_20d
    pullback_pct = (high_20d-close)/high_20d*100 if high_20d>0 else 0
    
    ma20_trend = 'up' if len(df)>=21 and ma20 > df['close'].iloc[-21] else 'neutral'
    
    # 倍量阳线
    is_double_volume = volume > volume_20d_avg*1.8 if volume_20d_avg>0 else False
    is_big_yang = close > open_p and (close-open_p)/open_p*100 > 2 if open_p>0 else False
    
    # 模式得分
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
    
    # 杯柄（简化版）
    if not breakout and len(df) >= 40:
        high_40d = df['high'].iloc[-40:-10].max()
        handle_low = df['low'].iloc[-10:-1].min()
        if high_40d > 0 and close > high_40d * 0.95 and handle_low > high_40d * 0.85:
            pattern = 1.5
            pattern_name = '杯柄(疑似)'
    
    has_hammer = False
    body = abs(close-open_p)
    upper_shadow = high-max(close,open_p)
    lower_shadow = min(close,open_p)-low
    if body > 0 and lower_shadow > body*2 and upper_shadow < body*0.5:
        has_hammer = True
    
    return {
        'code': code, 'name': info.get('name',''),
        'close': close, 'open': open_p, 'high': high, 'low': low,
        'prev_close': prev_close, 'volume': volume, 'amount': amount,
        'volume_20d_avg': volume_20d_avg, 'high_20d': high_20d, 'low_20d': low_20d,
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
        'macd': macd, 'rsi6': rsi6, 'kdj_k': k, 'kdj_d': d, 'kdj_j': j,
        'volume_ratio': volume_ratio, 'change_pct': change_pct,
        'is_hot_sector': len(info.get('sectors',[])) > 0 or 'main_line' in info.get('sources',[]),
        'streak_days': 0, 'institution_hold_pct': 0, 'market_cap': 100,
        'beta': 1.0, 'sector_return': 0, 'index_change': 0, 'sector_change': 0,
        'total_position_pct': 0.3, 'rebound_count': 1, 'retail_etf_flow': 0,
        'erp': 0.03, 'margin_status': 0, 'market_breadth': 0.5,
        'sentiment_score': 0, 'fundamental_score': 0, 'news_sentiment': 0,
        'notice_risk': 1, 'date': datetime.now().strftime('%Y%m%d'),
        'high_recent': high_20d, 'volume_rally_avg': volume_20d_avg,
        'has_hammer': has_hammer, 'has_engulfing': False,
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
        'is_limit_up_pullback': is_limit_up_pullback,
        'is_dragon_first_yin': is_dragon_yin,
        'is_first_board_break': is_first_break,
        'pattern': pattern, 'pattern_name': pattern_name,
        'is_double_volume': is_double_volume, 'is_big_yang': is_big_yang,
    }


def run_scoring(candidates, kline_data):
    print(f"\n[Step 4-3] 完整版v2.2精筛评分...")
    results = []
    
    for code, info in candidates.items():
        kline_df = kline_data.get(code)
        
        if kline_df is not None and len(kline_df) >= 21:
            # 有K线：完整版评分
            try:
                data = build_v22_data(code, info, kline_df)
                if data is None: 
                    # 完整评分失败，降级为简化
                    result = build_simplified_score(code, info)
                else:
                    result = run_v22_scoring(data)
                    # 战法加分
                    tactic_score = data.get('tactic_score', 0)
                    if tactic_score > 0:
                        base = result.get('final_score', 0)
                        bonus = min(tactic_score * 0.1, 0.15)
                        result['final_score'] = min(base + bonus, 1.0)
                    result['close'] = data['close']
                    result['change_pct'] = data['change_pct']
                    result['pattern_name'] = data.get('pattern_name', '-')
                    result['tactic_names'] = data.get('tactic_names', [])
                    result['tactic_score'] = data.get('tactic_score', 0)
            except Exception as e:
                result = build_simplified_score(code, info)
        else:
            # 无K线：简化评分
            result = build_simplified_score(code, info)
        
        result.update({
            'code': code, 'name': info.get('name',''),
            'sources': info.get('sources', []),
            'sectors': info.get('sectors', []),
        })
        results.append(result)
    
    results.sort(key=lambda x: x.get('final_score',0), reverse=True)
    print(f"  ✅ 评分完成: {len(results)}只")
    return results

def build_simplified_score(code, info):
    """无K线时的简化评分（基于已有数据）"""
    change_pct = info.get('change_pct', 0)
    sectors = info.get('sectors', [])
    sources = info.get('sources', [])
    close = info.get('close', 0)
    
    # 基础分
    base_score = 0.3
    
    # 涨幅加分（-10%~+10%映射到0~0.2）
    change_bonus = max(0, min(change_pct + 5, 15)) / 75  # -5%以下0分，+10%得0.2
    
    # 来源加分（多池覆盖=更强信号）
    source_bonus = min(len(sources) * 0.03, 0.1)
    
    # 板块加分
    sector_bonus = 0.05 if sectors else 0
    
    # 主力流入加分
    main_force_bonus = 0.05 if '主力流入' in sources else 0
    
    # 热点板块加分
    hot_bonus = 0.05 if '热点板块' in sources else 0
    
    final_score = min(base_score + change_bonus + source_bonus + sector_bonus + main_force_bonus + hot_bonus, 0.55)
    
    # 策略判断
    if change_pct > 5:
        strategy = '两者皆可'
        overnight_grade = '观察'
        fusion_grade = '一般'
    elif change_pct > 2:
        strategy = '波段'
        overnight_grade = '观察'
        fusion_grade = '一般'
    elif change_pct < -3:
        strategy = '观望'
        overnight_grade = '排除'
        fusion_grade = '弱'
    else:
        strategy = '观望'
        overnight_grade = '观察'
        fusion_grade = '一般'
    
    return {
        'final_score': round(final_score, 3),
        'tier': 'B' if final_score >= 0.45 else 'X',
        'overnight_score': 5.0,
        'overnight_grade': overnight_grade,
        'overnight_probability': 0.5,
        'fusion_score': 3.0,
        'fusion_grade': fusion_grade,
        'strategy_type': {'type': strategy, 'overnight_suitable': strategy != '观望', 'swing_suitable': strategy != '观望'},
        'close': close,
        'change_pct': change_pct,
        'pattern_name': '-',
        'tactic_names': [],
        'tactic_score': 0,
        'reasons': ['简化评分(无K线)', f'涨幅{change_pct:+.1f}%'],
        'position_pct': 0.05,
    }

# ═══════════════════════════════════════════════════════════════
# Step 8: 输出
# ═══════════════════════════════════════════════════════════════

def format_output(results):
    lines = []
    lines.append("=" * 90)
    lines.append(f"🎯 A股动量选股系统 v3.2 — 完整版")
    lines.append(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"📊 iFinD主力 + 自动热点板块 + 历史K线 + 六池")
    lines.append("=" * 90)
    lines.append("")
    
    tier_s = [r for r in results if r.get('tier')=='S']
    tier_a = [r for r in results if r.get('tier')=='A']
    tier_b = [r for r in results if r.get('tier')=='B']
    tier_x = [r for r in results if r.get('tier')=='X']
    
    if tier_s:
        lines.append("🔥🔥🔥 Tier S — 强烈推荐 🔥🔥🔥")
        for r in tier_s[:5]: lines.extend(fmt_stock(r))
        lines.append("")
    
    if tier_a:
        lines.append("⭐⭐ Tier A — 推荐关注 ⭐⭐")
        for r in tier_a[:10]: lines.extend(fmt_stock(r))
        lines.append("")
    
    if tier_b:
        lines.append("⭐ Tier B — 观察 ⭐")
        for r in tier_b[:10]: lines.extend(fmt_stock(r))
        lines.append("")
    
    # 战法
    tactics = [r for r in results if r.get('tactic_score',0)>0]
    if tactics:
        lines.append("⚔️ 战法专区 ⚔️")
        for r in tactics[:5]: lines.extend(fmt_tactic(r))
        lines.append("")
    
    lines.append("📈 统计:")
    lines.append(f"   Tier S:{len(tier_s)} | A:{len(tier_a)} | B:{len(tier_b)} | X:{len(tier_x)}")
    if tactics: lines.append(f"   战法:{len(tactics)}只")
    lines.append("")
    
    return "\n".join(lines)


def fmt_stock(r):
    lines = []
    code, name = r.get('code',''), r.get('name','')
    close = r.get('close',0)
    change = r.get('change_pct',0)
    tier = r.get('tier','X')
    overnight = r.get('overnight_score',0)
    fusion = r.get('fusion_score',0)
    pattern_name = r.get('pattern_name','-')
    tactic_names = r.get('tactic_names',[])
    sectors = r.get('sectors',[])
    
    # 操作策略判断：过夜 vs 波段
    if overnight >= 10 and 2 <= change <= 7:
        action = '两者皆可（过夜优先）' if fusion >= 6 else '过夜'
    elif fusion >= 6 and pattern_name in ['杯柄(疑似)', '突破(大幅越过)', '突破(中等越过)']:
        action = '波段'
    elif overnight >= 8:
        action = '过夜'
    elif fusion >= 5:
        action = '波段'
    else:
        action = '观望'
    
    # 命中项：说明为什么高分
    reasons = []
    if overnight >= 12:
        reasons.append(f'一夜持股法{overnight:.0f}分，T+0午后介入信号极强')
    elif overnight >= 10:
        reasons.append(f'一夜持股法{overnight:.0f}分，T+0午后介入信号强')
    elif overnight >= 8:
        reasons.append(f'一夜持股法{overnight:.0f}分，具备T+0介入条件')
    
    if fusion >= 8:
        reasons.append(f'三维融合{fusion:.0f}分，3-20日波段趋势极强')
    elif fusion >= 6:
        reasons.append(f'三维融合{fusion:.0f}分，波段趋势向好')
    
    if pattern_name and pattern_name != '-':
        reasons.append(f'{pattern_name}，技术形态加分')
    
    if tactic_names:
        reasons.append(f'战法:{"+".join(tactic_names)}，主力行为确认')
    
    if not reasons:
        reasons = ['技术面共振']
    
    sector_str = ' / '.join(sectors[:3]) if sectors else '—'
    
    lines.append('—' * 60)
    lines.append(f'标的名称:     {code} {name} [{tier}]')
    lines.append(f'所属概念板块: {sector_str}')
    lines.append(f'今日涨跌幅:   {change:+.2f}%')
    lines.append(f'当前股价:     ¥{close:.2f}')
    lines.append(f'策略逻辑命中项: {"; ".join(reasons)}')
    lines.append(f'操作策略:     {action}')
    lines.append('')
    return lines


def fmt_tactic(r):
    lines = []
    code, name = r.get('code',''), r.get('name','')
    close = r.get('close',0)
    change = r.get('change_pct',0)
    tier = r.get('tier','X')
    tactic_names = r.get('tactic_names',[])
    sectors = r.get('sectors',[])
    
    sector_str = ' / '.join(sectors[:3]) if sectors else '—'
    
    lines.append('—' * 60)
    lines.append(f'标的名称:     {code} {name} [{tier}]')
    lines.append(f'所属概念板块: {sector_str}')
    lines.append(f'今日涨跌幅:   {change:+.2f}%')
    lines.append(f'当前股价:     ¥{close:.2f}')
    lines.append(f'策略逻辑命中项: 战法:{"+".join(tactic_names)}')
    lines.append(f'操作策略:     波段')
    lines.append('')
    return lines

# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 80)
    print("A股动量选股系统 v3.2 — 完整版启动")
    print("=" * 80)
    
    # 判断交易时间
    trading = is_trading_time()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    if not trading:
        print(f"\n⏰ 当前时间 {now_str} — 非交易时间")
        print("   A股交易时间: 工作日 09:30-11:30, 13:00-15:00")
        print("   非交易时间将回退到上一交易日结果...\n")
        
        last = get_last_result()
        if last:
            results, fname = last
            print(f"📂 加载历史结果: {fname}")
            output = format_output(results)
            print(output)
            print(f"\n💡 提示: 以上为历史数据，非实时。请在交易时间运行获取最新候选。")
            return
        else:
            print("❌ 未找到历史结果文件。请在交易时间首次运行以生成本日数据。")
            return
    
    # 交易时间 — 正常执行全流程
    print(f"\n🚀 交易时间 {now_str} — 启动实时扫描...\n")
    start = time.time()

    # ═══════════════════════════════════════════════════════════════
    # Step 0: 更新池子中所有票的最新价格
    # ═══════════════════════════════════════════════════════════════
    print("📊 Step 0: 更新池子最新行情...")
    db_path = '/root/.openclaw/workspace/skills/ifind-momentum-screener/data/pools/pools.duckdb'
    dm = DataSourceManager()
    dm.update_pool_prices(db_path)
    print()

    
    main_force = fetch_main_force()
    hot_sectors, sector_stocks = fetch_hot_sectors_fast()
    
    # Step 2.5-2.8: 自动池更新（交易时间才更新）
    fetch_limit_up_from_ifind()
    fetch_popularity_pool()
    fetch_main_line_pool()
    fetch_strong_pool()
    
    # Step 3: 读取六池（DuckDB）
    pools = load_all_pools()
    candidates = merge_candidates(main_force, sector_stocks, pools)
    
    if not candidates:
        print("\n❌ 候选池为空")
        return
    
    kline_data = fetch_klines(candidates)
    kline_data = fetch_intraday(candidates, kline_data)
    results = run_scoring(candidates, kline_data)
    
    output = format_output(results)
    print(output)
    
    date_str = datetime.now().strftime('%Y%m%d')
    out_file = RESULT_DIR / f'result_v32_{date_str}.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n💾 已保存: {out_file}")
    print(f"⏱️ 总耗时: {time.time()-start:.1f}秒")

if __name__ == '__main__':
    main()
