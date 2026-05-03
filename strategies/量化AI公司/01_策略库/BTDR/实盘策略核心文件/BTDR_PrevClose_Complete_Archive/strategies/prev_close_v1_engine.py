# -*- coding: utf-8 -*-
"""
协同 PrevClose V1 策略引擎
涡轮A: 涨10%卖出 → 等PrevClose买回
涡轮B: 跌5%买入  → 等PrevClose卖出
仓位安全边界: 7500-10500

Created: 2026-04-12
Version: 1.0.0
"""
import json, datetime
from pathlib import Path

# ============================================================
# 策略参数
# ============================================================
SELL_THRESHOLD   = 0.10   # A卖出: 价格 >= 前收 * (1 + 10%)
BUY_THRESHOLD    = 0.05   # B买入: 价格 <= 前收 * (1 - 5%)
PREV_CLOSE_A_BUYBACK_OFFSET = 0.00   # A买回: 价格 <= 前收 * (1 - 0%) = 精确前收
PREV_CLOSE_B_SELLBACK_OFFSET = 0.00   # B卖出: 价格 >= 前收 * (1 + 0%) = 精确前收
SHARES_PER_TRADE = 1000
POS_MIN = 7000
POS_MAX = 11000
POS_BALANCE_LOWER = 7500
POS_BALANCE_UPPER = 10500
COMMISSION_RATE = 0.001
SLIPPAGE_RATE   = 0.001

# ============================================================
# 状态机
# ============================================================
class TurboStrategy:
    def __init__(self, initial_pos=8894, initial_cash=200000.0):
        self.pos = initial_pos
        self.cash = initial_cash
        self.tA = None  # [sell_price, prev_close_at_sell]
        self.tB = None  # [buy_price, prev_close_at_buy]
        self.log = []

    # ---- Turbo A 触发检查 ----
    def check_A_sell(self, price, prev_close):
        if self.tA is None and self.pos > POS_MIN:
            if price >= prev_close * (1 + SELL_THRESHOLD):
                q = min(SHARES_PER_TRADE, self.pos - POS_MIN)
                sp = price * (1 - SLIPPAGE_RATE)
                self.cash += sp * q * (1 - COMMISSION_RATE)
                self.pos -= q
                self.tA = [sp, prev_close]  # 记录卖出价和当日的前收
                self.log.append({
                    'dt': 'sell_A', 'price': sp, 'qty': q,
                    'pos': self.pos, 'note': f'A卖出@{sp:.2f} (前收{prev_close:.2f}, +{SELL_THRESHOLD*100:.0f}%)'
                })
                return True
        return False

    # ---- Turbo A 买回检查 ----
    def check_A_buyback(self, price, prev_close):
        if self.tA is not None:
            sell_price, prev_close_at_sell = self.tA
            # PrevClose条件: 价格跌回至A卖出当日的前收
            if price <= prev_close_at_sell:
                q = min(SHARES_PER_TRADE, int(self.cash / price))
                if q > 0:
                    bp = price * (1 + SLIPPAGE_RATE)
                    self.cash -= bp * q * (1 + COMMISSION_RATE)
                    self.pos += q
                    profit = (sell_price - bp) * q
                    self.log.append({
                        'dt': 'buyback_A', 'price': bp, 'qty': q,
                        'profit': profit, 'pos': self.pos,
                        'note': f'A买回@{bp:.2f} (目标前收{prev_close_at_sell:.2f}, 等0d)'
                    })
                self.tA = None
                return True
            # 安全边界: 仓位过低，协同B补位买
            elif self.pos < POS_BALANCE_LOWER:
                self.log.append({
                    'dt': 'warn_A_balance', 'pos': self.pos,
                    'note': f'A等待买回中但仓位{self.pos}<{POS_BALANCE_LOWER}，B应自动买入补位'
                })
        return False

    # ---- Turbo B 触发检查 ----
    def check_B_buy(self, price, prev_close):
        if self.tB is None and self.pos < POS_MAX:
            if price <= prev_close * (1 - BUY_THRESHOLD):
                q = min(SHARES_PER_TRADE, int(self.cash / price), POS_MAX - self.pos)
                if q > 0:
                    bp = price * (1 + SLIPPAGE_RATE)
                    self.cash -= bp * q * (1 + COMMISSION_RATE)
                    self.pos += q
                    self.tB = [bp, prev_close]
                    self.log.append({
                        'dt': 'buy_B', 'price': bp, 'qty': q,
                        'pos': self.pos, 'note': f'B买入@{bp:.2f} (前收{prev_close:.2f}, -{BUY_THRESHOLD*100:.0f}%)'
                    })
                    return True
        return False

    # ---- Turbo B 卖出检查 ----
    def check_B_sellback(self, price, prev_close):
        if self.tB is not None:
            buy_price, prev_close_at_buy = self.tB
            # PrevClose条件: 价格反弹至B买入当日的前收
            if price >= prev_close_at_buy:
                q = min(SHARES_PER_TRADE, self.pos - POS_MIN)
                if q > 0:
                    sp = price * (1 - SLIPPAGE_RATE)
                    self.cash += sp * q * (1 - COMMISSION_RATE)
                    self.pos -= q
                    profit = (sp - buy_price) * q
                    self.log.append({
                        'dt': 'sellback_B', 'price': sp, 'qty': q,
                        'profit': profit, 'pos': self.pos,
                        'note': f'B卖出@{sp:.2f} (目标前收{prev_close_at_buy:.2f}, 等0d)'
                    })
                self.tB = None
                return True
            # 安全边界: 仓位过高，协同A补位卖
            elif self.pos > POS_BALANCE_UPPER:
                self.log.append({
                    'dt': 'warn_B_balance', 'pos': self.pos,
                    'note': f'B等待卖出中但仓位{self.pos}>{POS_BALANCE_UPPER}，A应自动卖出减位'
                })
        return False

    def status(self):
        return {
            'pos': self.pos, 'cash': round(self.cash, 2),
            'tA': self.tA, 'tB': self.tB,
            'portfolio_value': round(self.pos * 0 + self.cash, 2)  # price needed for valuation
        }


# ============================================================
# 快速回测验证
# ============================================================
if __name__ == '__main__':
    import pandas as pd
    DATA_DIR = Path('C:/Trading/data')
    with open(DATA_DIR / 'btdr_daily_360d.json') as f:
        d = json.load(f)
    df = pd.DataFrame(d)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)
    for col in ['open','high','low','close']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['close']).reset_index(drop=True)

    ps = df['close'].values.astype(float)
    p0 = 8894; c0 = 200000.0
    pos = p0; cash = c0
    tA = None; tB = None
    log = []; trades = 0

    for i in range(len(ps)):
        p = ps[i]
        if i == 0: continue
        prv = ps[i-1]

        # A sell
        if tA is None and pos > POS_MIN:
            if p >= prv * (1 + SELL_THRESHOLD):
                q = min(1000, pos - POS_MIN); sp = p * (1 - SLIPPAGE_RATE)
                cash += sp * q * (1 - COMMISSION_RATE); pos -= q; trades += 1
                tA = [sp, prv]; log.append(('A_sell', i, sp, q))
        # A buyback
        if tA is not None:
            if p <= tA[1]:
                q = min(1000, int(cash / p)); bp = p * (1 + SLIPPAGE_RATE)
                cash -= bp * q * (1 + COMMISSION_RATE); pos += q
                log.append(('A_buy', i, bp, q, tA[0] - bp))
                tA = None
            elif pos < POS_BALANCE_LOWER:
                log.append(('A_balance_warn', i, pos))
        # B buy
        if tB is None and pos < POS_MAX:
            if p <= prv * (1 - BUY_THRESHOLD):
                q = min(1000, int(cash / p), POS_MAX - pos)
                if q > 0:
                    bp = p * (1 + SLIPPAGE_RATE)
                    cash -= bp * q * (1 + COMMISSION_RATE); pos += q; trades += 1
                    tB = [bp, prv]; log.append(('B_buy', i, bp, q))
        # B sellback
        if tB is not None:
            if p >= tB[1]:
                q = min(1000, pos - POS_MIN); sp = p * (1 - SLIPPAGE_RATE)
                cash += sp * q * (1 - COMMISSION_RATE); pos -= q
                log.append(('B_sell', i, sp, q, sp - tB[0]))
                tB = None
            elif pos > POS_BALANCE_UPPER:
                log.append(('B_balance_warn', i, pos))

    fv = pos * ps[-1] + cash; sv = p0 * ps[0] + c0
    gross = sum(e[4] for e in log if len(e) > 4)
    cost = trades * (ps[-1] * 1000 * COMMISSION_RATE + 1000 * 0.05)
    net = gross - cost
    print(f'回测验证 | 交易{trades}笔 | 毛利${gross:,.0f} | 净${net:,.0f} | 超额{(fv-sv)/sv*100-(ps[-1]/ps[0]-1)*100:+.2f}%')
    print(f'持仓{pos}股 | 现金${cash:,.0f} | 总值${fv:,.0f} vs 基准${sv:,.0f}')
