#!/usr/bin/env python3
"""
DuckDB 本地数据缓存层 — 从 KhQuantFramework 借鉴

核心设计：
- 按市场分目录: duckdb_storage/SH/ /SZ/ /BJ/
- 每只股票一个 .db 文件（轻量化，避免单库过大）
- 首次从 akshare 拉取后写入本地，后续直接读本地
- 自动检测数据缺失区间，智能补充

收益：第二次回测速度提升 10x+
"""

import os
import duckdb
import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import json

# 默认存储路径
DEFAULT_STORAGE_DIR = os.path.join(
    os.path.dirname(__file__), '..', 'data', 'duckdb_storage'
)

# 市场映射
MARKET_MAP = {
    '6': 'SH', '0': 'SZ', '3': 'SZ', '8': 'BJ', '4': 'BJ',
}


def _get_market(code: str) -> str:
    """根据代码判断市场"""
    if code.startswith('sh.'):
        return 'SH'
    elif code.startswith('sz.'):
        return 'SZ'
    elif code.startswith('bj.'):
        return 'BJ'
    first = code[0] if code else '6'
    return MARKET_MAP.get(first, 'SH')


def _to_baostock_code(code: str) -> str:
    """统一转 baostock 格式"""
    # 如果已经是 baostock 格式，直接返回
    if code.startswith(('sh.', 'sz.', 'bj.')):
        return code
    # 去掉 .SH/.SZ/.BJ 后缀
    code = code.split('.')[0]
    if code.startswith('6'):
        return f'sh.{code}'
    elif code.startswith(('0', '3')):
        return f'sz.{code}'
    elif code.startswith(('8', '4')):
        return f'bj.{code}'
    return code


def _to_std_code(code: str) -> str:
    """统一转标准代码（去掉前缀）"""
    return code.replace('sh.', '').replace('sz.', '').replace('bj.', '')


def _to_baostock_date(date_str: str) -> str:
    """YYYYMMDD → YYYY-MM-DD"""
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def _to_std_date(date_str: str) -> str:
    """YYYY-MM-DD → YYYYMMDD"""
    return date_str.replace('-', '')


class StockDataCache:
    """股票数据缓存管理器"""

    def __init__(self, storage_dir: str = None):
        self.storage_dir = storage_dir or DEFAULT_STORAGE_DIR
        os.makedirs(self.storage_dir, exist_ok=True)
        self._bs_logged_in = False
        self._bs_blacklisted = False  # 标记是否数据源不可用

    def _get_db_path(self, code: str) -> str:
        """获取某只股票的 db 文件路径"""
        market = _get_market(code)
        market_dir = os.path.join(self.storage_dir, market)
        os.makedirs(market_dir, exist_ok=True)
        std_code = _to_std_code(code)
        return os.path.join(market_dir, f"{std_code}.db")

    def _bs_login(self):
        """数据源初始化占位（akshare无需登录）"""
        self._bs_logged_in = True

    def _bs_logout(self):
        """数据源退出占位（akshare无需登出）"""
        self._bs_logged_in = False

    def _init_table(self, conn: duckdb.DuckDBPyConnection):
        """初始化 K 线数据表"""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kline (
                date VARCHAR PRIMARY KEY,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                amount DOUBLE,
                turn DOUBLE,
                pctChg DOUBLE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def _read_local(self, code: str) -> pd.DataFrame:
        """从本地 DuckDB 读取全部数据"""
        db_path = self._get_db_path(code)
        if not os.path.exists(db_path):
            return pd.DataFrame()

        conn = duckdb.connect(db_path)
        try:
            df = conn.execute("SELECT * FROM kline ORDER BY date").fetchdf()
            return df
        except Exception as e:
            print(f"⚠️ 读取本地数据失败 {code}: {e}")
            return pd.DataFrame()
        finally:
            conn.close()

    def _write_local(self, code: str, df: pd.DataFrame):
        """写入数据到本地 DuckDB"""
        if df.empty:
            return

        db_path = self._get_db_path(code)
        conn = duckdb.connect(db_path)
        try:
            self._init_table(conn)
            # 先注册临时表
            conn.register('new_data', df)
            # 指定列插入，避免与 updated_at 不匹配
            conn.execute("""
                INSERT OR REPLACE INTO kline (date, open, high, low, close, volume, amount, turn, pctChg)
                SELECT date, open, high, low, close, volume, amount, turn, pctChg FROM new_data
            """)
            conn.unregister('new_data')
        finally:
            conn.close()

    def _fetch_from_akshare(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """从 akshare 拉取数据"""
        std_code = _to_std_code(code)
        # 转 akshare 的 symbol 格式
        if std_code.startswith('6'):
            symbol = f'sh{std_code}'
        elif std_code.startswith(('0', '3')):
            symbol = f'sz{std_code}'
        elif std_code.startswith(('8', '4')):
            symbol = f'bj{std_code}'
        else:
            symbol = f'sh{std_code}'

        try:
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq"  # 前复权
            )
        except Exception as e:
            print(f"⚠️ akshare 拉取失败 {symbol}: {e}")
            return pd.DataFrame()

        if df is None or df.empty:
            return pd.DataFrame()

        # akshare 列名 → 标准化列名
        # stock_zh_a_daily 返回: date,open,high,low,close,volume,amount,outstanding_share,turnover
        col_map = {
            'date': 'date',
            'open': 'open',
            'close': 'close',
            'high': 'high',
            'low': 'low',
            'volume': 'volume',
            'amount': 'amount',
            'turnover': 'turn',
        }
        df = df.rename(columns=col_map)

        # 日期标准化为 YYYYMMDD
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y%m%d')

        # 数值转换
        for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # 自己算涨跌幅（akshare daily 接口没有 pctChg）
        df['pctChg'] = df['close'].pct_change() * 100
        # 第一行的涨跌幅用 (close - open) / open 近似，或者留空
        if len(df) > 0 and pd.isna(df['pctChg'].iloc[0]):
            df.loc[df.index[0], 'pctChg'] = (df['close'].iloc[0] - df['open'].iloc[0]) / df['open'].iloc[0] * 100

        # 只保留需要的列
        needed = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']
        df = df[[c for c in needed if c in df.columns]]

        return df

    def get_kline(self, code: str, start_date: str, end_date: str,
                  auto_fetch: bool = True, force_refresh: bool = False) -> pd.DataFrame:
        """
        获取 K 线数据（智能缓存）

        Args:
            code: 股票代码（支持 600519 / sh.600519 格式）
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            auto_fetch: 本地缺失时是否自动从 akshare 补充
            force_refresh: 是否强制重新拉取（忽略本地缓存）

        Returns:
            DataFrame with columns: date, open, high, low, close, volume, amount, turn, pctChg
        """
        # 标准化日期
        start = _to_std_date(start_date)
        end = _to_std_date(end_date)

        if force_refresh:
            local_df = pd.DataFrame()
        else:
            local_df = self._read_local(code)

        # 情况1: 本地无数据，需要全量拉取
        if local_df.empty:
            if not auto_fetch:
                return pd.DataFrame()
            print(f"📥 {code} 本地无缓存，从 akshare 拉取 {start}~{end} ...")
            df = self._fetch_from_akshare(code, start, end)
            if not df.empty:
                self._write_local(code, df)
            return df

        # 情况2: 本地有数据，检查区间覆盖
        if not local_df.empty:
            local_min = local_df['date'].min()
            local_max = local_df['date'].max()

            # 完全在本地范围内
            if start >= local_min and end <= local_max:
                return local_df[(local_df['date'] >= start) & (local_df['date'] <= end)].copy()

            # 需要补充的数据区间
            missing_ranges = []
            if start < local_min:
                missing_ranges.append((start, local_min))
            if end > local_max:
                missing_ranges.append((local_max, end))

            if missing_ranges and auto_fetch:
                for miss_start, miss_end in missing_ranges:
                    # 留一天重叠，避免边界问题
                    actual_start = miss_start
                    actual_end = miss_end
                    print(f"📥 {code} 补充数据 {actual_start}~{actual_end} ...")
                    new_df = self._fetch_from_akshare(code, actual_start, actual_end)
                    if not new_df.empty:
                        self._write_local(code, new_df)

                # 重新读取合并后的本地数据
                local_df = self._read_local(code)

        # 返回请求区间
        result = local_df[(local_df['date'] >= start) & (local_df['date'] <= end)].copy()
        return result.sort_values('date').reset_index(drop=True)

    def get_klines_batch(self, codes: List[str], start_date: str, end_date: str,
                         auto_fetch: bool = True) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票 K 线

        Returns:
            {code: DataFrame, ...}
        """
        results = {}
        for code in codes:
            df = self.get_kline(code, start_date, end_date, auto_fetch=auto_fetch)
            if not df.empty:
                results[code] = df
        return results

    def cache_status(self, code: str = None) -> Dict:
        """
        查看缓存状态

        Returns:
            {
                'total_stocks': int,
                'total_size_mb': float,
                'stocks': [{code, market, min_date, max_date, rows}, ...]
            }
        """
        stocks = []
        total_size = 0

        for market in ['SH', 'SZ', 'BJ']:
            market_dir = os.path.join(self.storage_dir, market)
            if not os.path.exists(market_dir):
                continue
            for fname in os.listdir(market_dir):
                if not fname.endswith('.db'):
                    continue
                db_path = os.path.join(market_dir, fname)
                size = os.path.getsize(db_path)
                total_size += size
                std_code = fname.replace('.db', '')
                full_code = f"{market.lower()}.{std_code}"

                conn = duckdb.connect(db_path)
                try:
                    info = conn.execute("""
                        SELECT MIN(date) as min_date, MAX(date) as max_date, COUNT(*) as rows
                        FROM kline
                    """).fetchone()
                    stocks.append({
                        'code': std_code,
                        'market': market,
                        'min_date': info[0],
                        'max_date': info[1],
                        'rows': info[2],
                        'size_kb': round(size / 1024, 1),
                    })
                except:
                    pass
                finally:
                    conn.close()

        # 如果指定了 code，只返回该股票
        if code:
            std = _to_std_code(code)
            stocks = [s for s in stocks if s['code'] == std]

        return {
            'total_stocks': len(stocks),
            'total_size_mb': round(total_size / 1024 / 1024, 2),
            'stocks': stocks,
        }

    def clear_cache(self, code: str = None):
        """清理缓存"""
        if code:
            db_path = self._get_db_path(code)
            if os.path.exists(db_path):
                os.remove(db_path)
                print(f"🗑️ 已清理 {code} 缓存")
        else:
            import shutil
            if os.path.exists(self.storage_dir):
                shutil.rmtree(self.storage_dir)
                os.makedirs(self.storage_dir, exist_ok=True)
                print(f"🗑️ 已清空全部缓存")

    def __del__(self):
        """析构时清理"""
        try:
            pass
        except:
            pass


# ============ 便捷函数 ============

def get_cached_kline(code: str, start_date: str, end_date: str,
                     storage_dir: str = None, **kwargs) -> pd.DataFrame:
    """便捷函数：一行获取带缓存的 K 线"""
    cache = StockDataCache(storage_dir=storage_dir)
    return cache.get_kline(code, start_date, end_date, **kwargs)


def get_cached_klines_batch(codes: List[str], start_date: str, end_date: str,
                            storage_dir: str = None, **kwargs) -> Dict[str, pd.DataFrame]:
    """便捷函数：批量获取带缓存的 K 线"""
    cache = StockDataCache(storage_dir=storage_dir)
    return cache.get_klines_batch(codes, start_date, end_date, **kwargs)


if __name__ == "__main__":
    # 测试
    print("=== DuckDB 数据缓存测试 ===")
    cache = StockDataCache()

    # 测试1: 首次拉取
    print("\n--- 测试1: 首次拉取 ---")
    df1 = cache.get_kline('600519', '20250101', '20250815')
    print(f"获取到 {len(df1)} 条数据")
    print(df1.head(3))

    # 测试2: 第二次读取（应该走缓存）
    print("\n--- 测试2: 缓存读取 ---")
    df2 = cache.get_kline('600519', '20250101', '20250815')
    print(f"缓存读取 {len(df2)} 条数据")

    # 测试3: 缓存状态
    print("\n--- 测试3: 缓存状态 ---")
    status = cache.cache_status()
    print(f"缓存股票数: {status['total_stocks']}")
    print(f"总大小: {status['total_size_mb']} MB")
    for s in status['stocks'][:3]:
        print(f"  {s['code']}: {s['min_date']}~{s['max_date']} ({s['rows']}条, {s['size_kb']}KB)")

    # 测试4: 批量获取
    print("\n--- 测试4: 批量获取 ---")
    batch = cache.get_klines_batch(['600519', '000001'], '20250101', '20250815')
    for code, df in batch.items():
        print(f"  {code}: {len(df)} 条")
