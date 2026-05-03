# -*- coding: utf-8 -*-
"""
全年回测（341天）+ 交易成本敏感性分析
1. 不同触发阈值的全年表现
2. 佣金敏感性（0.05% ~ 0.30%）
3. 滑点敏感性（0.00% ~ 0.30%）
4. 组合场景分析
"""
import json, numpy as np, pandas as pd
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')

DATA_DIR = Path("C:/Trading/data")
OUT = DATA_DIR / "cost_sensitivity.json"

# ============================================================
# 加载数据
# ============================================================
print("Loading daily data...")
with open(DATA_DIR / "btdr_daily_360d.json") as f:
    d = json.load(f)
df = pd.DataFrame(d)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
for col in ['open','high','low','close','volume']:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df = df.dropna(subset=['close','open']).reset_index(drop=True)
prices = df['close'].values.astype(float)
opens = df['open'].values.astype(float)
n = len(prices)
bh_ret = round((prices[-1]/prices[0]-1)*100, 2)
print(f"  {n} trading days: {df['date'].min().date()} → {df['date'].max().date()}")
print(f"  BH return: {bh_ret}%")
print(f"  Start: ${prices[0]:.2f} → End: ${prices[-1]:.2f}")

# ============================================================
# 回测引擎（支持佣金+滑点）
# ============================================================
def run_bt(prices, opens_arr, n_bars,
           sell_t, buy_t,
           a_mode, a_param,
           b_mode, b_param,
           commission=0.001,    # 佣金率（如0.001=0.1%）
           slippage=0.0,        # 滑点率
           pos0=8894, cash0=200000.0,
           name=""):
    """
    commission: 每笔交易双向收取（买入+卖出各收一次 = 2×commission）
    slippage: 成交价偏移比例（卖出-滑点，买入+滑点）
    a_mode: 1=open, 2=prev_close, 3=prev_close+pct, 4=entry*retrace_down
    b_mode: 1=open, 2=prev_close, 3=prev_close+pct, 4=entry*retrace_up
    """
    pos = pos0; cash = cash0
    tA = [False, 0.0, 0.0, 0.0]  # on, entry, prev_close, open
    tB = [False, 0.0, 0.0, 0.0]
    pA = 0.0; pB = 0.0
    n_trades = 0; nA = 0; nB = 0
    cost_total = 0.0
    volume_total = 0.0

    for i in range(n_bars):
        price = float(prices[i])
        op = float(opens_arr[i]) if i < len(opens_arr) else price
        if i == 0: continue
        prev = float(prices[i-1])

        # Turbo A: Sell high → buy back lower
        if not tA[0]:
            if price >= prev * (1 + sell_t) and pos > 7000:
                q = min(1000, pos - 7000)
                sell_price = price * (1 - slippage)   # 卖出收滑点
                trade_val = sell_price * q
                c = trade_val * commission              # 双向佣金
                pos -= q; cash += trade_val - c
                cost_total += c; volume_total += trade_val
                tA = [True, sell_price, prev, op]
                n_trades += 1
        else:
            bp = None
            if a_mode == 1: bp = tA[3]
            elif a_mode == 2: bp = tA[2]
            elif a_mode == 3: bp = tA[2] * (1 + a_param)
            elif a_mode == 4: bp = tA[1] * (1 - a_param)
            if bp is not None:
                buy_price = bp * (1 + slippage)  # 买回收滑点
                if price <= buy_price:
                    q = min(1000, int(cash / buy_price))
                    if q > 0:
                        trade_val = buy_price * q
                        c = trade_val * commission
                        pos += q; cash -= trade_val + c
                        cost_total += c; volume_total += trade_val
                        pA += (tA[1] - buy_price) * q
                        nA += 1
                    tA = [False, 0.0, 0.0, 0.0]

        # Turbo B: Buy low → sell higher
        if not tB[0]:
            if price <= prev * (1 - buy_t) and pos < 11000:
                q = min(1000, int(cash / price), 11000 - pos)
                if q > 0:
                    buy_price = price * (1 + slippage)
                    trade_val = buy_price * q
                    c = trade_val * commission
                    pos += q; cash -= trade_val + c
                    cost_total += c; volume_total += trade_val
                    tB = [True, buy_price, prev, op]
                    n_trades += 1
        else:
            sp = None
            if b_mode == 1: sp = tB[3]
            elif b_mode == 2: sp = tB[2]
            elif b_mode == 3: sp = tB[2] * (1 + b_param)
            elif b_mode == 4: sp = tB[1] * (1 + b_param)
            if sp is not None:
                sell_price = sp * (1 - slippage)
                if price >= sell_price:
                    q = min(1000, pos - 7000)
                    if q > 0:
                        trade_val = sell_price * q
                        c = trade_val * commission
                        pos -= q; cash += trade_val - c
                        cost_total += c; volume_total += trade_val
                        pB += (sell_price - tB[1]) * q
                        nB += 1
                    tB = [False, 0.0, 0.0, 0.0]

    fp = float(prices[-1])
    fv = pos * fp + cash
    sv = pos0 * float(prices[0]) + cash0
    ret = (fv - sv) / sv * 100
    excess = ret - bh_ret
    total_cost = cost_total
    net_pnl = pA + pB - total_cost

    return {
        'name': name,
        'sell_t': sell_t, 'buy_t': buy_t,
        'a_mode': a_mode, 'a_param': a_param,
        'b_mode': b_mode, 'b_param': b_param,
        'commission': commission, 'slippage': slippage,
        'ret': round(ret, 3), 'excess': round(excess, 3),
        'gross_pnl': round(pA + pB), 'cost': round(total_cost),
        'net_pnl': round(net_pnl),
        'pa': round(pA), 'pb': round(pB),
        'na': nA, 'nb': nB, 'trades': n_trades,
        'final_val': round(fv), 'bh': bh_ret,
        'volume': round(volume_total),
    }

# ============================================================
# PART 1: 无交易成本的全年基础测试
# ============================================================
print("\n" + "="*75)
print("PART 1: 全年基础回测（无交易成本）")
print("="*75)
print(f"Data: {n} trading days  |  BH: {bh_ret}%")
print()
print("{:<12} {:>5} {:>8} {:>8} {:>10} {:>9} {:>8} {:>7}".format(
    "Trigger","Bars","Return","Excess","GrossPnL","Cost","NetPnL","Trades"))
print("-"*72)

triggers = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10]
# A: prev_close+3%, B: retrace 2% (best from previous analysis)
results = []

for st in triggers:
    for bt2 in [0.03, 0.04, 0.05]:
        if st <= bt2 * 0.5: continue  # sell must be at least half of buy
        r = run_bt(prices, opens, n, st, bt2,
                   a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
                   commission=0.0, slippage=0.0,
                   name=f"S{int(st*100)}%_B{int(bt2*100)}%")
        results.append(r.copy())
        print("{:<12} {:>5} {:>+7.3f}% {:>+7.3f}% ${:>9,.0f} ${:>8,.0f} ${:>6,.0f} {:>5}".format(
            f"S{int(st*100)}%/B{int(bt2*100)}%", n, r['ret'], r['excess'],
            r['gross_pnl'], 0, r['gross_pnl'], r['trades']))

# ============================================================
# PART 2: 交易成本敏感性分析（最佳触发配置）
# ============================================================
print("\n" + "="*75)
print("PART 2: 交易成本敏感性分析")
print("="*75)

# Find best trigger from Part 1
best_no_cost = max(results, key=lambda x: x['net_pnl'])
best_st = best_no_cost['sell_t']
best_bt = best_no_cost['buy_t']
print(f"\nUsing best trigger: S{int(best_st*100)}% / B{int(best_bt*100)}%")
print()

commissions = [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]
slippages   = [0.0, 0.0005, 0.001, 0.0015, 0.002, 0.0025, 0.003]

cost_matrix = []

# 2a: 佣金敏感性（无滑点）
print("佣金敏感性（无滑点）:")
print("{:<14} {:>6} {:>7} {:>8} {:>9} {:>8} {:>7}".format(
    "Commission","Trades","Return","Excess","GrossPnL","Cost","NetPnL"))
print("-"*62)
for c in commissions:
    r = run_bt(prices, opens, n, best_st, best_bt,
               a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
               commission=c, slippage=0.0, name=f"c={c}")
    cost_matrix.append(r.copy())
    comm_label = f"{c*100:.2f}%" if c > 0 else "0.00%"
    print("{:<14} {:>6} {:>+6.3f}% {:>+7.3f}% ${:>8,.0f} ${:>7,.0f} ${:>6,.0f}".format(
        comm_label, r['trades'], r['ret'], r['excess'], r['gross_pnl'], r['cost'], r['net_pnl']))

print()
print("滑点敏感性（佣金=0.10%，无滑点→0.30%）:")
print("{:<12} {:>6} {:>7} {:>8} {:>9} {:>8} {:>7}".format(
    "Slippage","Trades","Return","Excess","GrossPnL","Cost","NetPnL"))
print("-"*62)
for s in slippages:
    r = run_bt(prices, opens, n, best_st, best_bt,
               a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
               commission=0.001, slippage=s, name=f"s={s}")
    cost_matrix.append(r.copy())
    slip_label = f"{s*100:.2f}%" if s > 0 else "0.00%"
    print("{:<12} {:>6} {:>+6.3f}% {:>+7.3f}% ${:>8,.0f} ${:>7,.0f} ${:>6,.0f}".format(
        slip_label, r['trades'], r['ret'], r['excess'], r['gross_pnl'], r['cost'], r['net_pnl']))

# 2b: 组合场景矩阵
print("\n组合场景矩阵（佣金 × 滑点 → NetPnL）:")
print("{:<10}".format(""), end="")
for s in slippages:
    print(" {:>8}".format(f"Slip={s*100:.1f}%"), end="")
print()
print("-"*75)
for c in [0.0005, 0.001, 0.0015, 0.002]:
    print("{:<10}".format(f"Comm={c*100:.2f}%"), end="")
    for s in slippages:
        r = run_bt(prices, opens, n, best_st, best_bt,
                   a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
                   commission=c, slippage=s)
        cost_matrix.append(r.copy())
        print(" {:>+7,.0f}".format(r['net_pnl']), end="")
    print()

# ============================================================
# PART 3: 各触发阈值的成本敏感性
# ============================================================
print("\n" + "="*75)
print("PART 3: 各触发阈值的成本敏感性（佣金0.10% + 滑点0.10%）")
print("="*75)
print("{:<12} {:>6} {:>7} {:>8} {:>9} {:>8} {:>7}".format(
    "Trigger","Trades","Return","Excess","GrossPnL","Cost","NetPnL"))
print("-"*62)

trigger_costs = []
for st in triggers:
    for bt2 in [0.03, 0.04, 0.05]:
        if st <= bt2 * 0.5: continue
        r = run_bt(prices, opens, n, st, bt2,
                   a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
                   commission=0.001, slippage=0.001,
                   name=f"S{int(st*100)}%_B{int(bt2*100)}%_c0.1_s0.1")
        trigger_costs.append(r.copy())
        net = r['gross_pnl'] - r['cost']
        print("{:<12} {:>6} {:>+6.3f}% {:>+7.3f}% ${:>8,.0f} ${:>6,.0f} ${:>+6,.0f}".format(
            f"S{int(st*100)}%/B{int(bt2*100)}%", r['trades'], r['ret'], r['excess'],
            r['gross_pnl'], r['cost'], net))

# ============================================================
# PART 4: 涡轮A/B不同买回策略的成本敏感性
# ============================================================
print("\n" + "="*75)
print("PART 4: 涡轮A/B买回策略 × 成本水平")
print("="*75)

# Different A/B modes
ab_configs = [
    ("A+3%_Bret2%", 3, 0.03, 4, 0.02),
    ("Aret1%_Bret2%", 4, 0.01, 4, 0.02),
    ("Aret2%_Bret2%", 4, 0.02, 4, 0.02),
    ("Aret5%_Bret5%", 4, 0.05, 4, 0.05),
    ("A-3%_B-3%", 3, -0.03, 3, -0.03),
    ("A-5%_B+5%", 3, -0.05, 3, 0.05),
]
cost_levels = [
    ("无成本", 0.0, 0.0),
    ("低(0.05%/0.05%)", 0.0005, 0.0005),
    ("中(0.10%/0.10%)", 0.001, 0.001),
    ("高(0.15%/0.15%)", 0.0015, 0.0015),
    ("极高(0.20%/0.20%)", 0.002, 0.002),
]

print("{:<18}".format("Config"), end="")
for clabel, _, _ in cost_levels:
    print(" {:>16}".format(clabel[:14]), end="")
print()
print("-"*100)

for alabel, am, ap, bm, bp in ab_configs:
    print("{:<18}".format(alabel), end="")
    for clabel, c, s in cost_levels:
        r = run_bt(prices, opens, n, 0.05, 0.05,  # symmetric 5% for comparison
                   a_mode=am, a_param=ap, b_mode=bm, b_param=bp,
                   commission=c, slippage=s)
        net = r['gross_pnl'] - r['cost']
        flag = " ★" if net > 0 else " ✗"
        print(" {:>+6,.0f}{:<10}".format(net, flag), end="")
    print()

# ============================================================
# PART 5: 真实成本估算（富途收费标准）
# ============================================================
print("\n" + "="*75)
print("PART 5: 真实成本估算（富途收费标准）")
print("="*75)
print("富途收费标准:")
print("  港股佣金: 最低HK$50/笔，或成交金额的0.10%（取高者）")
print("  美股佣金: 每股$0.0049，最低$0.99/笔")
print("  平台费: HK$15/笔")
print("  印花税: 卖出金额的0.10%（港股）")
print()
print("假设实盘成本估算（港股BTDR，1000股/笔）:")
print()

# Simulate realistic costs
def real_cost_estimate(price_per_share, shares_per_trade, trades, market="HK"):
    if market == "HK":
        # Commission: max(50 HKD, 0.1% of trade value)
        comm = max(50, price_per_share * shares_per_trade * 0.001)
        # Stamp duty on sell only
        stamp = price_per_share * shares_per_trade * 0.001 if trades > 0 else 0
        # Platform fee
        platform = 15 * trades
        cost_per_trade_hkd = comm + platform + stamp * 0.5  # stamp only on sell
        # Convert to USD (assume 1 USD = 7.8 HKD)
        cost_per_trade_usd = cost_per_trade_hkd / 7.8
    else:  # US
        comm = max(0.99, shares_per_trade * 0.0049)
        platform = 0
        stamp = 0
        cost_per_trade_usd = comm
    return cost_per_trade_hkd, cost_per_trade_usd

avg_price = float(np.mean(prices))
avg_hk_cost_per, avg_us_cost_per = real_cost_estimate(avg_price, 1000, 1, "HK")
avg_us_cost_per = real_cost_estimate(avg_price, 1000, 1, "US")[1]

print(f"  平均股价: ${avg_price:.2f} (≈HK${avg_price*7.8:.0f})")
print(f"  每笔港股成本: ≈HK${avg_hk_cost_per:.0f} (≈${avg_hk_cost_per/7.8:.2f})")
print(f"  每笔美股成本: ≈${avg_us_cost_per:.2f}")
print()

# Compare triggers with realistic costs
print("{:<12} {:>6} {:>8} {:>8} {:>10} {:>8} {:>9}".format(
    "Trigger","Trades","HKCost","USCost","GrossPnL","NetPnL(HK)","NetPnL(US)"))
print("-"*72)

trigger_real = []
for st in [0.01, 0.02, 0.03, 0.05]:
    for bt2 in [0.03, 0.05]:
        if st > bt2: continue
        r = run_bt(prices, opens, n, st, bt2,
                   a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
                   commission=0.0, slippage=0.0)
        
        hk_cost = r['trades'] * avg_hk_cost_per
        us_cost = r['trades'] * avg_us_cost_per
        net_hk = r['gross_pnl'] - hk_cost
        net_us = r['gross_pnl'] - us_cost
        
        flag_hk = " ★" if net_hk > 0 else " ✗"
        flag_us = " ★" if net_us > 0 else " ✗"
        
        print("{:<12} {:>6} ${:>7,.0f} ${:>6,.0f} ${:>9,.0f} ${:>+8,.0f}{} ${:>+7,.0f}{}".format(
            f"S{int(st*100)}%/B{int(bt2*100)}%", r['trades'],
            hk_cost, us_cost, r['gross_pnl'],
            net_hk, flag_hk, net_us, flag_us))
        
        trigger_real.append({
            'trigger': f"S{int(st*100)}%/B{int(bt2*100)}%",
            **r, 'hk_cost': round(hk_cost), 'us_cost': round(us_cost),
            'net_hk': round(net_hk), 'net_us': round(net_us)
        })

# ============================================================
# PART 6: Break-even 分析
# ============================================================
print("\n" + "="*75)
print("PART 6: 盈亏平衡分析（策略能承受的最大成本）")
print("="*75)

break_even_configs = []
for st in [0.01, 0.02, 0.03, 0.05]:
    for bt2 in [0.03, 0.05]:
        if st > bt2: continue
        r = run_bt(prices, opens, n, st, bt2,
                   a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
                   commission=0.0, slippage=0.0)
        
        gross = r['gross_pnl']
        # Break-even: cost < gross
        # Simple model: cost_per_trade = p * q * c, where c = total cost rate
        # gross_pnl = sum of profits
        # break_even_rate = gross / (total_trade_volume)
        
        # For simplicity: find the cost rate where net = 0
        # Assuming commission = slippage = x (same rate)
        # net = gross - 2 * x * volume  (2x because each trade has buy+sell)
        # 0 = gross - 2 * x * vol  →  x = gross / (2 * vol)
        
        # Actually: 2 trades per round trip (buy+sell of same position)
        # But our trades are split: some are A sells (1 trade), some are B buys (1 trade)
        # So volume here is total volume traded
        
        if r['volume'] > 0:
            # commission+slippage rate where net=0:
            # Each trade: buy pays (price+slip)*q*(1+comm), sell gets (price-slip)*q*(1-comm)
            # Simplified: net_cost ≈ 2 * x * volume
            # net = gross - 2*x*vol  →  x = gross / (2*vol)
            be_rate = gross / (2 * r['volume']) if r['volume'] > 0 else 1.0
            be_pct = be_rate * 100
        else:
            be_pct = 999
        
        break_even_configs.append({
            'trigger': f"S{int(st*100)}%/B{int(bt2*100)}%",
            'gross': gross, 'trades': r['trades'],
            'volume': r['volume'], 'be_rate': round(be_pct, 3)
        })
        print(f"  {f'S{int(st*100)}%/B{int(bt2*100)}%':<12} gross=${gross:>8,.0f}  vol=${r['volume']:>12,.0f}  break-even={be_pct:.3f}% ({be_pct*100:.2f}bp)")

best_be = max(break_even_configs, key=lambda x: x['be_rate'])
print(f"\n  盈亏平衡最高: {best_be['trigger']} 可承受 {best_be['be_rate']:.3f}% 总成本率")

# ============================================================
# 保存结果
# ============================================================
all_results = {
    'baseline': results,
    'cost_matrix': cost_matrix,
    'trigger_costs': trigger_costs,
    'trigger_real': trigger_real,
    'break_even': break_even_configs,
    'bh_ret': bh_ret,
    'period_days': n,
    'avg_price': round(float(avg_price), 2),
}
with open(OUT, 'w') as f:
    json.dump(all_results, f, indent=2)
print(f"\nSaved to {OUT}")

# ============================================================
# 汇总表
# ============================================================
print("\n" + "="*75)
print("SUMMARY: 最佳配置 × 成本水平")
print("="*75)
print("{:<14} {:>6} {:>8} {:>8} {:>9} {:>8} {:>9}".format(
    "Config","Trades","GrossPnL","Cost","NetPnL","Net/HK","Net/US"))
print("-"*72)
for x in sorted(trigger_real, key=lambda x: x['net_hk'], reverse=True):
    flag = " ★" if x['net_hk'] > 0 else " ✗"
    print("{:<14} {:>6} ${:>7,.0f} ${:>6,.0f} ${:>8,.0f} ${:>+8,.0f}  ${:>+7,.0f}".format(
        x['trigger'], x['trades'], x['gross'], x['hk_cost'],
        x['gross']-x['hk_cost'], x['net_hk'], x['net_us']) + flag)

print(f"\n  ★ = 盈利    ✗ = 亏损")
print(f"  BH return: {bh_ret}%  |  Period: {n} trading days")
