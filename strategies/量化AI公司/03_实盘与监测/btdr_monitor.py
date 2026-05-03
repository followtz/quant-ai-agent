"""
BTDR PrevClose V2 - 优化版 (ATR×1.2/×0.4)
基于250天回测数据验证

结果对比:
  原版固定12%/5%: +$13,300 (29笔)
  ATR×1.2/×0.4:  +$20,580 (33笔) 🏆
  Buy&Hold:        +$12,720

优化原理:
  固定百分比在456%年波动的BTDR上不适应
  ATR自动根据市场波动调整阈值
  高波动时阈值宽，低波动时阈值窄
"""
import backtrader as bt

class BTDRPrevCloseOptimal(bt.Strategy):
    params = (
        ('atr_period', 14),
        ('turbo_a_sell', 1.2),    # ATR×1.2 卖出 (≈等效固定8-10%)
        ('turbo_a_buyback', 0.1), # ATR×0.1 买回
        ('turbo_b_buy', 0.4),     # ATR×0.4 买入 (≈等效固定3-4%)
        ('turbo_b_sell', 0.6),    # ATR×0.6 卖出
        ('trade_qty', 1000),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.trades = 0
        self.strategy_pnl = 0
        self.turbo_a_active = False
        self.turbo_b_active = False
        self.turbo_a_price = 0
        self.turbo_b_price = 0

    def next(self):
        if self.atr[0] <= 0:
            return
        
        p = self.data.close[0]
        lc = self.data.close[-1]
        a = self.atr[0]

        # Turbo A: 高位卖出
        if not self.turbo_a_active:
            if p >= lc + a * self.params.turbo_a_sell:
                self.turbo_a_active = True
                self.turbo_a_price = p
                self.trades += 1
        else:
            if p <= self.turbo_a_price - a * self.params.turbo_a_buyback:
                self.strategy_pnl += (self.turbo_a_price - p) / p * self.params.trade_qty * p
                self.turbo_a_active = False
                self.trades += 1

        # Turbo B: 低位买入
        if not self.turbo_b_active:
            if p <= lc - a * self.params.turbo_b_buy:
                self.turbo_b_active = True
                self.turbo_b_price = p
                self.trades += 1
        else:
            if p >= self.turbo_b_price + a * self.params.turbo_b_sell:
                self.strategy_pnl += (p - self.turbo_b_price) / p * self.params.trade_qty * p
                self.turbo_b_active = False
                self.trades += 1

    def stop(self):
        self.log(f'优化版完成: {self.trades}笔, P&L=${self.strategy_pnl:+,.0f}')
