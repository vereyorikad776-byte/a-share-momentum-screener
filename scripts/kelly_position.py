#!/usr/bin/env python3
"""
kelly_position.py — 凯利公式动态仓位管理

核心思想：根据策略实际胜率和盈亏比，动态计算最优仓位。
不是固定20%，而是该重仓时重仓，该轻仓时轻仓。

公式：f* = (bp - q) / b
  p = 胜率, q = 败率 = 1-p, b = 盈亏比

实际使用半凯利（50%）更保守：f = f* × 0.5
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

FEEDBACK_LOG = "/root/.openclaw/workspace/skills/ifind-momentum-screener/data/feedback_log.jsonl"


class KellyPositionManager:
    """凯利公式动态仓位管理器"""

    def __init__(self, min_position_pct: float = 0.10, max_position_pct: float = 0.25,
                 lookback_days: int = 60, default_win_rate: float = 0.55,
                 default_win_loss_ratio: float = 1.5):
        """
        Args:
            min_position_pct: 最小单票仓位（避免凯利过低时空仓）
            max_position_pct: 最大单票仓位（风险控制上限）
            lookback_days: 回看历史交易天数
            default_win_rate: 默认胜率（无历史数据时使用）
            default_win_loss_ratio: 默认盈亏比（无历史数据时使用）
        """
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.lookback_days = lookback_days
        self.default_win_rate = default_win_rate
        self.default_win_loss_ratio = default_win_loss_ratio
        self._cache = None
        self._cache_time = None

    def _read_feedback_log(self) -> List[Dict]:
        """读取反馈日志"""
        if not os.path.exists(FEEDBACK_LOG):
            return []
        entries = []
        with open(FEEDBACK_LOG, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except:
                        pass
        return entries

    def calculate_kelly(self, trades: List[float]) -> Tuple[float, float, float]:
        """
        根据历史交易计算凯利比例

        Args:
            trades: 交易收益率列表（如 [0.03, -0.04, 0.05, -0.02]）

        Returns:
            (kelly_pct, win_rate, win_loss_ratio)
        """
        if not trades or len(trades) < 10:
            # 数据不足，使用默认值
            return self._default_kelly()

        wins = [t for t in trades if t > 0]
        losses = [t for t in trades if t < 0]

        if not wins or not losses:
            return self._default_kelly()

        win_rate = len(wins) / len(trades)
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))

        if avg_loss == 0:
            return self._default_kelly()

        win_loss_ratio = avg_win / avg_loss

        # 凯利公式：f* = (bp - q) / b
        # p = 胜率, q = 败率, b = 盈亏比
        q = 1 - win_rate
        kelly = (win_rate * win_loss_ratio - q) / win_loss_ratio

        return max(0, kelly), win_rate, win_loss_ratio

    def _default_kelly(self) -> Tuple[float, float, float]:
        """使用默认参数计算凯利"""
        q = 1 - self.default_win_rate
        kelly = (self.default_win_rate * self.default_win_loss_ratio - q) / self.default_win_loss_ratio
        return max(0, kelly), self.default_win_rate, self.default_win_loss_ratio

    def get_position_size(self, total_capital: float, tier: str = 'B',
                          use_half_kelly: bool = True) -> Dict:
        """
        计算建议仓位

        Args:
            total_capital: 总资金
            tier: 股票评级 S/A/B/C
            use_half_kelly: 是否使用半凯利（推荐）

        Returns:
            {
                'kelly_pct': 凯利比例,
                'half_kelly_pct': 半凯利比例,
                'position_pct': 实际仓位比例,
                'position_value': 实际仓位金额,
                'win_rate': 胜率,
                'win_loss_ratio': 盈亏比,
                'tier_boost': 评级加成,
                'reason': 说明
            }
        """
        # 1. 获取历史交易数据
        entries = self._read_feedback_log()
        cutoff = (datetime.now() - timedelta(days=self.lookback_days)).strftime("%Y%m%d")

        # 只取有实际收益的
        recent = [e for e in entries
                  if e.get('date', '0') >= cutoff
                  and e.get('actual_return_1d') is not None]

        # 2. 计算凯利
        if len(recent) >= 10:
            trades = [e['actual_return_1d'] for e in recent]
            kelly, win_rate, wlr = self.calculate_kelly(trades)
            reason = f"基于{len(recent)}笔历史交易"
        else:
            kelly, win_rate, wlr = self._default_kelly()
            reason = f"历史数据不足({len(recent)}笔)，使用默认参数"

        # 3. 半凯利
        half_kelly = kelly * 0.5

        # 4. 评级加成（S/A级更值得重仓）
        tier_multipliers = {'S': 1.2, 'A': 1.1, 'B': 1.0, 'C': 0.8}
        tier_boost = tier_multipliers.get(tier, 1.0)

        # 5. 计算最终仓位
        position_pct = half_kelly * tier_boost

        # 6. 边界控制
        position_pct = max(self.min_position_pct, min(self.max_position_pct, position_pct))

        return {
            'kelly_pct': round(kelly * 100, 2),
            'half_kelly_pct': round(half_kelly * 100, 2),
            'position_pct': round(position_pct * 100, 2),
            'position_value': round(total_capital * position_pct, 2),
            'win_rate': round(win_rate * 100, 1),
            'win_loss_ratio': round(wlr, 2),
            'tier_boost': tier_boost,
            'reason': reason
        }

    def get_market_kelly(self, total_capital: float, market_trend: str = 'neutral') -> Dict:
        """
        根据市场环境调整整体仓位

        Args:
            total_capital: 总资金
            market_trend: 市场趋势 up/down/neutral

        Returns:
            建议总仓位
        """
        result = self.get_position_size(total_capital, tier='B')

        # 市场环境调整
        if market_trend == 'up':
            result['position_pct'] = min(result['position_pct'] * 1.2, 70.0)
            result['reason'] += " | 牛市环境，仓位上浮20%"
        elif market_trend == 'down':
            result['position_pct'] = max(result['position_pct'] * 0.5, 10.0)
            result['reason'] += " | 熊市环境，仓位减半"

        result['position_value'] = round(total_capital * result['position_pct'] / 100, 2)
        return result


# ============ 便捷函数 ============

def calc_kelly_position(total_capital: float, tier: str = 'B',
                        market_trend: str = 'neutral') -> Dict:
    """一行计算凯利仓位"""
    manager = KellyPositionManager()
    if market_trend != 'neutral':
        return manager.get_market_kelly(total_capital, market_trend)
    return manager.get_position_size(total_capital, tier)


def calc_kelly_for_backtest(win_rate: float, win_loss_ratio: float,
                            half_kelly: bool = True) -> float:
    """
    回测专用：给定胜率和盈亏比，计算凯利仓位

    Args:
        win_rate: 胜率 0~1
        win_loss_ratio: 盈亏比
        half_kelly: 是否半凯利

    Returns:
        建议仓位比例 0~1
    """
    q = 1 - win_rate
    kelly = (win_rate * win_loss_ratio - q) / win_loss_ratio
    kelly = max(0, kelly)

    if half_kelly:
        kelly = kelly * 0.5

    # 边界
    return max(0.10, min(0.25, kelly))


if __name__ == "__main__":
    print("=== 凯利公式仓位管理测试 ===")
    print()

    manager = KellyPositionManager()

    # 测试1：无历史数据（默认参数）
    print("测试1：无历史数据，默认参数")
    r1 = manager.get_position_size(100000, tier='A')
    print(f"  凯利比例: {r1['kelly_pct']}%")
    print(f"  半凯利: {r1['half_kelly_pct']}%")
    print(f"  实际仓位: {r1['position_pct']}% = ¥{r1['position_value']}")
    print(f"  胜率: {r1['win_rate']}%, 盈亏比: {r1['win_loss_ratio']}")
    print(f"  原因: {r1['reason']}")
    print()

    # 测试2：不同评级
    print("测试2：不同评级仓位对比")
    for tier in ['S', 'A', 'B', 'C']:
        r = manager.get_position_size(100000, tier=tier)
        print(f"  {tier}级: {r['position_pct']}% = ¥{r['position_value']}")
    print()

    # 测试3：市场环境
    print("测试3：市场环境影响")
    for trend in ['up', 'neutral', 'down']:
        r = manager.get_market_kelly(100000, market_trend=trend)
        print(f"  {trend}: 总仓位{r['position_pct']}% = ¥{r['position_value']}")
    print()

    # 测试4：回测参数计算
    print("测试4：回测参数计算")
    # 假设胜率40%，盈亏比2.0
    k = calc_kelly_for_backtest(0.40, 2.0, half_kelly=True)
    print(f"  胜率40%，盈亏比2.0 → 半凯利仓位: {k*100:.1f}%")
    # 假设胜率55%，盈亏比1.5
    k = calc_kelly_for_backtest(0.55, 1.5, half_kelly=True)
    print(f"  胜率55%，盈亏比1.5 → 半凯利仓位: {k*100:.1f}%")
    print()

    print("=== 测试完成 ===")
