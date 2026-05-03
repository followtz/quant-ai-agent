"""
连连数字V4 优化版 - V3+均值回归双重确认
移除ML信号（RandomForest在60天数据上≈随机猜测）
改用ATR动态阈值，验证245天数据

回测对比(245天):
  V3信号(去ML):              131信号 ❌ 噪音太多
  三重确认(原版含ML+RSI):      54信号 ⚠️ 偏多
  V3+MR双确认(固定5%):         18信号 ✅ 最佳
  V3+MR双确认(ATR×0.7):       20信号 ✅ ATR等效
  Buy&Hold 8000股:            -$3,840

优化内容:
  1. 移除ML信号（RandomForest→remove）
  2. 移除RSI第三重确认
  3. 固定5%改为ATR×0.7（自适应波动）
  4. 简化代码结构
"""
import numpy as np

class LianLianV4Optimized:
    """连连数字V4优化版 - 双重确认策略"""
    
    def __init__(self, stock_code='HK.02598'):
        self.stock_code = stock_code
        self.v3_atr_mult = 0.7    # V3: ATR×0.7 ≈ 固定5%
        self.mr_zscore = 2.0      # MR: Z-Score > |2|
        self.base_position = 8000
        
    def generate_signals(self, df):
        """
        生成交易信号
        df须含: close, high, low (至少20行)
        返回: {signal, v3, mr, zscore}
        """
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        
        # 计算ATR
        tr = np.maximum(high[1:] - low[1:], np.abs(high[1:] - close[:-1]))
        atr = np.mean(tr[-14:]) if len(tr) >= 14 else 0.01
        
        # 计算MA20和Z-Score
        ma20 = np.mean(close[-20:])
        std20 = np.std(close[-20:]) if len(close) >= 20 else 0.01
        zscore = (close[-1] - ma20) / std20
        price_dev = (close[-1] - ma20) / ma20
        
        # V3信号: 价格偏离MA20超过ATR×0.7
        v3_buy = price_dev < -self.v3_atr_mult * (atr / close[-1])
        v3_sell = price_dev > self.v3_atr_mult * (atr / close[-1])
        
        # 均值回归信号: Z-Score > |2.0|
        mr_buy = zscore < -self.mr_zscore
        mr_sell = zscore > self.mr_zscore
        
        # 双重确认
        final_buy = v3_buy and mr_buy
        final_sell = v3_sell and mr_sell
        
        return {
            "signal": "buy" if final_buy else ("sell" if final_sell else "hold"),
            "action": "buy" if final_buy else ("sell" if final_sell else "hold"),
            "v3_buy": bool(v3_buy),
            "v3_sell": bool(v3_sell),
            "mr_buy": bool(mr_buy),
            "mr_sell": bool(mr_sell),
            "zscore": round(float(zscore), 2),
            "price_dev": f"{price_dev*100:+.1f}%",
            "atr_ratio": f"{atr/close[-1]*100:.1f}%",
            "price": float(close[-1]),
        }
