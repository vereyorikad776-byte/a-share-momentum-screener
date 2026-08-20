# A股动量选股系统 v2.2 整合版

## 文件结构 (29个Python模块)

```
skills/ifind-momentum-screener/
├── SKILL.md                          # 本文件
├── config/
│   ├── default.json                  # 默认配置
│   └── pool_config.json              # 池子配置
├── scripts/                          # 核心代码 (29个模块)
│   │
│   ├── 【评分引擎】
│   │   ├── v22_engine.py            ⭐ 核心评分引擎 v2.2r++ (融入首启战法指标)
│   │   ├── v21_engine.py             v2.1兼容层 (映射到v22)
│   │   ├── fscore_module.py          F-Score质量因子 (5分制)
│   │   └── zscore_module.py          Z-Score财务健康度 (A股适用版)
│   │
│   ├── 【多Agent系统】
│   │   ├── multi_agent_debate.py    七维辩论 (技术/资金/基本面/消息/产业/宏观/行为)
│   │   ├── market_regime.py          五维择时 + 三维风险
│   │   ├── kelly_position.py         凯利公式动态仓位
│   │   ├── trade_manager.py          交易执行 + T+1冻结 ⭐ v2.2r新增
│   │   └── market_data_feed.py      五维择时数据自动获取 ⭐ v2.2r++新增
│   │
│   ├── 【池子管理】
│   │   ├── pool_manager.py           六池管理 + 扩散指标 + RRG
│   │   ├── data_cache.py             DuckDB本地缓存
│   │   └── data_source_manager.py    数据源管理
│   │
│   ├── 【数据获取】
│   │   ├── ifind_data.py             iFinD数据接口
│   │   ├── ifind_call.py             MCP调用封装
│   │   ├── ifind_screener.py         iFinD筛选器
│   │   ├── news_analyzer.py          新闻分析
│   │   └── news_sentiment.py         舆情分析
│   │
│   ├── 【扫描器】
│   │   ├── complete_scanner.py       完整流程: 五池→粗筛→精筛→评分
│   │   ├── run_v22_today.py          盘后批量评分 (Top20)
│   │   ├── run_v22_ultimate.py      一站式入口 (8种模式) ⭐ v2.2r++
│   │   ├── batch_v22_score.py        批量评分
│   │   ├── intraday_scanner.py       盘中实时扫描 (14:30窗口)
│   │   ├── daily_screener.py         每日全市场扫描
│   │   ├── full_screener.py          iFinD+Baostock混合扫描
│   │   ├── quick_screener.py         快速扫描8只大盘蓝筹
│   │   ├── full_top20_scanner.py     Top20完整版
│   │   └── run_final_scoring.py      最终评分
│   │
│   ├── 【反馈学习】⭐ v2.2r新增
│   │   └── feedback_learning.py      预测日志/命中率追踪/模式效能/用户否决/自动清理
│   │
│   ├── 【回测与模拟】⭐ v2.2r++新增
│   │   ├── backtest_adapter.py       Backtrader回测适配器 (v22评分接入标准框架)
│   │   └── paper_trading.py          模拟盘引擎 (虚拟资金+真实费率万3+持仓管理)
│   │
│   └── 【工具】
│       ├── config.py                 配置系统
│       ├── daily_top.py              每日Top榜
│       └── batch_fetch_klines.py     批量获取K线
│
├── data/
│   ├── pools/                        # 六大池子 (JSON)
│   ├── daily/                        # 每日计划
│   ├── duckdb_storage/               # K线缓存 (SH/SZ)
│   ├── feedback/                     # 反馈数据 ⭐ v2.2新增
│   │   ├── prediction_log.jsonl      # 预测日志
│   │   ├── pattern_stats.json        # 模式效能统计
│   │   └── user_overrides.json       # 用户否决记录
│   └── top20_*.json                  # 评分结果
│
└── references/
    └── scoring-formula.md            # 评分公式参考
```

---

## 核心执行流程

```
用户请求选股
    ↓
[Step 0] 五维择时 (market_regime.py + market_data_feed.py)
    ├─ 自动获取: PE/ERP/融资余额/市场广度/PCR/IV/CPI/PMI
    └─ 输出: 当前仓位上限 (0%~70%) / 市场环境判断
    ↓
[Step 1] 六池读取 (pool_manager.py)
    ├─ bottom (底部放量)     优先级1  手动更新
    ├─ limit_up (涨停池)     优先级2  自动抓取
    ├─ main_line (主线热点)  优先级3  自动抓取
    ├─ strong (强势票)       优先级4  自动/手动
    ├─ watchlist (自选)      优先级5  手动
    └─ hot (人气票)          优先级6  自动抓取
    ↓
[Step 2] 5日板块扫描 + 热点合并 ⭐ v2.2恢复 (v22_engine.py)
    ├─ scan_5day_sectors(): 0.4×涨幅 + 0.3×涨停密度 + 0.3×资金流
    └─ merge_hot_sectors(): 5日+当日取并集，双边1.15倍加成
    ↓
[Step 3] 技术面评分 (v22_engine.py) ⭐ v2.2r+融入首启战法
    ├─ MACD/RSI/KDJ/均线/量价/振幅/阳线实体
    ├─ 20日新高 (≥high_20d +3分)
    ├─ 距高点距离 (<3% +1分, <5% +0.5分) ← 首启战法指标
    ├─ 量比/连涨/回调/冲高回落检测
    └─ 输出: 0~25分 + 详细理由
    ↓
[Step 4] 情绪面评分 (v22_engine.py) ⭐ v2.2r+融入首启战法
    ├─ 涨幅分级 (2~5% +4分, 5~7% +3分...)
    ├─ 热点板块 (+3分) / 板块涨幅
    ├─ 板块内强度排名 (跑赢板块20% +2分) ← 首启战法指标
    ├─ 多概念叠加 / 连涨惯性
    └─ 输出: 0~15分 + 详细理由
    ↓
[Step 5] 资金面评分 (v22_engine.py)
    ├─ 机构持仓 / 北向资金 / 主力净流入 / 融资余额
    ├─ 散户情绪反向 (融资高减分)
    └─ 输出: 0~15分
    ↓
[Step 6] 基本面评分 (fscore_module.py + zscore_module.py)
    ├─ F-Score (5分制): ROE/毛利率/净利率/负债率/流动比率
    ├─ Z-Score (A股适用版): Z'≥1.5安全, <0排除
    ├─ 估值水平 (PE/PB/PS)
    └─ 输出: 0~10分 (财务缺失不扣分不exclude)
    ↓
[Step 7] 消息面评分 (news_analyzer.py)
    ├─ 新闻舆情分析
    ├─ 重大利空硬排除 (副总留置/补缴税款/监管问询等)
    └─ 输出: 0~10分 / 或直接exclude
    ↓
[Step 8] 多Agent辩论 (multi_agent_debate.py)
    ├─ 技术Agent 25% / 资金Agent 20% / 基本面Agent 20%
    ├─ 消息情绪Agent 15% / 产业逻辑Agent 10%
    ├─ 宏观Agent 5% / 行为Agent 5%
    └─ 输出: 加权综合分 + 各Agent理由
    ↓
[Step 9] 综合评分与分级 (v22_engine.py)
    ├─ Tier S: 综合≥8.0 + 模式命中 + 热点前3
    ├─ Tier A: 综合6.5~8.0
    ├─ Tier B: 综合4.5~6.5
    ├─ Tier X: <4.5 或 触发硬排除规则
    └─ 明确操作建议: 买/等/不买 + 理由汇总
    ↓
[Step 10] 凯利仓位 (kelly_position.py)
    ├─ 半凯利公式 × 趋势调整 × 等级倍率
    └─ 约束: 单票≤20% / 总仓位≤70% / 最低现金≥30%
    ↓
[Step 11] 交易计划生成 (trade_manager.py) ⭐ v2.2r
    ├─ 持仓检查 (止损/止盈/时间止损)
    ├─ 买入计划 (S级20%仓位/A级15%仓位)
    ├─ 同花顺条件单参数
    └─ 每日复盘
    ↓
[Step 12] 模拟盘执行 (paper_trading.py) ⭐ v2.2r++
    ├─ 虚拟资金账户管理
    ├─ 真实费率模拟 (佣金万3/最低5元/印花税千1)
    ├─ 持仓盈亏实时跟踪
    └─ 交易记录持久化
    ↓
[Step 13] 反馈迭代学习 (feedback_learning.py) ⭐ v2.2r
    ├─ 记录预测日志
    ├─ 次日回填实际结果
    ├─ 计算命中率 (近20日)
    ├─ 模式效能统计
    ├─ 用户否决学习
    └─ 自动清理 (保留最近5个交易日)
    ↓
[可选] Backtrader回测 (backtest_adapter.py) ⭐ v2.2r++
    ├─ v22评分接入标准回测框架
    ├─ 完整回测报告 (资金曲线/夏普比率/最大回撤)
    └─ 多策略对比
    ↓
[输出] 完整报告
    ├─ 评分详情 (6维度独立评分)
    ├─ 交易计划 (买/持有/观望)
    ├─ 风控设置 (止损/止盈/时间止损)
    ├─ 模拟盘持仓 (如启用)
    └─ 学习报告 (命中率/模式效能)
```

---

## v2.2 vs v2.0 vs v2.1 对比

| 功能 | v2.0 (文档) | v2.1 (旧代码) | v2.2 (当前整合版) | v2.2r (硬改造) | v2.2r++ (精华融入) |
|:---|:---:|:---:|:---:|:---:|:---:|
| **一夜持股法** | ✅ 20分制 | ❌ 无 | ✅ 20分制 (恢复) | ✅ | ✅ |
| **三维融合** | ✅ 15分制 | ❌ 简化 | ✅ 15分制 (恢复) | ✅ | ✅ |
| **五大模式** | ✅ 突破/回调/旗形/杯柄/筹码 | ✅ 有 | ✅ 完整保留 | ✅ | ✅ |
| **5日板块扫描** | ✅ 复合评分 | ❌ 无 | ✅ 恢复 | ✅ | ✅ |
| **热点合并** | ✅ 双边1.15倍 | ❌ 无 | ✅ 恢复 | ✅ | ✅ |
| **七维辩论** | ✅ 7维 | ❌ 6维 | ✅ 7维 (恢复产业+宏观+行为) | ✅ | ✅ |
| **过夜胜率预测** | ❌ 无 | ❌ 无 | ✅ v2.2新增 | ✅ | ✅ |
| **策略类型判定** | ❌ 无 | ❌ 无 | ✅ v2.2新增 | ✅ | ✅ |
| **反馈迭代学习** | ✅ 有 | ❌ 无 | ✅ v2.2新增 | ✅ | ✅ |
| **数据留存规则** | ✅ 5日清理 | ❌ 无 | ✅ v2.2新增 | ✅ | ✅ |
| **执行纪律** | ✅ 硬规则 | ❌ 软规则 | ✅ v2.2新增 | ✅ | ✅ |
| **五维择时** | ❌ 无 | ✅ 有 | ✅ 保留 | ✅ | ✅ 自动数据获取 |
| **凯利公式** | ❌ 无 | ✅ 有 | ✅ 保留 | ✅ | ✅ |
| **F/Z-Score** | ❌ 无 | ✅ 有 | ✅ 保留 | ✅ | ✅ |
| **BetaGap因子** | ❌ 无 | ✅ 有 | ✅ 保留 | ✅ | ✅ |
| **散户反向指标** | ❌ 无 | ✅ 有 | ✅ 保留 | ✅ | ✅ |
| **阶梯止盈** | ❌ 无 | ✅ 有 | ✅ 保留 | ✅ | ✅ |
| **六池管理** | ❌ 5池 | ✅ 6池 | ✅ 保留 | ✅ | ✅ |
| **消息面硬排除** | ❌ 无 | ❌ 无 | ❌ 无 | ✅ v2.2r新增 | ✅ |
| **冲高回落检测** | ❌ 无 | ❌ 无 | ❌ 无 | ✅ v2.2r新增 | ✅ |
| **明确操作建议** | ❌ 无 | ❌ 无 | ❌ 无 | ✅ v2.2r新增 | ✅ |
| **距高点距离** | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 首启战法 |
| **板块内强度排名** | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 首启战法 |
| **五维数据自动获取** | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 东方系统 |
| **Backtrader回测** | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 东方系统 |
| **模拟盘引擎** | ❌ 无 | ❌ 无 | ❌ 无 | ❌ 无 | ✅ 东方系统 |
| **交易计划生成** | ❌ 无 | ❌ 无 | ❌ 无 | ✅ v2.2r新增 | ✅ |
| **用户否决学习** | ❌ 无 | ❌ 无 | ❌ 无 | ✅ v2.2r新增 | ✅ |

---

## 执行纪律 (硬规则)

```python
# 规则1: 遇到任何异常立即中止
#   - 绝不自行修补、猜测或跳过
#   - 向用户报告，提供可选方案: 重试/放宽条件/中止

# 规则2: API/数据失败按优先级尝试
#   - akshare → iFinD → gildata
#   - 全部失败抛出FetchError并终止
#   - 不返回空数据继续执行

# 规则3: 严禁临时修改参数
#   - 禁止为绕过问题修改评分阈值、权重、排除规则
#   - 所有参数调整必须通过反馈学习模块或用户明确指令
```

---

## v2.2r++ 新增模块使用指南

### 1. 五维择时自动数据获取 (market_data_feed.py)

```python
from market_data_feed import run_five_dimension_timing

position, reasons = run_five_dimension_timing()
# position: 建议仓位 0.0~1.0
# reasons: 判断依据列表
```

或命令行:
```bash
python3 run_v22_ultimate.py --mode market
```

**获取的数据:**
- 估值: 沪深300 PE → ERP股权风险溢价
- 资金: 融资余额变化率 + 布林带突破
- 技术: 市场广度 (上涨家数占比)
- 情绪: PCR/IV/期货持仓/基差 (需专业数据源)
- 基本面: CPI同比 / PMI

---

### 2. 模拟盘引擎 (paper_trading.py)

```python
from paper_trading import PaperAccount, PaperHolding, PaperTrader

account = PaperAccount(initial_cash=100000)
holdings = PaperHolding()
trader = PaperTrader(account, holdings)

# 买入
result = trader.buy('600519', '贵州茅台', 1500.0, 100, '波段', 'S级信号')

# 卖出
result = trader.sell('600519', 1600.0, reason='止盈')

# 查看账户
from paper_trading import get_paper_trading_summary
print(get_paper_trading_summary())
```

**费率模拟:**
- 佣金: 万3 (最低5元)
- 印花税: 千1 (卖出时)
- 过户费: 十万分之二

命令行:
```bash
python3 run_v22_ultimate.py --mode paper
```

---

### 3. Backtrader回测 (backtest_adapter.py)

```python
from backtest_adapter import run_backtest
import pandas as pd

# 准备数据 {code: DataFrame}
data_dict = {
    '600519': df,  # DataFrame含open/high/low/close/volume
}

result = run_backtest(data_dict, '20240101', '20241231', 1000000)
# result: {total_return, sharpe_ratio, max_drawdown, trade_count, trade_log}
```

**依赖:** `pip install backtrader` (未安装时不影响其他功能)

**注意:** 如果未安装backtrader，backtest_adapter.py会导入失败，但不影响评分/扫描/模拟盘等其他功能。

---

### 4. 一站式入口 (run_v22_ultimate.py)

```bash
# 8种运行模式
python3 run_v22_ultimate.py --mode single   --code 600519 --name 贵州茅台  # 单票评分
python3 run_v22_ultimate.py --mode scan                                     # 全量扫描
python3 run_v22_ultimate.py --mode check                                    # 持仓检查
python3 run_v22_ultimate.py --mode plan    --cash 100000 --capital 500000   # 交易计划
python3 run_v22_ultimate.py --mode report                                   # 学习报告
python3 run_v22_ultimate.py --mode backtest --days 20                       # 回测
python3 run_v22_ultimate.py --mode market                                   # 五维择时
python3 run_v22_ultimate.py --mode paper                                    # 模拟盘
```

---

## 核心评分示例输出 (v2.2r++)

```
1. 603239 浙江仙通 【3池覆盖】
   来源池子: main_line/limit_up/strong
   核心逻辑: 突破20日新高+放量 | MA20趋势向上 | 多池共振
   评级: S | 综合得分: 1.234
   模式分: 1.50 | 过夜分: 16.2/20 | 融合分: 11.5/15 | 辩论分: +3.24
   过夜胜率: 72.3% [高] | 预期收益: +2.5% | 置信度: 85%
   策略类型: ⭐ 适合过夜 (概率高+收益明确+置信高)
   收盘价: ¥18.50 | 涨跌幅: +3.90%
   理由: 收盘价>MA20; 放量1.88倍; MACD向上0.50; MA20趋势向上; 板块热点; 主板标的
```

---

## 版本信息

- **版本**: v2.2r++ (精华融入版)
- **验证日期**: 2026-08-20
- **模块数**: 50个Python脚本 + 14个JSON配置
- **总代码行**: ~10000+ 行
- **测试状态**: 全部核心功能通过
