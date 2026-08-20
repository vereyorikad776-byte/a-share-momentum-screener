#!/usr/bin/env python3
"""
data_source_manager.py — 多数据源智能管理
优先级: iFinD(盘中实时) > Baostock(盘后历史) > stock_finance_data(备选历史) > iFinD兜底
"""

import sys, time, warnings
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings('ignore')
sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import baostock as bs
from ifind_call import call


class DataSourceManager:
    """多数据源智能管理器"""
    
    # 数据源优先级配置
    PRIORITY = {
        'intraday': ['ifind'],           # 盘中实时：只用iFinD
        'post_close': ['stock_finance_data', 'baostock', 'akshare', 'ifind'],  # 盘后：同花顺→Baostock→akshare→iFinD
        'fallback': ['stock_finance_data', 'akshare', 'ifind'],  # Baostock不可用时的回退链
    }
    
    def __init__(self):
        self.baostock_available = False
        self.baostock_session = None
        self._check_baostock()
    
    def _check_baostock(self):
        """检测Baostock是否可用"""
        try:
            lg = bs.login()
            if lg.error_code == '0':
                self.baostock_available = True
                self.baostock_session = lg
                print("✅ Baostock 可用")
            else:
                self.baostock_available = False
                print(f"❌ Baostock 不可用: {lg.error_msg}")
                try:
                    bs.logout()
                except:
                    pass
        except Exception as e:
            self.baostock_available = False
            print(f"❌ Baostock 连接失败: {e}")
    
    def is_trading_hours(self):
        """判断是否在交易时间 (9:30-11:30, 13:00-15:00)"""
        now = datetime.now()
        weekday = now.weekday()
        if weekday >= 5:  # 周末
            return False
        
        hour, minute = now.hour, now.minute
        time_val = hour * 100 + minute
        
        # 9:30-11:30 或 13:00-15:00
        return (930 <= time_val <= 1130) or (1300 <= time_val <= 1500)
    
    def get_active_chain(self):
        """获取当前活跃的数据源链"""
        if self.is_trading_hours():
            print("📊 当前为盘中交易时间，使用iFinD实时数据")
            return self.PRIORITY['intraday']
        else:
            if self.baostock_available:
                print("📊 盘后时间，Baostock可用，使用完整历史K线")
                return self.PRIORITY['post_close']
            else:
                print("📊 盘后时间，Baostock不可用，使用备选数据源")
                return self.PRIORITY['fallback']
    
    def fetch_history_kline(self, code, days=25, end_date=None):
        """
        智能获取历史K线，按优先级尝试数据源
        
        Returns:
            DataFrame or None
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days*2)).strftime('%Y-%m-%d')
        
        chain = self.get_active_chain()
        
        for source in chain:
            try:
                if source == 'baostock':
                    df = self._fetch_baostock(code, start_date, end_date)
                    if df is not None and len(df) >= 20:
                        print(f"  ✅ Baostock成功: {code}")
                        return df
                
                elif source == 'stock_finance_data':
                    df = self._fetch_stock_finance_data(code, start_date, end_date)
                    if df is not None and len(df) >= 20:
                        print(f"  ✅ stock_finance_data成功: {code}")
                        return df
                
                elif source == 'ifind':
                    df = self._fetch_ifind_history(code, start_date, end_date)
                    if df is not None and len(df) >= 20:
                        print(f"  ✅ iFinD历史K线成功: {code}")
                        return df
                        
            except Exception as e:
                print(f"  ⚠️ {source}失败: {e}")
                continue
        
        print(f"  ❌ 所有数据源均无法获取 {code}")
        return None
    
    def _fetch_baostock(self, code, start_date, end_date):
        """Baostock获取K线"""
        import pandas as pd
        
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
            return df.dropna()
        return None
    
    def _fetch_stock_finance_data(self, code, start_date, end_date):
        """同花顺API获取历史K线（直接调用kimi_datasource_call）"""
        import pandas as pd
        import subprocess, json, os
        
        suffix = 'SH' if code.startswith('6') else 'SZ'
        ticker = f"{code}.{suffix}"
        out_file = f"/tmp/kline_{code}.csv"
        
        try:
            # 如果已有有效文件，直接读取
            if os.path.exists(out_file):
                df = pd.read_csv(out_file)
                if len(df) >= 20:
                    # 检查日期范围
                    first = str(df.iloc[0].get('time', df.iloc[0].get('date', '')))
                    last = str(df.iloc[-1].get('time', df.iloc[-1].get('date', '')))
                    if first >= start_date and last <= end_date:
                        return df
            
            # 调用同花顺API
            result = subprocess.run(
                ['openclaw', 'tool', 'kimi_datasource_call',
                 '--data_source_name', 'stock_finance_data',
                 '--api_name', 'stock_finance_data_get_price',
                 '--params', json.dumps({
                     'ticker': ticker,
                     'start_date': start_date,
                     'end_date': end_date,
                     'adjust': 'forward',
                     'frequency': 'daily',
                     'file_path': out_file
                 })],
                capture_output=True, text=True, timeout=45
            )
            
            # 读取结果
            if os.path.exists(out_file):
                df = pd.read_csv(out_file)
                if len(df) >= 20:
                    # 重命名列兼容
                    if 'time' in df.columns and 'date' not in df.columns:
                        df = df.rename(columns={'time': 'date'})
                    
                    # 确保数值列正确
                    for col in ['open','high','low','close','volume']:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # 计算涨跌幅和preclose
                    df['preclose'] = df['close'].shift(1)
                    df['pctChg'] = (df['close'] / df['preclose'] - 1) * 100
                    
                    return df.dropna()
            
            return None
            
        except Exception as e:
            print(f"    同花顺API异常: {e}")
            return None
    
    def _fetch_ifind_history(self, code, start_date, end_date):
        """iFinD获取历史K线（兜底）"""
        # iFinD主要提供实时数据，历史K线能力有限
        # 这里可以作为最后的兜底方案
        return None
    
    def cleanup(self):
        """清理资源"""
        if self.baostock_session:
            try:
                bs.logout()
            except:
                pass

    def update_pool_prices(self, db_path, batch_size=10):
        """
        更新 pools 表中所有票的最新行情
        从本地K线缓存获取最新价格并更新DuckDB
        """
        import duckdb
        import pandas as pd
        import os
        
        if not os.path.exists(db_path):
            print(f"❌ 数据库不存在: {db_path}")
            return 0
        
        conn = duckdb.connect(db_path)
        
        # 获取所有池子中的唯一代码
        codes = conn.execute("SELECT DISTINCT code FROM pools").fetchall()
        codes = [c[0] for c in codes]
        
        print(f"📊 池子中共有 {len(codes)} 只票需要更新价格")
        
        updated = 0
        failed = []
        
        for i, code in enumerate(codes):
            try:
                # 从本地K线缓存获取最新价格
                kline_file = f'/tmp/kline_{code}.csv'
                if os.path.exists(kline_file):
                    df = pd.read_csv(kline_file)
                    if len(df) > 0:
                        latest = df.iloc[-1]
                        close = float(latest.get('close', 0))
                        
                        # 计算涨跌幅（需要前一日价格）
                        if len(df) >= 2:
                            prev_close = float(df.iloc[-2].get('close', close))
                            change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                        else:
                            change_pct = 0
                        
                        volume = float(latest.get('volume', 0))
                        
                        # 更新数据库
                        conn.execute("""
                            UPDATE pools 
                            SET close_price = ?, change_pct = ?, volume = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE code = ?
                        """, [close, change_pct, volume, code])
                        updated += 1
                        continue
                
                # 本地没有缓存
                failed.append(code)
                
            except Exception as e:
                failed.append(code)
                print(f"  ⚠️ {code} 更新失败: {e}")
            
            if (i + 1) % 20 == 0:
                print(f"  进度: {i+1}/{len(codes)}")
        
        conn.commit()
        conn.close()
        
        print(f"\n✅ 价格更新完成: {updated}/{len(codes)} 只成功")
        if failed:
            print(f"❌ 失败 {len(failed)} 只: {', '.join(failed[:10])}{'...' if len(failed)>10 else ''}")
        
        return updated


# 全局单例
ds_manager = DataSourceManager()


def get_kline_smart(code, days=25):
    """智能获取K线的便捷函数"""
    return ds_manager.fetch_history_kline(code, days)


def is_baostock_available():
    """检查Baostock是否可用"""
    return ds_manager.baostock_available


if __name__ == "__main__":
    # 测试
    print("数据源管理器测试")
    print(f"Baostock可用: {ds_manager.baostock_available}")
    print(f"当前交易时间: {ds_manager.is_trading_hours()}")
    print(f"活跃链: {ds_manager.get_active_chain()}")
    
    # 测试获取K线
    df = get_kline_smart('000657', days=25)
    if df is not None:
        print(f"\n✅ 获取成功: {len(df)}条K线")
        print(df.tail(3))
    else:
        print("\n❌ 获取失败")
    
    ds_manager.cleanup()
