# V3 涡轮策略 - 快速参考

## 当前持仓状态

| 指标 | 数值 | 备注 |
|------|------|------|
| 实际持仓 | 8,894 股 | 目标 9,000 股 |
| 涡轮A | 已卖出 | 1,000股 @ $10.85 |
| 买回触发线 | ≤ $9.81 | 昨收 $10.33 × 0.95 |
| 涡轮B | 待命 | 触发线 ≤ $9.81 |

## 关键操作命令

```powershell
# 查看实时状态
Get-Content C:\Trading\data\v3_live_state.json | ConvertFrom-Json

# 查看最新日志
tail -n 50 C:\Trading\logs\v3_live_20260411.log

# 检查账户
python C:\Trading\scripts\check_real_account.py

# 手动启动引擎
python C:\Trading\scripts\v3_turbo_engine.py
```

## 重要文件路径

| 用途 | 路径 |
|------|------|
| 主引擎 | `C:\Trading\scripts\v3_turbo_engine.py` |
| 状态文件 | `C:\Trading\data\v3_live_state.json` |
| 日志目录 | `C:\Trading\logs\` |
| 启动脚本 | `C:\Trading\v3_daily_start.bat` |

## 交易规则速查

### 涡轮A（底仓做T）
- 卖出：价格 ≥ 昨收 × 1.05
- 买回：价格 ≤ 昨收 × 0.95
- 持仓下限：6,000 股

### 涡轮B（加仓做T）
- 买入：价格 ≤ 昨收 × 0.95
- 卖出：价格 ≥ 买入价 × 1.05
- 持仓上限：11,000 股

## 监控要点

1. **每天开盘前**：确认引擎已启动（检查任务计划）
2. **盘中**：关注涡轮A买回是否触发
3. **收盘后**：检查日志，确认无异常

## 紧急处理

| 场景 | 操作 |
|------|------|
| 引擎崩溃 | 手动重启：`python v3_turbo_engine.py` |
| 状态异常 | 重置状态文件，同步实际持仓 |
| 需要暂停 | 结束进程，修改状态文件为待命 |

---

*打印此页贴显示器旁备用*
