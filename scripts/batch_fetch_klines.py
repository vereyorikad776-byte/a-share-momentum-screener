#!/usr/bin/env python3
"""
batch_fetch_klines.py — 批量获取历史K线
支持: Baostock主 + stock_finance_data备选
批量获取，缓存到本地，供complete_scanner使用
"""

import sys, json, os, subprocess
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')
import baostock as bs
import pandas as pd

CACHE_DIR = Path('/tmp/kline_cache')
CACHE_DIR.mkdir(exist_ok=True)


def check_baostock():
    """检查Baostock是否可用"""
    try:
        lg = bs.login()
        if lg.error_code == '0':
            return True
        bs.logout()
    except:
        pass
    return False


def fetch_baostock_single(code, days=25):
    """单票Baostock获取"""
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


def fetch_stock_finance_data_batch(codes, days=25):
    """
    批量获取stock_finance_data历史K线
    每次最多3只，分批处理
    """
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')
    
    results = {}
    
    # 每批3只
    for i in range(0, len(codes), 3):
        batch = codes[i:i+3]
        tickers = []
        for code in batch:
            suffix = '.SH' if code.startswith('6') else '.SZ'
            tickers.append(f"{code}{suffix}")
        ticker_str = ','.join(tickers)
        
        file_path = f"/tmp/sfd_batch_{i}.csv"
        
        try:
            # 使用OpenClaw CLI调用kimi_datasource_call
            cmd = [
                'openclaw', 'tool', 'kimi_datasource_call',
                '--data_source_name', 'stock_finance_data',
                '--api_name', 'stock_finance_data_get_price',
                '--params', json.dumps({
                    'ticker': ticker_str,
                    'start_date': start_date,
                    'end_date': end_date,
                    'interval': 'D',
                    'adjust': 'forward',
                    'file_path': file_path
                })
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                # 按ticker分组
                for code in batch:
                    suffix = '.SH' if code.startswith('6') else '.SZ'
                    ticker = f"{code}{suffix}"
                    code_df = df[df.get('thscode', '') == ticker].copy()
                    
                    if len(code_df) >= 20:
                        # 重命名列
                        code_df = code_df.rename(columns={'time': 'date'})
                        for col in ['open', 'high', 'low', 'close', 'volume']:
                            if col in code_df.columns:
                                code_df[col] = pd.to_numeric(code_df[col], errors='coerce')
                        
                        # 计算preclose和pctChg
                        if len(code_df) >= 2:
                            code_df['preclose'] = code_df['close'].shift(1)
                            code_df['pctChg'] = (code_df['close'] - code_df['preclose']) / code_df['preclose'] * 100
                        
                        code_df = code_df.dropna()
                        if len(code_df) >= 20:
                            results[code] = code_df
                            # 缓存
                            cache_file = CACHE_DIR / f"{code}.csv"
                            code_df.to_csv(cache_file, index=False)
                            
        except Exception as e:
            print(f"  ⚠️ batch {i} failed: {e}")
            continue
    
    return results


def fetch_all_klines(codes, days=25, use_cache=True):
    """
    智能获取所有候选票的K线
    优先级: 缓存 > Baostock > stock_finance_data
    """
    results = {}
    missing = []
    
    # 1. 检查缓存
    if use_cache:
        for code in codes:
            cache_file = CACHE_DIR / f"{code}.csv"
            if cache_file.exists():
                try:
                    df = pd.read_csv(cache_file)
                    if len(df) >= 20:
                        results[code] = df
                        continue
                except:
                    pass
            missing.append(code)
    else:
        missing = codes
    
    if not missing:
        return results
    
    # 2. 尝试Baostock
    bs_available = check_baostock()
    if bs_available:
        print(f"📊 Baostock可用，获取{len(missing)}只K线...")
        bs.login()
        still_missing = []
        for code in missing:
            df = fetch_baostock_single(code, days)
            if df is not None and len(df) >= 20:
                results[code] = df
                cache_file = CACHE_DIR / f"{code}.csv"
                df.to_csv(cache_file, index=False)
            else:
                still_missing.append(code)
        bs.logout()
        missing = still_missing
    
    # 3. Baostock失败或不可用，用stock_finance_data
    if missing:
        print(f"📊 Baostock不可用/失败，改用stock_finance_data获取{len(missing)}只...")
        sfd_results = fetch_stock_finance_data_batch(missing, days)
        results.update(sfd_results)
    
    return results


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 batch_fetch_klines.py <codes_json_file>")
        sys.exit(1)
    
    with open(sys.argv[1]) as f:
        codes = json.load(f)
    
    print(f"批量获取 {len(codes)} 只票的K线...")
    results = fetch_all_klines(codes)
    print(f"✅ 成功获取 {len(results)} 只")
    
    # 输出结果文件路径
    output = {code: str(CACHE_DIR / f"{code}.csv") for code in results}
    print(json.dumps(output))
