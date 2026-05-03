# 每日盘后自动回测触发机制 — 使用说明

> 版本：1.0 | 创建日期：2026-04-20

## 概述

`auto_backtest_trigger.py` 是去LLM化的纯Python脚本，每日盘后自动执行回测并与实盘交易对比，生成偏差分析报告。

## 功能

1. **定时触发回测**：港股16:30后触发连连V4回测，美股4:30(HKT)后触发BTDR回测
2. **实盘日志解析**：自动拉取当日实盘交易日志
3. **偏差对比分析**：对比实盘与回测的交易信号、价格、滑点
4. **预警标记**：偏差超阈值时生成预警
5. **报告归档**：Markdown报告自动保存至策略目录

## 使用方法

### 自动模式（定时任务）

```powershell
# 自动判断当前时间是否应触发回测
python auto_backtest_trigger.py
```

### 手动模式

```powershell
# 手动触发港股回测
python auto_backtest_trigger.py --market HK

# 手动触发美股回测
python auto_backtest_trigger.py --market US

# 手动触发全部回测
python auto_backtest_trigger.py --market ALL

# 强制执行（忽略时间检查）
python auto_backtest_trigger.py --market US --force
```

## 调度方式

### 方式1：Windows任务计划程序

```powershell
# 创建港股回测任务（每日16:35 HKT）
schtasks /create /tn "QuantBT_HK" /tr "python C:\Users\Administrator\Desktop\量化AI公司\03_实盘与监测\auto_backtest_trigger.py --market HK" /sc daily /st 16:35

# 创建美股回测任务（每日4:35 HKT）
schtasks /create /tn "QuantBT_US" /tr "python C:\Users\Administrator\Desktop\量化AI公司\03_实盘与监测\auto_backtest_trigger.py --market US" /sc daily /st 04:35
```

### 方式2：process_guardian.py 调度

在 `process_guardian.py` 的配置中添加：

```json
{
  "name": "auto_backtest_HK",
  "command": "python auto_backtest_trigger.py --market HK",
  "schedule": "16:35",
  "workdir": "C:\\Users\\Administrator\\Desktop\\量化AI公司\\03_实盘与监测"
},
{
  "name": "auto_backtest_US",
  "command": "python auto_backtest_trigger.py --market US",
  "schedule": "04:35",
  "workdir": "C:\\Users\\Administrator\\Desktop\\量化AI公司\\03_实盘与监测"
}
```

## 预警阈值

| 偏差项 | 默认阈值 | 说明 |
|--------|---------|------|
| 价格偏差 | > 2% | 实盘成交价 vs 回测信号价 |
| 信号遗漏率 | > 30% | 实盘遗漏的交易信号比例 |
| 滑点偏差 | > 0.5% | 实际滑点 vs 预期滑点 |

## 输出文件

| 文件 | 路径 |
|------|------|
| 回测报告 | `01_策略库/{策略}/实盘策略核心文件/backtest_reports/{策略}_daily_{日期}.md` |
| 运行日志 | `06_龙虾自动运行日志/auto_backtest/backtest_{日期}.log` |

## TODO（待对接）

- [ ] 对接实际回测脚本执行（当前为mock模式）
- [ ] 实盘交易日志格式适配（需确认日志格式后调整parse_trade_log）
- [ ] 企业微信预警通知接入
- [ ] 富途API实时数据拉取
- [ ] 回测结果JSON格式标准化
- [ ] 多日偏差趋势分析

## 设计原则

- **去LLM化**：纯Python执行，不消耗大模型Token
- **容错设计**：异常自动重试3次，失败写日志不崩溃
- **可扩展**：新策略只需在STRATEGIES配置中添加条目
