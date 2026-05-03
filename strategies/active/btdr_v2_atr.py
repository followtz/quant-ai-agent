"""
BTDR PrevClose V2 - ATR动态阈值版
对比固定阈值版，用backtrader回测验证

ATR = Average True Range (14日)
阈值 = ATR × multiplier
"""
import backtrader as bt
import numpy as np

class BTDRPrevCloseATR(bt.Strategy):
    params = (
        ('name', 'btdr_v2_atr'),
        ('version', '2.1'),
        ('atr_period', 14),
        ('turbo_a_sell_mult', 1.4),    # ATR×1.4卖出（≈12%固定阈值，实测胜出）
        ('turbo_a_buyback_mult', 0.1), # ATR×0.1买回
        ('turbo_b_buy_mult', 0.6),     # ATR×0.6买入（≈5%固定阈值）
        ('turbo_b_sell_mult', 0.6),    # ATR×0.6卖出
        ('trade_qty', 1000),
        ('base_shares', 8000),
    )

    def __init__(self):
        self.atr = bt.indicators.ATR(self.data, period=self.params.atr_period)
        self.turbo_a_active = False
        self.turbo_b_active = False
        self.turbo_a_price = 0
        self.turbo_b_price = 0
        self.trades = 0
        self.strategy_pnl = 0

    def next(self):
        price = self.data.close[0]
        prev = self.data.close[-1]
        atr_val = self.atr[0]
        
        if atr_val <= 0:
            return
        
        # Turbo A: 高位卖出
        if not self.turbo_a_active:
            sell_trigger = prev + atr_val * self.params.turbo_a_sell_mult
            if price >= sell_trigger:
                self.turbo_a_active = True
                self.turbo_a_price = price
                self.trades += 1
        else:
            buyback = self.turbo_a_price - atr_val * self.params.turbo_a_buyback_mult
            if price <= buyback:
                pnl = (self.turbo_a_price - price) / price * self.params.trade_qty * price
                self.strategy_pnl += pnl
                self.turbo_a_active = False
                self.trades += 1

        # Turbo B: 低位买入
        if not self.turbo_b_active:
            buy_trigger = prev - atr_val * self.params.turbo_b_buy_mult
            if price <= buy_trigger:
                self.turbo_b_active = True
                self.turbo_b_price = price
                self.trades += 1
        else:
            sell_target = self.turbo_b_price + atr_val * self.params.turbo_b_sell_mult
            if price >= sell_target:
                pnl = (price - self.turbo_b_price) / price * self.params.trade_qty * price
                self.strategy_pnl += pnl
                self.turbo_b_active = False
                self.trades += 1

    def stop(self):
        self.log(f'ATR策略完成: 共{self.trades}笔交易, P&L=${self.strategy_pnl:+.2f}')
