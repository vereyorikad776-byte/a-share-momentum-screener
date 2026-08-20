# 📊 盘中实时扫描设置指南

## 说明

本系统使用 **iFinD 真实数据** 进行盘中扫描，**不是模拟数据**。

## 扫描时间表

| 时间 | 用途 | 数据源 |
|:---:|:---|:---:|
| 10:00 | 早盘确认 | iFinD 实时 |
| 11:00 | 上午收盘前 | iFinD 实时 |
| 13:30 | 下午开盘 | iFinD 实时 |
| **14:30** ⭐ | **过夜持股法关键窗口** | iFinD 实时 |

## 明日测试步骤

### Step 1: 明天 14:25 手动运行测试

```bash
cd ~/.openclaw/workspace/skills/ifind-momentum-screener/scripts
bash run_intraday.sh
```

### Step 2: 检查结果

```bash
cat data/intraday_1430.json
```

输出示例：
```json
{
  "time": "14:30",
  "signals": [
    {
      "code": "600519",
      "name": "贵州茅台",
      "tier": "S",
      "score": 8.5,
      "price": 1500.0,
      "change_pct": 3.2,
      "action": "买",
      "reasons": ["MACD>0", "突破新高"]
    }
  ]
}
```

### Step 3: 确认无误后，设置定时任务

```bash
crontab -e
```

添加以下行：
```
# A股盘中扫描（周一至周五）
0 10,11 * * 1-5 bash /root/.openclaw/workspace/skills/ifind-momentum-screener/scripts/run_intraday.sh >> /tmp/intraday_cron.log 2>&1
30 13,14 * * 1-5 bash /root/.openclaw/workspace/skills/ifind-momentum-screener/scripts/run_intraday.sh >> /tmp/intraday_cron.log 2>&1
```

## 微信推送（可选）

扫描完成后自动推送结果到微信，需额外配置。

### 配置步骤

1. 安装企业微信/飞书 Bot（免费）
2. 在 `run_intraday.sh` 中取消 `--notify` 注释
3. 填入 Bot Webhook URL

## 注意事项

- ⚠️ **使用 iFinD 真实额度**，每次扫描约消耗 100~200 次调用
- ⚠️ **扫描结果仅供参考**，买卖决策需人工确认
- ⚠️ **14:30 是过夜持股法关键窗口**，但尾盘买入有流动性风险
- ⚠️ **非交易日自动跳过**（cron 已设 1-5）

## 数据存储

扫描结果保存到：
```
data/intraday_HHMM.json
```

历史记录可对比查看：
```bash
ls -lt data/intraday_*.json | head -10
```
