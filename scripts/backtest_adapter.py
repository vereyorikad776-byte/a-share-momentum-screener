"""
backtest_adapter.py - Backtrader回测适配器 v2.2r

将v22评分系统接入Backtrader回测框架
支持：
1. 单策略回测（v22评分选股）
2. 多策略对比
3. 完整回测报告（资金曲线、夏普比率、最大回撤）

依赖: pip install backtrader
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional

from v22_engine import run_v22_scoring


class V22Strategy(bt.Strategy):
    """
    v22评分策略 - Backtrader适配
    
    每天收盘后：
    1. 对全市场候选票跑v22评分
    2. 选出S/A级且action="买"的票
    3. 次日开盘价买入
    4. 持仓票触发止损/止盈时卖出
    """
    
    params = (
        ('max_positions', 4),
        ('position_pct', 0.20),  # 单票仓位
        ('stop_loss', -0.07),
        ('take_profit_1', 0.03),
        ('take_profit_2', 0.06),
        ('take_profit_3', 0.10),
        ('max_hold_days', 10),
        ('rebalance_freq', 5),  # 每5天调仓
    )
    
    def __init__(self):
        self.holdings = {}  # {code: {'entry_price': ..., 'entry_date': ..., 'highest': ...}}
        self.trade_log = []
        
    def next(self):
        """每天收盘后执行"""
        current_date = self.datas[0].datetime.date(0)
        
        # 检查持仓风控
        self._check_risk_management()
        
        # 按调仓频率执行
        if len(self) % self.params.rebalance_freq == 0:
            self._rebalance()
    
    def _check_risk_management(self):
        """检查持仓的止损/止盈/时间止损"""
        to_sell = []
        
        for code, info in list(self.holdings.items()):
            # 找到对应的数据
            data = None
            for d in self.datas:
                if d._name == code:
                    data = d
                    break
            
            if data is None:
                continue
            
            current_price = data.close[0]
            entry_price = info['entry_price']
            entry_date = info['entry_date']
            highest = info.get('highest', entry_price)
            
            # 更新最高价
            if current_price > highest:
                self.holdings[code]['highest'] = current_price
                highest = current_price
            
            # 计算盈亏
            gain_pct = (current_price - entry_price) / entry_price
            
            # 硬止损 -7%
            if gain_pct <= self.params.stop_loss:
                to_sell.append((code, "硬止损", gain_pct))
                continue
            
            # 阶梯止盈
            max_gain = (highest - entry_price) / entry_price
            retrace = (highest - current_price) / entry_price
            
            if max_gain >= self.params.take_profit_3 and retrace >= 0.08:
                to_sell.append((code, "止盈三档", gain_pct))
            elif max_gain >= self.params.take_profit_2 and retrace >= 0.05:
                to_sell.append((code, "止盈二档", gain_pct))
            elif max_gain >= self.params.take_profit_1 and retrace >= 0.03:
                to_sell.append((code, "止盈一档", gain_pct))
            
            # 时间止损
            hold_days = (self.datas[0].datetime.date(0) - entry_date).days
            if hold_days >= self.params.max_hold_days:
                to_sell.append((code, "时间止损", gain_pct))
        
        # 执行卖出
        for code, reason, gain in to_sell:
            self._sell_stock(code, reason, gain)
    
    def _sell_stock(self, code: str, reason: str, gain_pct: float):
        """卖出股票"""
        for d in self.datas:
            if d._name == code:
                size = self.getposition(d).size
                if size > 0:
                    self.sell(data=d, size=size)
                    self.trade_log.append({
                        'date': self.datas[0].datetime.date(0),
                        'code': code,
                        'action': 'SELL',
                        'reason': reason,
                        'gain_pct': gain_pct,
                    })
                    if code in self.holdings:
                        del self.holdings[code]
                break
    
    def _rebalance(self):
        """调仓：卖出X级，买入S/A级"""
        # 获取当前持仓数量
        current_positions = len([p for p in self.holdings.values()])
        
        # 对所有候选票跑v22评分（简化版，实际需要接入数据）
        candidates = []
        for d in self.datas:
            code = d._name
            if code in self.holdings:
                continue  # 已持仓
            
            # 构建数据
            data = {
                'code': code,
                'close': d.close[0],
                'open': d.open[0],
                'high': d.high[0],
                'low': d.low[0],
                'volume': d.volume[0],
                'change_pct': (d.close[0] - d.close[-1]) / d.close[-1] if d.close[-1] > 0 else 0,
                'ma5': np.mean([d.close[-i] for i in range(5)]),
                'ma10': np.mean([d.close[-i] for i in range(10)]),
                'ma20': np.mean([d.close[-i] for i in range(20)]),
            }
            
            # 运行v22评分
            try:
                result = run_v22_scoring(data)
                if result.get('tier') in ['S', 'A'] and result.get('action') == '买':
                    candidates.append((code, result['final_score'], d))
            except:
                continue
        
        # 按评分排序，买入Top N
        candidates.sort(key=lambda x: x[1], reverse=True)
        
        for code, score, data in candidates:
            if current_positions >= self.params.max_positions:
                break
            
            # 计算买入数量
            cash = self.broker.getcash()
            price = data.close[0]
            max_value = self.broker.getvalue() * self.params.position_pct
            size = int(max_value / price / 100) * 100  # 100股整数倍
            
            if size < 100 or size * price > cash:
                continue
            
            # 买入
            self.buy(data=data, size=size)
            self.holdings[code] = {
                'entry_price': price,
                'entry_date': self.datas[0].datetime.date(0),
                'highest': price,
            }
            current_positions += 1
            
            self.trade_log.append({
                'date': self.datas[0].datetime.date(0),
                'code': code,
                'action': 'BUY',
                'score': score,
            })


class V22Analyzer(bt.Analyzer):
    """v22策略分析器"""
    
    def __init__(self):
        self.returns = []
        self.trades = []
    
    def next(self):
        value = self._owner.broker.getvalue()
        self.returns.append(value)
    
    def get_analysis(self):
        returns = pd.Series(self.returns)
        total_return = (returns.iloc[-1] / returns.iloc[0] - 1) if len(returns) > 0 else 0
        
        # 计算夏普比率（简化版）
        daily_returns = returns.pct_change().dropna()
        sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0
        
        # 最大回撤
        cummax = returns.cummax()
        drawdown = (returns - cummax) / cummax
        max_drawdown = drawdown.min()
        
        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
        }


def run_backtest(data_dict: Dict[str, pd.DataFrame], 
                 start_date: str = '20240101',
                 end_date: str = '20241231',
                 initial_cash: float = 1000000.0) -> dict:
    """
    运行v22策略回测
    
    Args:
        data_dict: {code: DataFrame}，每个DataFrame需包含open/high/low/close/volume
        start_date: 回测开始日期
        end_date: 回测结束日期
        initial_cash: 初始资金
    
    Returns:
        {"total_return": ..., "sharpe": ..., "max_drawdown": ..., "trade_log": [...]}
    """
    cerebro = bt.Cerebro()
    
    # 添加数据
    for code, df in data_dict.items():
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        data = bt.feeds.PandasData(
            dataname=df,
            name=code,
            fromdate=datetime.strptime(start_date, '%Y%m%d'),
            todate=datetime.strptime(end_date, '%Y%m%d'),
        )
        cerebro.adddata(data)
    
    # 添加策略
    cerebro.addstrategy(V22Strategy)
    
    # 设置资金
    cerebro.broker.setcash(initial_cash)
    
    # 设置手续费（万3，最低5元）
    cerebro.broker.setcommission(commission=0.0003, mincommission=5)
    
    # 添加分析器
    cerebro.addanalyzer(V22Analyzer, _name='v22_analyzer')
    
    # 运行回测
    print(f"\n{'='*60}")
    print(f"开始回测: {start_date} ~ {end_date}")
    print(f"初始资金: {initial_cash:,.0f}")
    print(f"{'='*60}")
    
    results = cerebro.run()
    strat = results[0]
    
    # 获取结果
    final_value = cerebro.broker.getvalue()
    analysis = strat.analyzers.v22_analyzer.get_analysis()
    
    result = {
        'start_date': start_date,
        'end_date': end_date,
        'initial_cash': initial_cash,
        'final_value': final_value,
        'total_return': analysis['total_return'],
        'sharpe_ratio': analysis['sharpe_ratio'],
        'max_drawdown': analysis['max_drawdown'],
        'trade_count': len(strat.trade_log),
        'trade_log': strat.trade_log,
    }
    
    print(f"\n{'='*60}")
    print(f"回测结果")
    print(f"{'='*60}")
    print(f"总收益率: {result['total_return']*100:.2f}%")
    print(f"夏普比率: {result['sharpe_ratio']:.2f}")
    print(f"最大回撤: {result['max_drawdown']*100:.2f}%")
    print(f"交易次数: {result['trade_count']}")
    print(f"最终资金: {result['final_value']:,.0f}")
    
    return result


if __name__ == "__main__":
    print("Backtrader适配器已就绪")
    print("用法:")
    print("  from backtest_adapter import run_backtest")
    print("  result = run_backtest(data_dict, '20240101', '20241231')")
