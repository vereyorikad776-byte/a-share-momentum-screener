#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股量化交易系统 - 七套经典战法信号引擎
龙头首阴 / 龙回头 / 均线多头 / 箱体突破 / 量价齐升 / 缩量回踩 / 戴维斯双击
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass
from data_gateway import get_kline


@dataclass
class StrategySignal:
    """战法信号"""
    name: str           # 战法名称
    triggered: bool     # 是否触发
    strength: float     # 信号强度 0-1
    entry: float        # 建议入场价
    stop_loss: float    # 止损价
    target: float       # 目标价
    holding_days: int   # 建议持有天数
    reason: str         # 触发理由


class ClassicStrategies:
    """七套经典战法"""
    
    def __init__(self):
        self.strategies = [
            self.dragon_head_first_yin,
            self.dragon_return,
            self.ma_bull,
            self.box_breakout,
            self.volume_price_rise,
            self.shrinkage_pullback,
            self.davis_double_play
        ]
    
    def scan_all(self, code: str) -> List[StrategySignal]:
        """扫描所有战法信号"""
        signals = []
        for strategy in self.strategies:
            try:
                signal = strategy(code)
                if signal.triggered:
                    signals.append(signal)
            except Exception as e:
                print(f"战法扫描失败 {strategy.__name__}: {e}")
        
        # 按强度排序
        signals.sort(key=lambda x: x.strength, reverse=True)
        return signals
    
    def dragon_head_first_yin(self, code: str) -> StrategySignal:
        """
        龙头首阴战法
        连板龙头首阴+缩量低吸，1-2天
        """
        klines = get_kline(code, "day", 10)
        if len(klines) < 5:
            return StrategySignal("龙头首阴", False, 0, 0, 0, 0, 0, "")
        
        # 检查最近是否有连续涨停（简化：连续大涨）
        recent_changes = []
        for i in range(-5, 0):
            if i < -len(klines):
                break
            prev_close = klines[i-1].close if i > -len(klines) else klines[0].open
            change = (klines[i].close - prev_close) / prev_close * 100
            recent_changes.append(change)
        
        # 连续3天大涨（>7%）视为连板龙头
        consecutive_rises = sum(1 for c in recent_changes if c > 7)
        
        if consecutive_rises < 2:
            return StrategySignal("龙头首阴", False, 0, 0, 0, 0, 0, "")
        
        # 今日是否收阴
        today = klines[-1]
        yesterday = klines[-2]
        today_change = (today.close - yesterday.close) / yesterday.close * 100
        
        if today_change > -3:  # 需要明显收阴
            return StrategySignal("龙头首阴", False, 0, 0, 0, 0, 0, "")
        
        # 是否缩量
        volume_shrink = today.volume < yesterday.volume * 0.8
        
        if not volume_shrink:
            return StrategySignal("龙头首阴", False, 0, 0, 0, 0, 0, "")
        
        # 信号触发
        entry = today.close
        stop_loss = min(today.low, yesterday.close * 0.95)
        target = entry * 1.08
        
        strength = 0.7
        if consecutive_rises >= 3:
            strength = 0.9
        
        return StrategySignal(
            name="龙头首阴",
            triggered=True,
            strength=strength,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            holding_days=2,
            reason=f"连续{consecutive_rises}天大涨后首阴，缩量{((1-today.volume/yesterday.volume)*100):.0f}%"
        )
    
    def dragon_return(self, code: str) -> StrategySignal:
        """
        龙回头战法
        龙头回调15-30%二波启动，5-15天
        """
        klines = get_kline(code, "day", 40)
        if len(klines) < 20:
            return StrategySignal("龙回头", False, 0, 0, 0, 0, 0, "")
        
        closes = [k.close for k in klines]
        
        # 找前期高点和当前回调幅度
        high_20 = max(closes[-20:])
        current = closes[-1]
        pullback = (high_20 - current) / high_20 * 100
        
        if not (15 <= pullback <= 30):
            return StrategySignal("龙回头", False, 0, 0, 0, 0, 0, "")
        
        # 是否在支撑位止跌
        # 简化：检查最近3天是否企稳
        recent = closes[-3:]
        if not (recent[-1] >= recent[-2] * 0.98):  # 未企稳
            return StrategySignal("龙回头", False, 0, 0, 0, 0, 0, "")
        
        # 缩量
        volumes = [k.volume for k in klines]
        recent_vol = np.mean(volumes[-5:])
        prev_vol = np.mean(volumes[-15:-5])
        if recent_vol > prev_vol * 0.8:  # 未明显缩量
            return StrategySignal("龙回头", False, 0, 0, 0, 0, 0, "")
        
        entry = current
        stop_loss = current * 0.93
        target = high_20 * 0.95
        
        return StrategySignal(
            name="龙回头",
            triggered=True,
            strength=0.75,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            holding_days=10,
            reason=f"回调{pullback:.1f}%，缩量企稳"
        )
    
    def ma_bull(self, code: str) -> StrategySignal:
        """
        均线多头战法
        5>10>20>60多头排列回踩，10-30天
        """
        klines = get_kline(code, "day", 80)
        if len(klines) < 60:
            return StrategySignal("均线多头", False, 0, 0, 0, 0, 0, "")
        
        closes = [k.close for k in klines]
        
        # 计算均线
        ma5 = np.mean(closes[-5:])
        ma10 = np.mean(closes[-10:])
        ma20 = np.mean(closes[-20:])
        ma60 = np.mean(closes[-60:])
        
        # 多头排列
        if not (ma5 > ma10 > ma20 > ma60):
            return StrategySignal("均线多头", False, 0, 0, 0, 0, 0, "")
        
        # 是否回踩10日或20日线
        current = closes[-1]
        distance_to_10 = abs(current - ma10) / ma10
        distance_to_20 = abs(current - ma20) / ma20
        
        if distance_to_10 > 0.05 and distance_to_20 > 0.05:
            return StrategySignal("均线多头", False, 0, 0, 0, 0, 0, "")
        
        # 缩量
        volumes = [k.volume for k in klines]
        recent_vol = np.mean(volumes[-3:])
        avg_vol = np.mean(volumes[-20:])
        if recent_vol > avg_vol * 0.7:
            return StrategySignal("均线多头", False, 0, 0, 0, 0, 0, "")
        
        entry = current
        stop_loss = ma20 * 0.95
        target = current * 1.15
        
        strength = 0.8 if current > ma20 else 0.6
        
        return StrategySignal(
            name="均线多头",
            triggered=True,
            strength=strength,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            holding_days=15,
            reason=f"多头排列，回踩{'10日线' if distance_to_10 < distance_to_20 else '20日线'}"
        )
    
    def box_breakout(self, code: str) -> StrategySignal:
        """
        箱体突破战法
        横盘20-60天放量突破，10-30天
        """
        klines = get_kline(code, "day", 80)
        if len(klines) < 30:
            return StrategySignal("箱体突破", False, 0, 0, 0, 0, 0, "")
        
        closes = [k.close for k in klines[-60:]]
        
        # 检查是否横盘
        box_high = max(closes)
        box_low = min(closes)
        box_range = (box_high - box_low) / box_low * 100
        
        if box_range > 25:  # 波动太大，不是箱体
            return StrategySignal("箱体突破", False, 0, 0, 0, 0, 0, "")
        
        # 今日是否突破
        today = klines[-1]
        yesterday = klines[-2]
        
        if today.close <= box_high * 1.02:  # 未突破上轨
            return StrategySignal("箱体突破", False, 0, 0, 0, 0, 0, "")
        
        # 放量
        if today.volume < np.mean([k.volume for k in klines[-20:]]) * 1.5:
            return StrategySignal("箱体突破", False, 0, 0, 0, 0, 0, "")
        
        entry = today.close
        stop_loss = box_high * 0.97
        target = entry + (box_high - box_low)
        
        return StrategySignal(
            name="箱体突破",
            triggered=True,
            strength=0.85,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            holding_days=15,
            reason=f"横盘{len(closes)}天，放量突破箱体"
        )
    
    def volume_price_rise(self, code: str) -> StrategySignal:
        """
        量价齐升战法
        价涨量增动量跟进，5-15天
        """
        klines = get_kline(code, "day", 20)
        if len(klines) < 10:
            return StrategySignal("量价齐升", False, 0, 0, 0, 0, 0, "")
        
        recent = klines[-5:]
        
        # 检查是否价涨量增
        price_up_days = 0
        volume_increase = True
        
        for i in range(1, len(recent)):
            if recent[i].close > recent[i-1].close:
                price_up_days += 1
            if recent[i].volume < recent[i-1].volume * 0.8:
                volume_increase = False
        
        if price_up_days < 3 or not volume_increase:
            return StrategySignal("量价齐升", False, 0, 0, 0, 0, 0, "")
        
        # 涨幅不过大（15%-30%）
        total_change = (recent[-1].close - recent[0].close) / recent[0].close * 100
        if not (10 <= total_change <= 35):
            return StrategySignal("量价齐升", False, 0, 0, 0, 0, 0, "")
        
        entry = recent[-1].close
        stop_loss = recent[-1].close * 0.95
        target = entry * 1.12
        
        return StrategySignal(
            name="量价齐升",
            triggered=True,
            strength=0.7,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            holding_days=7,
            reason=f"5日{price_up_days}天上涨，量价齐升"
        )
    
    def shrinkage_pullback(self, code: str) -> StrategySignal:
        """
        缩量回踩战法
        上涨回调量能萎缩，5-15天
        """
        klines = get_kline(code, "day", 30)
        if len(klines) < 15:
            return StrategySignal("缩量回踩", False, 0, 0, 0, 0, 0, "")
        
        closes = [k.close for k in klines]
        
        # 前期上升趋势
        if closes[-10] <= closes[-15] * 1.05:  # 前期涨幅不足
            return StrategySignal("缩量回踩", False, 0, 0, 0, 0, 0, "")
        
        # 最近回调
        recent = klines[-7:]
        pullback = (max([k.close for k in recent[:-1]]) - recent[-1].close) / max([k.close for k in recent[:-1]]) * 100
        
        if not (3 <= pullback <= 12):
            return StrategySignal("缩量回踩", False, 0, 0, 0, 0, 0, "")
        
        # 缩量
        recent_vol = np.mean([k.volume for k in recent[-3:]])
        prev_vol = np.mean([k.volume for k in klines[-15:-5]])
        if recent_vol > prev_vol * 0.6:
            return StrategySignal("缩量回踩", False, 0, 0, 0, 0, 0, "")
        
        # 止跌信号
        today = klines[-1]
        if today.close < today.open * 0.98:  # 阴线，未止跌
            return StrategySignal("缩量回踩", False, 0, 0, 0, 0, 0, "")
        
        entry = today.close
        stop_loss = min(today.low, recent[-1].close * 0.95)
        target = max([k.close for k in recent]) * 1.05
        
        return StrategySignal(
            name="缩量回踩",
            triggered=True,
            strength=0.75,
            entry=entry,
            stop_loss=stop_loss,
            target=target,
            holding_days=7,
            reason=f"回调{pullback:.1f}%，缩量至前期{recent_vol/prev_vol*100:.0f}%"
        )
    
    def davis_double_play(self, code: str) -> StrategySignal:
        """
        戴维斯双击战法
        业绩+估值双提升，1-3月
        """
        # 这是一个基本面战法，需要财务数据
        # 简化版：假设通过其他数据源获取
        
        # 实际实现需要：
        # 1. 查询最近2季度业绩增速
        # 2. 查询当前PE及历史分位
        # 3. 查询机构持仓变化
        
        # 由于需要财务数据接口，这里返回未触发
        # 实际使用时需要接入ifind/ftshare
        
        return StrategySignal("戴维斯双击", False, 0, 0, 0, 0, 0, "需要财务数据接口")


# 全局实例
strategies = ClassicStrategies()


def scan_classic_strategies(code: str) -> List[StrategySignal]:
    """便捷函数：扫描经典战法"""
    return strategies.scan_all(code)


if __name__ == "__main__":
    # 测试
    signals = scan_classic_strategies("000983")
    print(f"\n扫描到 {len(signals)} 个战法信号:")
    for s in signals:
        print(f"  [{s.name}] 强度:{s.strength:.0%} 入场:{s.entry:.2f} 止损:{s.stop_loss:.2f} 目标:{s.target:.2f}")
        print(f"    理由: {s.reason}")
