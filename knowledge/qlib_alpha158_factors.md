# Qlib Alpha158 因子精读
**来源**: microsoft/qlib Alpha158DL  
**提取时间**: 2026-05-04

---

## 因子分类（共158个）

### 1. K线基础（20个）
归一化的价格序列，对60天窗口做 Ref/Mean/Std/Slope/Rsquare
```
$close/Ref($close,1)        # 日收益率
$open/$close                # 开盘/收盘比
$high/$close                # 最高/收盘比
$low/$close                 # 最低/收盘比
($close-$close_20ma)/$close # 价格偏离度（自实现）
```

### 2. 波动因子（15个）
```
Std($close, N)/$close      # N日波动率
Max($high, N)/$close       # N日最高/收盘
Min($low, N)/$close        # N日最低/收盘
($close-Min($low,N))/(Max($high,N)-Min($low,N))  # 位置指标（%）
```

### 3. 趋势因子（12个）
```
Slope($close, N)/$close    # N日线性趋势斜率
Rsquare($close, N)         # N日线性拟合R²（趋势强度）
Mean($close>Ref($close,1), N)  # N日上涨比例
Mean($close<Ref($close,1), N)  # N日下跌比例
```

### 4. 量价关系因子（10个）
```
Corr($close, Log(volume+1), N)      # 价格-成交量相关性
Corr(return, volume_return, N)       # 收益率-成交量变化率相关
Mean($volume, N)/($volume+1e-12)    # 相对成交量
```

### 5. 高阶因子（逆市/排序等）
```
Rank($close, N)            # N日价格排序位置
IdxMax($high, N)/N         # 最高价出现位置（%）
IdxMin($low, N)/N          # 最低价出现位置（%）
Resi($close, N)/$close     # 线性回归残差（逆市信号）
Quantile($close, N, 0.8)   # 80%分位
Quantile($close, N, 0.2)   # 20%分位
```

---

## → 适合我们（小盘/高波动）的精选因子

| 类别 | 因子 | 适合我们的原因 |
|------|------|--------------|
| **波动** | Std($close, 5)/$close | 小盘高波动，捕捉爆发前夜 |
| **趋势** | Slope($close, 5)/$close | 短期趋势识别，适合规则化交易 |
| **动量** | Mean($close>Ref, 5) | 连续上涨天数，小盘股趋势强劲 |
| **反转** | Resi($close, 20)/$close | 逆市信号，高波动标的易出现超卖 |
| **位置** | ($close-Min($low,20))/(Max($high,20)-Min($low,20)) | 判断是否在价格区间底部（超卖区） |
| **量价** | Corr($close, Log(volume), 5) | 量价背离识别，小盘股信号强 |
| **波动** | ($close-CloseMA5)/$close | 价格偏离度，高波动标的大偏离预示回归 |

### 如何用？
```python
# 这些因子可通过 Futu OpenD 的历史K线数据直接计算
# 不需要Qlib的完整数据流水线
# 例: 5日波动率因子
import numpy as np
closes = [...]  # 从OpenD获取
vol_5d = np.std(closes[-5:]) / closes[-1]
```
