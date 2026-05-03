# -*- coding: utf-8 -*-
"""
协同 PrevClose V1 → V2 优化
核心问题：10%触发+精确PrevClose(0%)是否最优？
探索：更宽松的卖出触发 + 更深的买回折扣 → 更多交易机会

测试维度：
1. 卖出触发: 3%/4%/5%/6%/7%/8%/10%/12%/15%
2. A买回折扣: 0%/-1%/-2%/-3%/-5%  (0%=精确PrevClose, -3%=前收-3%买回)
3. B卖出溢价: 0%/+1%/+2%/+3%/+5%   (0%=精确PrevClose, +3%=前收+3%卖出)
4. B买入折扣: 3%/5%/7%/10%
"""
import json, warnings
import numpy as np
import pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('C:/Trading/data')
with open(DATA_DIR / 'btdr_daily_360d.json') as f:
    d = json.load(f)
df = pd.DataFrame(d)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
for col in ['open','high','low','close']:
    df[col] = pd.parse(col, errors='coerce') if False else pd.to_numeric(df[col], errors='coerce')
df = df.dropna(subset=['close','open']).reset_index(drop=True)
ps = df['close'].values.astype(float)
n = len(ps)
bh = round((ps[-1]/ps[0]-1)*100, 2)
print(f'Data: {n} days, BH={bh}%')
print()

# ============================================================
# 核心回测引擎 (PrevClose + Offset 支持)
# ============================================================
def run_prev_offset(n_bars, prices,
                    sell_t,     # A卖出触发: price >= prev_close * (1+sell_t)
                    buy_t,      # B买入触发: price <= prev_close * (1-buy_t)
                    A_offset,   # A买回折扣: price <= prev_close_at_A_sell * (1+A_offset)
                                 #   A_offset=0   → 精确PrevClose
                                 #   A_offset=-0.03 → 前收-3%买回（更容易成交）
                    B_offset,   # B卖出溢价: price >= prev_close_at_B_buy * (1+B_offset)
                                 #   B_offset=0   → 精确PrevClose
                                 #   B_offset=+0.03 → 前收+3%卖出（更容易成交）
                    pos_min=7000, pos_max=11000,
                    bal_lower=7500, bal_upper=10500,
                    p0=8894, cash0=200000.0,
                    comm=0.001, slip=0.001):
    """
    PrevClose + Offset 版本：
    - A卖出: sell_t% 触发
    - A买回: 触发价 = A卖出当日的前收 * (1 + A_offset)
      A_offset<0 → 买回价更低 → 更容易买回（但利润更薄）
      A_offset=-0.03: 前收-3%买回，折扣3%
    - B买入: buy_t% 触发
    - B卖出: 触发价 = B买入当日的前收 * (1 + B_offset)
      B_offset>0 → 卖出价更高 → 更容易卖出（但利润更薄）
      B_offset=+0.03: 前收+3%卖出，溢价3%
    """
    pos = p0; cash = cash0
    tA = None  # [sell_price, prev_close_at_sell]
    tB = None  # [buy_price, prev_close_at_buy]
    pA = 0.0; pB = 0.0; cost = 0.0; vol = 0.0
    nA = 0; nB = 0; nA_exp = 0; nB_exp = 0
    nA_comp = 0; nB_comp = 0
    trades = 0; log = []

    for i in range(n_bars):
        p = float(prices[i])
        if i == 0: continue
        prv = float(prices[i-1])

        # ---- A Sell ----
        if tA is None and pos > pos_min:
            if p >= prv * (1 + sell_t):
                q = min(1000, pos - pos_min)
                sp = p * (1 - slip)
                cash += sp * q * (1 - comm); cost += sp * q * comm; vol += sp * q
                pos -= q; trades += 1
                tA = [sp, prv]
                log.append(('A_sell', i, sp, q, prv, 'price'))

        # ---- A Buyback ----
        if tA is not None:
            sell_price, prev_close_at_A = tA
            # 买回触发价
            buyback_target = prev_close_at_A * (1 + A_offset)
            bp = buyback_target * (1 + slip)
            if p <= buyback_target:
                q = min(1000, int(cash / bp))
                if q > 0:
                    bp_actual = p * (1 + slip)  # 以实际价格成交
                    val = bp_actual * q
                    cash -= val * (1 + comm); cost += val * comm; vol += val
                    pos += q
                    pA += (sell_price - bp_actual) * q; nA += 1
                    log.append(('A_buy', i, bp_actual, q, sell_price - bp_actual,
                                prev_close_at_A, buyback_target, A_offset, 'prev_close'))
                tA = None
            elif pos < bal_lower:
                # 协同B补位
                q = min(1000, int(cash / p))
                if q > 0:
                    bp2 = p * (1 + slip)
                    cash -= bp2 * q * (1 + comm); cost += bp2 * q * comm
                    pos += q; trades += 1; nA_comp += 1
                    log.append(('A_comp_buy', i, bp2, q, 0, prev_close_at_A, p, A_offset, 'balance'))
                    if tB is None: tB = [bp2, prv]

        # ---- B Buy ----
        if tB is None and pos < pos_max:
            if p <= prv * (1 - buy_t):
                q = min(1000, int(cash / p), pos_max - pos)
                if q > 0:
                    bp = p * (1 + slip)
                    cash -= bp * q * (1 + comm); cost += bp * q * comm; vol += bp * q
                    pos += q; trades += 1; nB += 1
                    tB = [bp, prv]
                    log.append(('B_buy', i, bp, q, prv, 'price'))

        # ---- B Sellback ----
        if tB is not None:
            buy_price, prev_close_at_B = tB
            # 卖出触发价
            sellback_target = prev_close_at_B * (1 + B_offset)
            if p >= sellback_target:
                q = min(1000, pos - pos_min)
                if q > 0:
                    sp = p * (1 - slip)
                    val = sp * q
                    cash += val * (1 - comm); cost += val * comm; vol += val
                    pos -= q
                    pB += (sp - buy_price) * q; nB += 1
                    log.append(('B_sell', i, sp, q, sp - buy_price,
                                prev_close_at_B, sellback_target, B_offset, 'prev_close'))
                tB = None
            elif pos > bal_upper:
                # 协同A减位
                q = min(1000, pos - pos_min)
                if q > 0:
                    sp = p * (1 - slip)
                    cash += sp * q * (1 - comm); cost += sp * q * comm
                    pos -= q; trades += 1; nB_comp += 1
                    log.append(('B_comp_sell', i, sp, q, 0, prev_close_at_B, p, B_offset, 'balance'))
                    if tA is None: tA = [sp, prv]

    gross = round(pA + pB)
    net = round(pA + pB - cost)
    fv = pos * float(prices[-1]) + cash
    sv = p0 * float(prices[0]) + cash0
    ret = round((fv - sv) / sv * 100, 3)
    excess = round(ret - bh, 3)

    # 胜率
    fills = [e for e in log if e[0] in ('A_buy', 'B_sell')]
    wins = sum(1 for e in fills if len(e) > 4 and e[4] > 0)
    wr = wins / len(fills) * 100 if fills else 0

    return {
        'sell_t': sell_t, 'buy_t': buy_t,
        'A_offset': A_offset, 'B_offset': B_offset,
        'trades': trades, 'gross': gross, 'cost': round(cost),
        'net': net, 'ret': ret, 'excess': excess,
        'nA': nA, 'nB': nB,
        'nA_exp': nA_exp, 'nB_exp': nB_exp,
        'nA_comp': nA_comp, 'nB_comp': nB_comp,
        'win_rate': round(wr, 1),
        'na_fills': sum(1 for e in log if e[0]=='A_buy'),
        'nb_fills': sum(1 for e in log if e[0]=='B_sell'),
        'vol': round(vol),
        'log': log, 'bh': bh
    }


# ============================================================
# PART 1: A_offset 扫描（固定 S=10%, B_offset=0）
# ============================================================
print('='*72)
print('PART 1: A_offset 扫描  (固定 S=10%, B=5%/0%)')
print('='*72)
print()
print('A_offset: 0%=精确前收, -1%=前收-1%买回, -3%=前收-3%买回...')
print('  (=0):  等价格精确反弹 → 机会少但利润高')
print('  (<0):  价格跌更多才买回 → 机会更少（更严格）还是更多？')
print()
print('{:<20} {:>5} {:>7} {:>7} {:>7} {:>8} {:>7} {:>6} {:>5}'.format(
    '配置','交易','A_offset','毛利$','净利$','超额%','A笔','B笔','胜率'))
print('-'*72)

offset_results = []
A_offsets = [0.0, -0.01, -0.02, -0.03, -0.05]
for ao in A_offsets:
    r = run_prev_offset(n, ps, 0.10, 0.05, ao, 0.0)
    r['name'] = f'S10%_A_off{ao:+.0%}'
    offset_results.append(r)
    print('{:<20} {:>5} {:>+7.2%} ${:>6,.0f} ${:>+7,.0f} {:>+7.3f}% {:>5} {:>5} {:>5.1f}%'.format(
        r['name'], r['trades'], ao, r['gross'], r['net'], r['excess'],
        r['na_fills'], r['nb_fills'], r['win_rate']))

# ============================================================
# PART 2: B_offset 扫描（固定 S=10%, A=0%）
# ============================================================
print()
print('='*72)
print('PART 2: B_offset 扫描  (固定 S=10%, A=0%)')
print('='*72)
print()
print('{:<20} {:>5} {:>7} {:>7} {:>7} {:>8} {:>7} {:>6} {:>5}'.format(
    '配置','交易','B_offset','毛利$','净利$','超额%','A笔','B笔','胜率'))
print('-'*72)

B_offsets = [0.0, 0.01, 0.02, 0.03, 0.05]
b_offset_results = []
for bo in B_offsets:
    r = run_prev_offset(n, ps, 0.10, 0.05, 0.0, bo)
    r['name'] = f'S10%_B_off{bo:+.0%}'
    b_offset_results.append(r)
    print('{:<20} {:>5} {:>+7.2%} ${:>6,.0f} ${:>+7,.0f} {:>+7.3f}% {:>5} {:>5} {:>5.1f}%'.format(
        r['name'], r['trades'], bo, r['gross'], r['net'], r['excess'],
        r['na_fills'], r['nb_fills'], r['win_rate']))

# ============================================================
# PART 3: 组合网格扫描 (S_t × A_offset × B_offset)
# ============================================================
print()
print('='*72)
print('PART 3: 完整网格扫描  S触发 × A买回折扣 × B卖出溢价')
print('='*72)

sell_ts = [0.03, 0.04, 0.05, 0.06, 0.07, 0.08, 0.10, 0.12]
A_offsets_scan = [0.0, -0.01, -0.02, -0.03, -0.05]
B_offsets_scan = [0.0, 0.01, 0.02, 0.03, 0.05]

all_results = []
for st in sell_ts:
    for ao in A_offsets_scan:
        for bo in B_offsets_scan:
            r = run_prev_offset(n, ps, st, 0.05, ao, bo)
            r['name'] = f'S{st:.0%}_Ao{ao:+.0%}_Bo{bo:+.0%}'
            all_results.append(r)

# 按净利排序
all_sorted = sorted(all_results, key=lambda x: x['net'], reverse=True)

print()
print('{:<30} {:>5} {:>7} {:>7} {:>7} {:>8} {:>7} {:>5}'.format(
    '配置','交易','毛利$','佣金$','净利$','超额%','胜率','评分'))
print('-'*82)

for i, r in enumerate(all_sorted[:20]):
    score = (r['net'] / 20000 * 0.5) + (r['trades'] / 30 * 0.2) + (r['win_rate'] / 100 * 0.3)
    flag = '★' if r['net'] > 15000 else ('+' if r['net'] > 0 else '-')
    print('{:<30} {:>5} ${:>6,.0f} ${:>5,.0f} ${:>+6,.0f} {:>+7.3f}% {:>5.1f}% {:>5.3f} {}'.format(
        r['name'][:28], r['trades'], r['gross'], r['cost'], r['net'],
        r['excess'], r['win_rate'], score, flag))

# ============================================================
# PART 4: Top5 详细成交分析
# ============================================================
print()
print('='*72)
print('PART 4: Top5 最优策略详细分析')
print('='*72)

top5 = all_sorted[:5]
for rank, r in enumerate(top5):
    print()
    print(f'--- #{rank+1}: {r["name"]} | 交易{r["trades"]}笔 | 净${r["net"]:,.0f} | 超额{r["excess"]:+.3f}% | 胜率{r["win_rate"]:.1f}% ---')
    log = r['log']
    a_log = [e for e in log if e[0] in ('A_sell','A_buy','A_comp_buy')]
    b_log = [e for e in log if e[0] in ('B_buy','B_sell','B_comp_sell')]
    
    print()
    print('  涡轮A ({:>2}笔主动交易)'.format(r['na_fills']))
    if a_log:
        print('  {:<3} {:<12} {:>4} {:>7} {:>6} {:>9} {:>12} {}'.format(
            '#','类型','日idx','价格','数量','利润','目标/前收','备注'))
        print('  '+'-'*65)
        for j, e in enumerate(a_log):
            if e[0] == 'A_sell':
                print('  {:<3} {:<12} {:>4} ${:>6.2f} {:>6} {:>9} prev=${:>6.2f} {}'.format(
                    j+1, 'A卖出', e[1], e[2], e[3], '—', e[4], e[7]))
            elif e[0] == 'A_buy':
                note = f'A_offset={e[7]:+.0%}' if e[7] != 0 else 'prev_close'
                print('  {:<3} {:<12} {:>4} ${:>6.2f} {:>6} ${:>+8,.0f} target=${:>6.2f} {}'.format(
                    j+1, 'A买回', e[1], e[2], e[3], e[4], e[5], note))
            elif e[0] == 'A_comp_buy':
                print('  {:<3} {:<12} {:>4} ${:>6.2f} {:>6} ${:>+8,.0f} prev=${:>6.2f} {}'.format(
                    j+1, 'A协同补', e[1], e[2], e[3], e[4], e[5], e[7]))
    
    print()
    print('  涡轮B ({:>2}笔主动交易)'.format(r['nb_fills']))
    if b_log:
        print('  {:<3} {:<12} {:>4} {:>7} {:>6} {:>9} {:>12} {}'.format(
            '#','类型','日idx','价格','数量','利润','目标/前收','备注'))
        print('  '+'-'*65)
        for j, e in enumerate(b_log):
            if e[0] == 'B_buy':
                print('  {:<3} {:<12} {:>4} ${:>6.2f} {:>6} {:>9} prev=${:>6.2f} {}'.format(
                    j+1, 'B买入', e[1], e[2], e[3], '—', e[4], e[7]))
            elif e[0] == 'B_sell':
                note = f'B_offset={e[7]:+.0%}' if e[7] != 0 else 'prev_close'
                print('  {:<3} {:<12} {:>4} ${:>6.2f} {:>6} ${:>+8,.0f} target=${:>6.2f} {}'.format(
                    j+1, 'B卖出', e[1], e[2], e[3], e[4], e[5], note))
            elif e[0] == 'B_comp_sell':
                print('  {:<3} {:<12} {:>4} ${:>6.2f} {:>6} ${:>+8,.0f} prev=${:>6.2f} {}'.format(
                    j+1, 'B协同减', e[1], e[2], e[3], e[4], e[5], e[7]))

# ============================================================
# PART 5: 利润分解 + 关键洞察
# ============================================================
print()
print('='*72)
print('PART 5: 关键洞察分析')
print('='*72)

# 5A: 交易次数 vs 净利关系
print()
print('【洞察A】交易次数 vs 净利关系')
print('{:<25} {:>5} {:>7} {:>7} {:>7} {:>7}'.format('策略','交易','毛利$','净利$','笔均$','胜率'))
print('-'*55)
sel = [
    ('V1基准 S10%_Ao0%_Bo0%', [r for r in all_results if r['sell_t']==0.10 and r['A_offset']==0.0 and r['B_offset']==0.0][0]),
    ('更松S5%_Ao-2%_Bo+2%', [r for r in all_results if r['sell_t']==0.05 and r['A_offset']==-0.02 and r['B_offset']==0.02][0]),
    ('最松S3%_Ao-3%_Bo+3%', [r for r in all_results if r['sell_t']==0.03 and r['A_offset']==-0.03 and r['B_offset']==0.03][0]),
    ('中庸S7%_Ao-2%_Bo+2%', [r for r in all_results if r['sell_t']==0.07 and r['A_offset']==-0.02 and r['B_offset']==0.02][0]),
]
for name, r in sel:
    per_trade = r['net'] / max(r['trades'], 1)
    print('{:<25} {:>5} ${:>6,.0f} ${:>+6,.0f} ${:>+6,.0f} {:>6.1f}%'.format(
        name, r['trades'], r['gross'], r['net'], per_trade, r['win_rate']))

# 5B: 买卖价差分析
print()
print('【洞察B】买卖价差分解 (以最佳配置为例)')
best = all_sorted[0]
print(f'  最优: {best["name"]}')
print()
print('  涡轮A: 卖出触发 {sell_t:.0%} → 买回折扣 {A_off:+.0%}'.format(
    sell_t=best['sell_t'], A_off=best['A_offset']))
print('  涡轮B: 买入折扣 {buy_t:.0%} → 卖出溢价 {B_off:+.0%}'.format(
    buy_t=best['buy_t'], B_off=best['B_offset']))
print()
a_log = [e for e in best['log'] if e[0] in ('A_sell','A_buy')]
b_log = [e for e in best['log'] if e[0] in ('B_buy','B_sell')]

if a_log:
    a_sells = [e for e in a_log if e[0]=='A_sell']
    a_buys  = [e for e in a_log if e[0]=='A_buy']
    if a_buys:
        avg_sell_A = np.mean([e[2] for e in a_sells])
        avg_buy_A  = np.mean([e[2] for e in a_buys])
        spread_A   = (avg_sell_A - avg_buy_A) / avg_sell_A * 100
        print('  涡轮A: 平均卖出价 ${:.2f}  平均买回价 ${:.2f}  价差 {spread:.2f}%'.format(
            avg_sell_A, avg_buy_A, spread=spread_A))
        print('         单笔平均利润: ${:,.0f}'.format(
            np.mean([e[4] for e in a_buys])))

if b_log:
    b_buys = [e for e in b_log if e[0]=='B_buy']
    b_sells= [e for e in b_log if e[0]=='B_sell']
    if b_sells:
        avg_buy_B  = np.mean([e[2] for e in b_buys])
        avg_sell_B = np.mean([e[2] for e in b_sells])
        spread_B   = (avg_sell_B - avg_buy_B) / avg_buy_B * 100
        print('  涡轮B: 平均买入价 ${:.2f}  平均卖出价 ${:.2f}  价差 {spread:.2f}%'.format(
            avg_buy_B, avg_sell_B, spread=spread_B))
        print('         单笔平均利润: ${:,.0f}'.format(
            np.mean([e[4] for e in b_sells])))

# 5C: 折扣是否值得
print()
print('【洞察C】A_offset效果对比（固定S=10%）')
print('{:<20} {:>7} {:>6} {:>7} {:>7} {:>7} {:>8}'.format(
    'A_offset','A触发','A买回','毛利$','净利$','胜率','vs精确前收'))
print('-'*68)
base_r = [r for r in all_results if r['sell_t']==0.10 and r['A_offset']==0.0 and r['B_offset']==0.0][0]
for ao in A_offsets:
    r = [x for x in all_results if x['sell_t']==0.10 and x['A_offset']==ao and x['B_offset']==0.0][0]
    delta = r['net'] - base_r['net']
    print('{:<20} {:>+6.2%} {:>+6.2%} ${:>6,.0f} ${:>+6,.0f} {:>6.1f}% {:>+8,.0f}'.format(
        f'A={ao:+.0%}', 0.10, ao, r['gross'], r['net'], r['win_rate'], delta))

print()
print('【洞察D】B_offset效果对比（固定S=10%，A=0%）')
print('{:<20} {:>6} {:>7} {:>7} {:>7} {:>8}'.format(
    'B_offset','B触发','毛利$','净利$','胜率','vs精确前收'))
print('-'*58)
for bo in B_offsets:
    r = [x for x in all_results if x['sell_t']==0.10 and x['A_offset']==0.0 and x['B_offset']==bo][0]
    delta = r['net'] - base_r['net']
    print('{:<20} {:>+6.2%} ${:>6,.0f} ${:>+6,.0f} {:>6.1f}% {:>+8,.0f}'.format(
        f'B={bo:+.0%}', bo, r['gross'], r['net'], r['win_rate'], delta))

# ============================================================
# PART 6: 综合最优配置推荐
# ============================================================
print()
print('='*72)
print('PART 6: 最终推荐配置')
print('='*72)
print()
print('综合考虑: 净利 × 交易频率 × 胜率 × 鲁棒性')
print()

# 多维度评分
for r in all_sorted[:30]:
    # 评分公式: 净利占50% + 交易频率占20% + 胜率占20% + 鲁棒性(是否在多个S下都好)占10%
    r['score'] = (
        r['net'] / max(r['net'], 1) * 0.4 +
        min(r['trades'] / 20, 1) * 0.2 +
        r['win_rate'] / 100 * 0.2 +
        (1 if r['net'] > 10000 else 0) * 0.2
    )

final_sorted = sorted(all_sorted, key=lambda x: x['score'], reverse=True)
print('{:<30} {:>5} {:>7} {:>7} {:>8} {:>6} {:>6}'.format(
    '配置','交易','净利$','超额%','净利/HK','胜率','综合评分'))
print('-'*75)

HK_RATE = 7.8
for i, r in enumerate(final_sorted[:10]):
    net_hk = r['net'] * HK_RATE
    star = '★' if i < 3 else ' '
    print('{:<30} {:>5} ${:>6,.0f} {:>+7.3f}% ${:>+7,.0f} {:>5.1f}% {:>5.3f} {}'.format(
        r['name'][:28], r['trades'], r['net'], r['excess'],
        net_hk, r['win_rate'], r['score'], star))

print()
print('★ = 推荐候选 | 注: 综合评分=(净利*0.4 + 频率*0.2 + 胜率*0.2 + 盈利*0.2)')
print()
print('Top 3 关键参数解读:')
for i, r in enumerate(final_sorted[:3]):
    print(f'  #{i+1} {r["name"]}')
    print(f'      涡轮A: 涨{r["sell_t"]*100:.0f}%卖出 → 买回触发={r["A_offset"]:+.0%}前收')
    print(f'      涡轮B: 跌{r["buy_t"]*100:.0f}%买入 → 卖出触发={r["B_offset"]:+.0%}前收')
    print(f'      净利${r["net"]:,.0f}  交易{r["trades"]}笔  胜率{r["win_rate"]:.0f}%')
    print()
