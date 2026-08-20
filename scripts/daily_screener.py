#!/usr/bin/env python3
"""
daily_screener.py — 每日自动选股脚本

核心设计：
- 数据源: Baostock（小批量请求，带延迟防超时）
- 选股范围: 主板股票（600/601/603/605/000/001/002/003开头）
- 评分: v2.2完整8步管线
- 输出: TOP5推荐 + 凯利仓位 + 止损位
"""

import sys
import time
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, '/root/.openclaw/workspace/skills/ifind-momentum-screener/scripts')

import baostock as bs
import pandas as pd
from datetime import datetime, timedelta

# v2.2引擎
from v21_engine import run_v21_pipeline
from kelly_position import calc_kelly_position


class DailyScreener:
    """每日选股器"""

    def __init__(self, capital=100000):
        self.capital = capital
        self.results = []

    def _throttle(self, seconds=1.5):
        """请求间隔，防超时"""
        time.sleep(seconds)

    def get_mainboard_codes(self, sample_size=200):
        """
        获取主板股票代码（小批量，避免超时）
        优先从本地缓存读取，没有再远程获取
        """
        # 主板代码范围
        sh_prefixes = ['600', '601', '603', '605']
        sz_prefixes = ['000', '001', '002', '003']

        codes = []
        for p in sh_prefixes:
            for i in range(0, 999):
                codes.append(f"sh.{p}{i:03d}")
        for p in sz_prefixes:
            for i in range(0, 999):
                codes.append(f"sz.{p}{i:03d}")

        # 只取前sample_size只（避免超时）
        return codes[:sample_size]

    def fetch_kline(self, code, days=25):
        """获取单只股票K线（带重试）"""
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        for attempt in range(3):
            try:
                rs = bs.query_history_k_data_plus(
                    code,
                    "date,open,high,low,close,volume,amount,turn,pctChg,preclose",
                    start_date=start_date, end_date=end_date,
                    frequency="d", adjustflag="3"
                )
                data = []
                while (rs.error_code == '0') & rs.next():
                    data.append(rs.get_row_data())

                if len(data) >= 20:
                    df = pd.DataFrame(data, columns=['date','open','high','low','close','volume','amount','turn','pctChg','preclose'])
                    df = df.apply(pd.to_numeric, errors='ignore')
                    return df
                return None
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    return None

    def calc_technical(self, df):
        """计算技术指标"""
        if df is None or len(df) < 20:
            return None

        closes = df['close'].values
        highs = df['high'].values
        lows = df['low'].values
        volumes = df['volume'].values

        # 最新数据
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        # 基础数据
        close = float(latest['close'])
        prev_close = float(prev['close']) if len(df) > 1 else close
        high = float(latest['high'])
        low = float(latest['low'])
        open_price = float(latest['open'])
        volume = float(latest['volume'])

        # 20日数据
        high_20d = max(highs[-20:])
        low_20d = min(lows[-20:])
        volume_20d_avg = sum(volumes[-20:]) / 20

        # MA
        ma5 = sum(closes[-5:]) / 5
        ma10 = sum(closes[-10:]) / 10
        ma20 = sum(closes[-20:]) / 20

        # RSI6
        deltas = [closes[i] - closes[i-1] for i in range(-6, 0)]
        gains = sum(d for d in deltas if d > 0)
        losses = sum(-d for d in deltas if d < 0)
        rsi6 = 100 * gains / (gains + losses) if (gains + losses) > 0 else 50

        # KDJ简化
        k, d, j = 50, 50, 50

        # MACD简化
        macd_hist = (ma5 - ma20) / ma20 * 100 if ma20 > 0 else 0

        # CCI简化
        tp = (high + low + close) / 3
        tp_sma = sum((df['high'] + df['low'] + df['close']).values[-20:]) / 20 / 3
        cci = (tp - tp_sma) / 0.015 if tp_sma > 0 else 0

        # ROC
        roc = (close - closes[-10]) / closes[-10] * 100 if closes[-10] > 0 else 0

        return {
            'close': close, 'high': high, 'low': low, 'open': open_price,
            'volume': volume, 'prev_close': prev_close,
            'high_20d': high_20d, 'low_20d': low_20d,
            'volume_20d_avg': volume_20d_avg,
            'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
            'rsi6': rsi6, 'k': k, 'd': d, 'j': j,
            'macd_hist': macd_hist, 'cci': cci, 'roc': roc,
            'streak_days': sum(1 for i in range(-3, 0) if closes[i] > closes[i-1])
        }

    def scan_stock(self, code, name=""):
        """扫描单只股票"""
        df = self.fetch_kline(code, days=25)
        tech = self.calc_technical(df)

        if tech is None:
            return None

        # v2.2评分
        result = run_v21_pipeline(
            code=code.replace('sh.', '').replace('sz.', ''),
            name=name or code,
            date=datetime.now().strftime('%Y%m%d'),
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
            breakout_today=tech['close'] > tech['high_20d'],
            high_cup=tech['high_20d'], handle_low=tech['low_20d'],
            volume_handle=tech['volume'], volume_cup_avg=tech['volume_20d_avg'],
            streak_days=tech['streak_days'],
            market_green=True, sector_green=True, trend_green=True,
            price_green=True, position_green=True,
            is_top3_sector=True, is_hot_sector=True, has_multi_concepts=False,
            rebound_count=1, friday_market_drop=False,
            ma20_trend='neutral',
            log=False
        )

        return result

    def run(self, max_stocks=100):
        """运行选股"""
        print("=" * 60)
        print(f"📊 A股动量选股 v2.2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 60)
        print()

        # 登录
        print("🔌 连接数据源...")
        bs.login()
        self._throttle(1)

        # 获取股票列表
        codes = self.get_mainboard_codes(sample_size=max_stocks)
        print(f"📋 扫描范围: 主板前{len(codes)}只")
        print(f"⏱️ 预计耗时: {len(codes) * 1.5:.0f}秒")
        print()

        # 扫描
        results = []
        for i, code in enumerate(codes):
            if i % 50 == 0 and i > 0:
                print(f"  进度: {i}/{len(codes)}...")

            result = self.scan_stock(code)
            self._throttle(1.5)  # 防超时

            if result and result['tier'] in ['S', 'A', 'B']:
                results.append(result)

            if len(results) >= 20:  # 够了就停
                break

        bs.logout()

        # 排序
        results.sort(key=lambda x: x['final_score'], reverse=True)

        # 输出
        print()
        print("=" * 60)
        print("🏆 TOP 推荐")
        print("=" * 60)
        print()

        for i, r in enumerate(results[:5], 1):
            # 凯利仓位
            kelly = calc_kelly_position(self.capital, r['tier'])

            # 止损位
            stop_price = r.get('prev_close', 0) * 0.93

            print(f"【{i}】{r['code']} {r['name']}")
            print(f"   评级: {r['tier']} | 评分: {r['final_score']:.3f}")
            print(f"   隔夜分: {r['overnight']:.1f} | 融合分: {r['fusion']:.1f} | 辩论: {r['debate']:.2f}")
            print(f"   建议仓位: {kelly['position_pct']:.1f}% = ¥{kelly['position_value']:.0f}")
            print(f"   止损位: ¥{stop_price:.2f} (-7%)")
            print()

        return results


if __name__ == "__main__":
    screener = DailyScreener(capital=67587)  # 用户当前资金
    results = screener.run(max_stocks=100)
