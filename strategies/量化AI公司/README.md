# Quant-Trade-Lab
这是用于存储测试、模拟及实盘的交易策略

---

## 📁 仓库结构

```
Quant-Trade-Lab/
├── README.md
├── .gitignore
│
├── strategies/                    # 🎯 策略库（实盘 + 备用）
│   ├── US-BTDR/                  # 🇺🇸 美股 - BTDR PrevClose V2 实盘
│   │   ├── live_engine/           #   实盘引擎
│   │   ├── backtest_data/         #   回测数据
│   │   ├── backtest_scripts/      #   回测脚本
│   │   ├── docs/                  #   策略文档
│   │   ├── logs/                  #   运行时日志
│   │   └── strategies/             #   策略参数
│   │
│   ├── HK-02598-Lianlian/         # 🇭🇰 港股 - 连连数字 V4 双重确认实盘
│   │   ├── v4_live_engine.py      #   V4实盘引擎
│   │   ├── v4_live_config.json    #   策略配置
│   │   ├── v4_monitor.py         #   监控面板
│   │   ├── README.md              #   使用说明
│   │   └── MEAN_REVERSION_*.md    #   均值回归分析
│   │
│   └──备用策略_待验证/            # 🔒 仅回测，禁止实盘
│
├── backtests/                    # 📊 回测数据与报告
│   ├── 历史回测结果/
│   ├── 每日新回测/
│   └── 备用策略回测记录/
│
├── live_trading/                 # 📈 实盘交易记录
│   ├── BTDR_实盘执行/
│   └── Lianlian_实盘执行/
│
├── monitoring/                   # 🖥️ 监控面板与状态
│   ├── BTDR监控端口8080/
│   └── Lianlian监控端口8081/
│
├── research/                     # 🔬 社区研究与因子库
│   ├── 聚宽高赞策略/
│   └── 因子借鉴记录/
│
├── market_pool/                  # 🌏 市场备选股票池
│   ├── A股备选池/
│   ├── 港股备选池/
│   └── 美股备选池/
│
├── agents_logs/                  # 📝 龙虾智能体运行日志
│
└── docs/                         # 📚 文档与报告
    ├── 实盘状态监测报告/
    └── 盘前盘后报告/
```

---

## ⚠️ 核心规则

### 实盘策略（可直接使用）
| 策略 | 市场 | 标的 | 状态 |
|------|------|------|------|
| BTDR PrevClose V2 | 美股 | US.BTDR | ✅ 实盘运行中 |
| 连连数字 V4 双重确认 | 港股 | HK.02598 | ✅ 实盘运行中 |

### 备用策略
- `strategies/备用策略_待验证/` 目录下的所有策略 **仅供回测验证**
- **禁止**接入富途 OpenAPI 进行实盘交易
- 需经回测验证通过后，方可申请升级为实盘策略

---

## 🔧 技术栈

- **行情/交易 API**: 富途 OpenAPI (Futu OpenD)
- **语言**: Python 3.8+
- **策略框架**: Pandas / NumPy / Scikit-learn
- **版本控制**: Git
- **数据存储**: 本地文件系统 + GitHub

---

## 📌 免责声明

本仓库仅供技术研究、学习交流使用。实盘交易存在风险，请自行评估，**作者不对任何实盘亏损负责**。
