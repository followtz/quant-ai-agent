# HEARTBEAT.md — 系统巡检

巡检由 `health_check.py` 每5分钟自动执行（纯代码，零LLM消耗）。
结果写入 `data/dashboard/health_status.json`。

## Heartbeat（每30分钟LLM）只做两件事

1. **读取 health_status.json** → 如果有 issues 则推送告警
2. **检查风控阈值** → 仅交易时段，仅读取 golden_state.json

## 规则
- `health_status.json` 中 `issues` 为空 → 回复 HEARTBEAT_OK
- `issues` 非空 → 推送 ❗红色告警
- 交易时段 + 单日亏损>5% → 推送 🚨L3熔断告警
- 其他情况 → 不推送，无噪音
