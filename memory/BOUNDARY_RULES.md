# 🛡️ 智能体边界规则手册

> 版本：1.0 | 生效日期：2026-04-21 | 维护组：总控官

---

## 规则体系概览

| 规则ID | 规则名称 | 优先级 | 状态 |
|-------|---------|-------|------|
| B-001 | 策略健康度自动检查 | P1 | 🆕 新增 |
| B-002 | Token战略储备机制 | P1 | 🆕 新增 |
| B-003 | 数据覆盖度门槛 | P1 | 🆕 新增 |
| B-004 | 记忆文件分卷机制 | P2 | 🆕 新增 |
| B-005 | 指标缓存机制 | P2 | 🆕 新增 |

---

## 规则B-001：策略健康度自动检查

### 触发条件
- 实盘运行时间 ≥ 2周
- 检查频率：每周一 09:00（港股开盘前）

### 检查指标与阈值

| 指标 | 黄色预警阈值 | 红色预警阈值 | 策略失效阈值 |
|-----|------------|------------|------------|
| 近2周胜率 | < 50% | < 45% | - |
| 近2周最大回撤 | - | > 15% | - |
| 近1月收益 vs Buy&Hold | - | - | < Buy&Hold |
| 组合条件 | - | 胜率<45% AND 回撤>15% | - |

### 触发动作

**黄色预警**：
- 生成策略健康度报告
- 发送至总控官审阅
- 建议关注，加强监控

**红色预警**：
- 自动触发历史回测重评
- 对比当前参数 vs 历史最优参数
- 生成回测对比报告
- 建议是否启动参数优化

**策略失效预警**：
- 立即上报总控官
- 建议暂停实盘交易
- 启动策略失效分析
- 评估回滚至上一版本

### 实现代码框架

```python
class StrategyHealthChecker:
    def __init__(self, strategy_id):
        self.strategy_id = strategy_id
        
    def check_health(self):
        """执行健康度检查"""
        metrics = {
            'win_rate_2w': self.calc_win_rate(days=14),
            'max_dd_2w': self.calc_max_drawdown(days=14),
            'return_1m': self.calc_return(days=30),
            'buy_hold_return_1m': self.get_buy_hold_return(days=30)
        }
        
        alert_level = self.determine_alert_level(metrics)
        
        if alert_level == 'yellow':
            self.send_yellow_alert(metrics)
        elif alert_level == 'red':
            self.trigger_backtest_review()
            self.send_red_alert(metrics)
        elif alert_level == 'failed':
            self.send_failure_alert(metrics)
            self.recommend_pause()
            
        return alert_level, metrics
```

---

## 规则B-002：Token战略储备机制

### 储备额度
- **储备量**：500万 Token
- **占比**：日预算 4000万 的 12.5%
- **补充周期**：每日 00:00 自动重置

### 储备用途（优先级排序）

| 优先级 | 用途 | 使用条件 | 审批要求 |
|-------|------|---------|---------|
| P0 | 紧急风控分析 | 触发熔断或重大风险事件 | 总控官直接调用 |
| P1 | 突发市场事件处理 | 黑天鹅事件、极端行情 | 总控官直接调用 |
| P2 | 策略紧急回滚 | 策略失效或严重Bug | 总控官直接调用 |
| P3 | 关键数据恢复 | 数据丢失或损坏 | 总控官审批 |

### 使用流程

```
触发紧急需求
    ↓
判断储备可用性
    ↓
是 → 直接调用储备额度
    ↓
执行紧急任务
    ↓
记录使用情况
    ↓
通知相关人员
```

### 储备耗尽处理

当储备额度耗尽时：
1. 暂停所有非核心任务（AI学习、非紧急回测）
2. 保留核心任务（风控监控、实盘交易执行）
3. 等待次日 00:00 自动重置
4. 生成储备耗尽报告，分析原因

### 监控指标

- 储备使用率（日/周/月统计）
- 储备耗尽次数
- 储备使用效率（任务完成度/消耗Token）

---

## 规则B-003：数据覆盖度门槛

### 新标的入池最低要求

| 数据类型 | 最低要求 | 理想标准 | 检查方式 |
|---------|---------|---------|---------|
| 历史数据时长 | ≥ 6个月（126交易日） | ≥ 1年（252交易日） | 自动统计 |
| 完整K线数据 | ≥ 95% | ≥ 99% | 缺失值检测 |
| 财报数据 | 最近4季度 | 最近8季度 | 财报日期检查 |
| 成交量数据 | 完整无缺失 | 完整无缺失 | 空值检查 |

### 影子模式验证要求

| 验证项 | 最低要求 | 通过标准 |
|-------|---------|---------|
| 验证期长度 | ≥ 2周（10交易日） | ≥ 4周（20交易日） |
| 信号准确率 | ≥ 55% | ≥ 60% |
| 最大回撤 | < 8% | < 5% |
| 收益 vs Buy&Hold | 跑赢或持平 | 显著跑赢 |

### 实盘准入检查清单

```python
NEW_STOCK_ADMISSION_CHECKLIST = {
    'data_coverage': {
        'history_length': '>= 126 days',
        'completeness': '>= 95%',
        'financial_reports': '>= 4 quarters'
    },
    'shadow_mode': {
        'duration': '>= 10 trading days',
        'win_rate': '>= 55%',
        'max_drawdown': '< 8%',
        'vs_buy_hold': 'outperform or match'
    },
    'liquidity': {
        'avg_daily_volume': '>= 2M shares',
        'avg_daily_value': '>= $5M'
    },
    'risk': {
        'correlation_to_btc': '>= 0.3',
        'volatility': '30% - 80% annualized'
    }
}
```

### 数据质量评分

| 评分维度 | 权重 | 评分标准 |
|---------|------|---------|
| 历史完整性 | 30% | 按缺失率扣分 |
| 数据及时性 | 25% | 延迟天数扣分 |
| 数据准确性 | 25% | 异常值检测 |
| 覆盖全面性 | 20% | K线/财报/基本面 |

**总分 ≥ 80分**：允许入池  
**60-79分**：补充数据后重评  
**< 60分**：拒绝入池

---

## 规则B-004：记忆文件分卷机制

### 触发条件

- MEMORY.md 文件行数 > 5000行
- 或文件大小 > 500KB
- 或季度末自动触发（3/6/9/12月）

### 分卷规则

```
原文件: MEMORY.md (5200行)
    ↓ 触发分卷
新文件: MEMORY.md (保留最近3个月，约1500行)
归档文件: MEMORY_2026-Q1.md (3700行历史内容)
```

### 归档内容选择

**保留在MEMORY.md（当前文件）**：
- 最近3个月的核心决策
- 正在进行的项目状态
- 当前有效的策略版本
- 未解决的已知问题
- 活跃的技术债务

**归档至历史文件**：
- 已完成的策略版本
- 已解决的历史问题
- 过时的技术决策
- 已完成的项目总结
- 季度以上的历史记录

### 分卷执行流程

```python
def archive_memory():
    """执行记忆文件分卷"""
    # 1. 读取当前MEMORY.md
    current_content = read_file('MEMORY.md')
    
    # 2. 解析内容，按时间戳分割
    entries = parse_entries(current_content)
    
    # 3. 分离近期内容和历史内容
    recent_entries = [e for e in entries if e.date > three_months_ago]
    historical_entries = [e for e in entries if e.date <= three_months_ago]
    
    # 4. 生成归档文件名
    quarter = get_current_quarter()
    archive_filename = f'MEMORY_{quarter}.md'
    
    # 5. 写入归档文件
    write_file(archive_filename, format_entries(historical_entries))
    
    # 6. 更新当前文件
    new_content = generate_header() + format_entries(recent_entries)
    write_file('MEMORY.md', new_content)
    
    # 7. 更新归档索引
    update_archive_index(archive_filename)
```

### 归档索引格式

```markdown
# MEMORY.md 归档索引

## 当前文件
- 时间范围: 2026-02-21 至 2026-04-21
- 内容: 最近3个月核心记忆

## 历史归档
| 文件名 | 时间范围 | 行数 | 关键内容 |
|-------|---------|------|---------|
| MEMORY_2026-Q1.md | 2026-01-01 至 2026-03-31 | 3700 | 架构优化v2.0/v2.1 |
| MEMORY_2025-Q4.md | 2025-10-01 至 2025-12-31 | 4200 | 系统初始化 |
```

---

## 规则B-005：指标缓存机制

### 缓存对象

| 指标类型 | 具体指标 | 计算复杂度 | 更新频率 |
|---------|---------|-----------|---------|
| 移动平均线 | MA5, MA10, MA20, MA60 | 中 | 5分钟 |
| 波动率指标 | 20日历史波动率 | 高 | 5分钟 |
| 成交量指标 | 20日均量 | 低 | 5分钟 |
| 技术指标 | RSI, MACD, KDJ | 中 | 5分钟 |
| 统计指标 | Z-Score, 百分位 | 中 | 5分钟 |

### 缓存结构

```python
CACHE_STRUCTURE = {
    'metadata': {
        'symbol': 'US.BTDR',
        'last_update': '2026-04-21T09:30:00+08:00',
        'data_version': 'v1'
    },
    'indicators': {
        'MA': {
            'MA5': {'value': 12.34, 'timestamp': '2026-04-21T09:30:00'},
            'MA10': {'value': 12.56, 'timestamp': '2026-04-21T09:30:00'},
            'MA20': {'value': 12.78, 'timestamp': '2026-04-21T09:30:00'},
        },
        'volatility': {
            'hist_vol_20d': {'value': 0.45, 'timestamp': '2026-04-21T09:30:00'}
        },
        'volume': {
            'avg_vol_20d': {'value': 2500000, 'timestamp': '2026-04-21T09:30:00'}
        }
    }
}
```

### 更新策略

**定时更新**：
- 交易时段：每5分钟
- 非交易时段：每小时

**事件触发更新**：
- 价格变动 > 2%
- 新K线生成
- 策略信号触发
- 手动刷新请求

### 失效策略

| 失效条件 | 处理方式 | 优先级 |
|---------|---------|-------|
| 超过更新周期 | 标记为stale，下次访问时更新 | P2 |
| 价格大幅变动 | 立即失效，强制更新 | P0 |
| 数据源切换 | 全部失效，重新计算 | P1 |
| 手动刷新 | 指定指标失效，立即更新 | P1 |

### 缓存持久化

```python
class IndicatorCache:
    CACHE_FILE = 'data/cache/indicators.json'
    
    def __init__(self):
        self.cache = self.load_cache()
        
    def load_cache(self):
        """从文件加载缓存"""
        if os.path.exists(self.CACHE_FILE):
            with open(self.CACHE_FILE, 'r') as f:
                return json.load(f)
        return {}
        
    def save_cache(self):
        """保存缓存到文件"""
        with open(self.CACHE_FILE, 'w') as f:
            json.dump(self.cache, f, indent=2)
            
    def get_indicator(self, symbol, indicator_name):
        """获取指标值，自动处理缓存失效"""
        cache_key = f"{symbol}:{indicator_name}"
        cached = self.cache.get(cache_key)
        
        if cached and not self.is_expired(cached):
            return cached['value']
            
        # 缓存失效，重新计算
        value = self.calculate_indicator(symbol, indicator_name)
        self.cache[cache_key] = {
            'value': value,
            'timestamp': datetime.now().isoformat()
        }
        self.save_cache()
        return value
```

### 性能优化预期

| 优化项 | 优化前 | 优化后 | 提升 |
|-------|-------|-------|------|
| 指标计算时间 | 500ms | 50ms | 10x |
| API调用次数 | 每次信号都调用 | 每5分钟一次 | 60x |
| 回测速度 | 10分钟 | 2分钟 | 5x |

---

## 规则执行监控

### 监控指标

| 指标 | 目标值 | 告警阈值 |
|-----|-------|---------|
| B-001检查覆盖率 | 100% | < 90% |
| B-002储备可用率 | > 80% | < 50% |
| B-003数据质量分 | > 80 | < 60 |
| B-004分卷及时性 | 季度完成 | 超期1周 |
| B-005缓存命中率 | > 70% | < 50% |

### 执行报告

每周一生成《边界规则执行报告》：
- 各规则执行统计
- 违规事件记录
- 优化建议
- 规则更新需求

---

## 附录：规则修订历史

| 版本 | 日期 | 修订内容 | 修订人 |
|-----|------|---------|-------|
| 1.0 | 2026-04-21 | 初始版本，包含B-001至B-005 | 龙虾总控智能体 |

---

*本手册由总控官维护，所有智能体必须严格遵守。*
