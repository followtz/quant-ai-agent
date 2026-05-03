import pandas as pd, numpy as np, json

# 加载日线数据
with open('C:/Trading/data/btdr_daily_90d.json', encoding='utf-8') as f:
    raw = json.load(f)

daily = pd.DataFrame(raw)
daily['date'] = pd.to_datetime(daily['date'])
daily = daily.sort_values('date').reset_index(drop=True)
daily['prev_close'] = daily['close'].shift(1)

# 过滤到合理范围
daily = daily[daily['date'] >= '2025-11-01'].reset_index(drop=True)
print('Trading days:', len(daily))
print('Period:', daily['date'].min().date(), '~', daily['date'].max().date())

INIT_SHARES = 10000
INIT_PRICE = daily.iloc[0]['close']  # 期初股价
INIT_CAPITAL = INIT_SHARES * INIT_PRICE
BASE = 0.05
MIN_S, MAX_S = 6000, 9000
TRADE = 1000

def run_strategy(daily, sell_ref_col, buy_ref_col, label):
    shares = INIT_SHARES
    cash = 0
    tA = None
    trades = []

    for i in range(1, len(daily)):
        row = daily.iloc[i]
        today_open = row['open']
        today_high = row['high']
        today_low = row['low']
        prev_close = row['prev_close']

        if pd.isna(prev_close):
            continue

        if sell_ref_col == 'prev_close':
            sell_trig = prev_close * (1 + BASE)
        else:
            sell_trig = today_open * (1 + BASE)

        buy_ref = row[buy_ref_col]
        buy_trig = buy_ref * (1 - BASE)

        if tA is None:
            if shares > MIN_S and today_high >= sell_trig:
                price = sell_trig
                qty = min(TRADE, shares - MIN_S)
                cash += qty * price
                shares -= qty
                tA = (price, qty)
        else:
            entry_price, pending_qty = tA
            if today_low <= buy_trig:
                price = buy_trig
                cash -= pending_qty * price
                shares += pending_qty
                pnl = (entry_price - price) * pending_qty
                cash += pnl
                trades.append((str(row['date'].date()), price, qty, pnl))
                tA = None

    # EOD结算
    final_price = daily.iloc[-1]['close']
    if tA is not None:
        entry_price, pending_qty = tA
        cash += pending_qty * final_price
        shares += pending_qty
        cash += (entry_price - final_price) * pending_qty
        tA = None

    total = shares * final_price + cash
    total_ret = (total - INIT_CAPITAL) / INIT_CAPITAL * 100
    turbo_ret = cash / INIT_CAPITAL * 100

    return {
        'label': label,
        'total': total,
        'total_ret': total_ret,
        'turbo_pnl': cash,
        'turbo_ret': turbo_ret,
        'final_shares': shares,
        'trades': len(trades),
        'trade_list': trades[-5:]
    }

# 策略A: V3现方案 - 基于昨收的5%
rA = run_strategy(daily, 'prev_close', 'prev_close', 'V3现: 昨收基准 5%/5%')

# 策略B: 锚定开盘价 - 卖出基于今开，买回基于今开
rB = run_strategy(daily, 'open', 'open', '方案B: 开盘价锚定 涨5%/回落至开盘价')

# Buy&Hold 基准
bh_price = daily.iloc[-1]['close']
bh_total = INIT_SHARES * bh_price
bh_ret = (bh_total - INIT_CAPITAL) / INIT_CAPITAL * 100

print('=' * 65)
print('   收益对比回测 (59交易日 2025-11-25 ~ 2026-02-20)')
print('=' * 65)
print()
print('起始: %d股@$%.2f = $%.0f' % (INIT_SHARES, INIT_PRICE, INIT_CAPITAL))
print('终点: $%.2f' % bh_price)
print()
print('%-30s %9s  %8s  %8s  %5s' % ('策略', '总资产', '总收益', '涡轮盈亏', '交易'))
print('-' * 65)
print('%-30s %9.0f  %+8.1f%%  %8s  %5d' % ('Buy&Hold(基准)', bh_total, bh_ret, '$0', 0))
for r in [rA, rB]:
    print('%-30s %9.0f  %+8.1f%%  %+8.0f  %5d' % (
        r['label'], r['total'], r['total_ret'], r['turbo_pnl'], r['trades']))
print()
print('%-30s %8s  %8s  %8s' % ('策略', '涡轮%', '相对B&H', '相对V3现'))
print('-' * 65)
for r in [rA, rB]:
    rel_bh = r['total_ret'] - bh_ret
    rel_v3 = r['total_ret'] - rA['total_ret'] if r != rA else 0
    print('%-30s %+7.1f%%  %+7.1f%%  %+7.1f%%' % (
        r['label'], r['turbo_ret'], rel_bh, rel_v3))
print()
print('最近5笔涡轮A交易:')
for r, name in [(rA,'V3现'), (rB,'开盘锚')]:
    print('  [%s]: %s' % (name, r['trade_list']))
