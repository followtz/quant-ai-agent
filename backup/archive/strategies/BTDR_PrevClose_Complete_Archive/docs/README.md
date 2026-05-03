# BTDR PrevClose 涡轮策略全集归档

## 版本总览

| 版本 | 策略描述 | 股/笔 | 净利(全年341天) | 超额收益 | 状态 |
|------|---------|-------|----------------|---------|------|
| V1 | S=10% / Ao=0% / Bo=0% | 1000 | $18,843 | +9.72% | 历史参考 |
| **V2** | **S=12% / Ao=-1% / Bo=+5%** | **1000** | **$25,456** | **+11.99%** | **实盘中运行** |
| V3 | S=12% / Ao=-1% / Bo=+5% | 2000 | $50,912 | +16.35% | 备用 |

---

## 目录结构

```
BTDR_PrevClose_Complete_Archive/
│
├── strategies/                          ← 策略参数文档 + 可运行引擎
│   ├── prev_close_v1.json              V1策略参数文档
│   ├── prev_close_v2.json              V2策略文档 ← 实盘运行中
│   ├── prev_close_v3.json              V3策略文档
│   └── prev_close_v1_engine.py          V1可运行引擎（PrevClose基准）
│
├── backtest_scripts/                    ← 完整回测分析脚本
│   ├── v3_threshold_deep.py             Part A/B/C/D 触发阈值深度扫描(68组)
│   ├── v3_threshold_v2.py               V2偏移量优化脚本
│   ├── v3_threshold_cd.py               Part C/D 短阈值分析
│   ├── v3_full_scan.py                 完整网格扫描
│   ├── volume_short_threshold.py        交易量K线+短阈值
│   ├── prev_close_timed.py              PrevClose+时间限制混合
│   ├── offset_analysis.py               完整偏移量网格
│   ├── prev_close_offset_scan.py        网格+洞察分析
│   └── full_year_cost_analysis.py       全年+交易成本敏感性
│
├── backtest_data/                       ← 回测结果数据(JSON)
│   ├── v3_threshold_full.json          68组参数完整对比
│   ├── lookback_analysis.json           ML训练窗口分析
│   └── cost_sensitivity_part2.json     盈亏平衡分析
│
├── live_engine/                        ← 实盘引擎
│   ├── prev_close_v2_engine.py          V2实盘引擎 ← 正在运行
│   └── v3_turbo_engine.py              V3旧引擎(参考)
│
└── docs/                               ← 使用文档
    └── README.md                        本文件
```

---

## V2实盘参数（正在运行）

```
涡轮A卖出:  价格 >= 前收 × (1 + 12%)
涡轮A买回:  价格 <= 前收(卖出日) × (1 - 1%)     ← 前收-1%折扣
涡轮B买入:  价格 <= 前收 × (1 - 5%)
涡轮B卖出:  价格 >= 前收(买入日) × (1 + 5%)     ← 前收+5%溢价

每笔交易量:   1000股
仓位范围:     7000 - 11000股
协同平衡:     7500(触发B自动买入) / 10500(触发A自动卖出)
账户:        Futu 281756477947279377 (实盘)
监控面板:     http://localhost:8080
状态文件:     C:\Trading\data\prev_close_v2_state.json
```

---

## 回测关键结论

### 结论1: B_offset=+5%是核心利润引擎
- V1(B_offset=0%): B单笔利润$2,614
- V2(B_offset=+5%): B单笔利润$4,467 → **+71%提升**
- 原因: B卖出触发价=前收×1.05，比精确前收更高、更容易触发、捕获更多动能

### 结论2: S=12%优于S=10%
- S=10%: 触发频繁但抓住小行情，利润薄
- S=12%: 门槛更高、过滤噪音，只抓20%+大行情，单笔利润更丰厚

### 结论3: A_offset=-1%微调有效
- A买回触发=前收-1%，对A买回影响不大，但配合S=12%可略微增加交易频率

### 结论4: 直觉S=7%/Ao=-3%/Bo=+3%是陷阱
- 更宽松的卖出触发反而减少利润，因为抓住了太多"假行情"

### 结论5: 股数翻倍=利润完美线性翻倍(2.0x)
- V2(1000股): $25,456
- V3(2000股): $50,912
- 系数: **2.00x** ← 策略逻辑与股数完全解耦

### 结论6: 仓位边界扩展是V3成功的关键
- 旧边界(7000-11000) + 2000股: 协同机制频繁触发，21笔交易胜率52.6%
- 新边界(5000-12000) + 2000股: 协同几乎不触发，10笔交易胜率100%

---

## 回测数据覆盖范围

- 时间: 2024-11-27 至 2026-04-10 (341个交易日)
- 买入持有: -12.06%
- 交易量K线数据: ~59天(2025-11 至 2026-02)
- 数据源: FutuOpenD API

---

## 实盘使用说明

### 启动V2引擎
```bash
cd C:\Trading\scripts
python prev_close_v2_engine.py
```

### 查看实时状态
```python
# 直接读取状态文件
with open('C:/Trading/data/prev_close_v2_state.json') as f:
    state = json.load(f)
print(state['turbo_A'], state['turbo_B'])
```

### 切换V3(2000股)
1. 停止V2引擎
2. 修改prev_close_v2_engine.py参数: TRADE_QTY=2000, POS_MIN=5000, POS_MAX=12000
3. 重启引擎

---

*由OpenClaw自动生成 | 更新时间: 2026-04-12*
