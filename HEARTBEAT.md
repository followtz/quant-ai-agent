# HEARTBEAT.md — 系统巡检清单

每30分钟自动执行。正常状态不推送，异常立即告警。

## 巡检项目

### 1. 系统健康检查
- [ ] Futu OpenD 进程是否运行（`ps aux | grep Futu_OpenD`）
- [ ] OpenClaw gateway 状态正常
- [ ] GitHub 无未推送变更

### 2. 黄金状态变量检查（交易时段）
- [ ] `data/dashboard/golden_state.json` 是否存在
- [ ] 关键字段: Current_Position / Today_PNL / Strategy_Status
- [ ] 数据超过15分钟未更新 → 标记 stale
- [ ] 非交易时段不推送告警

### 3. 风控阈值检查（交易时段）
- [ ] 单日亏损 >5% → L3 全局熔断告警
- [ ] 单票回撤 >15% → 暂停该标的

### 4. 外脑 Token 占比检查（非交易时段≥70%）
- [ ] 统计外脑 API 调用 Token 消耗
- [ ] 低于目标值 → 记录 warning

## 推送规则
- 正常 → 不推送（无噪音）
- 橙色预警 → 企业微信卡片
- 红色预警 → 企业微信 + QQ邮箱双通道
