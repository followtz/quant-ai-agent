# -*- coding: utf-8 -*-
"""
Volume Bars + Short Threshold Optimization
探索：交易量K线 + 更短触发阈值 是否能显著提升收益
"""
import json, numpy as np, pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import warnings; warnings.filterwarnings('ignore')

DATA_DIR = Path("C:/Trading/data")
OUT = DATA_DIR / "volume_short_threshold.json"

# ============================================================
# 1. 加载分钟数据
# ============================================================
print("Loading minute data...")
with open(DATA_DIR / "btdr_mins_90d.json") as f:
    raw = json.load(f)

all_rows = []
for date_key, bars in raw.items():
    for bar in bars:
        all_rows.append(bar)

df_m = pd.DataFrame(all_rows)
df_m['time_key'] = pd.to_datetime(df_m['time_key'])
df_m = df_m.sort_values('time_key').reset_index(drop=True)
for col in ['open','high','low','close','volume']:
    df_m[col] = df_m[col].astype(float)
print(f"  Minute data: {len(df_m)} rows, {df_m['time_key'].min().date()} to {df_m['time_key'].max().date()}")

# Daily aggregation (for reference comparison)
daily = df_m.groupby(df_m['time_key'].dt.date).agg(
    open=('open','first'), high=('high','max'), low=('low','min'), close=('close','last')
).reset_index(drop=True)
print(f"  Daily bars: {len(daily)} days")

# ============================================================
# 2. 构建不同阈值的交易量K线
# ============================================================
def build_volume_bars(df_min, threshold):
    """Build volume bars from minute data with given dollar volume threshold."""
    bars = []; curr = None
    for _, r in df_min.iterrows():
        dv = float(r['volume']) * float(r['close'])
        if curr is None:
            curr = {'open':float(r['open']),'high':float(r['high']),
                    'low':float(r['low']),'close':float(r['close']),
                    'volume':float(r['volume']),'time_key':r['time_key'],'dv':dv}
        else:
            curr['high'] = max(curr['high'], float(r['high']))
            curr['low'] = min(curr['low'], float(r['low']))
            curr['close'] = float(r['close'])
            curr['volume'] = curr['volume'] + float(r['volume'])
            curr['time_key'] = r['time_key']
            curr['dv'] = curr['dv'] + dv
            if curr['dv'] >= threshold:
                bars.append(curr)
                curr = None
    if curr is not None:
        bars.append(curr)
    return pd.DataFrame(bars)

def add_indicators(vb_df):
    """Add technical indicators to volume bars."""
    vb = vb_df.copy()
    vb = vb.sort_values('time_key').reset_index(drop=True)
    vb['returns'] = vb['close'].pct_change()
    for w in [5, 10, 20]:
        ma = vb['close'].rolling(w).mean()
        vb[f'ma{w}'] = ma
        vb[f'ma_ratio{w}'] = vb['close'] / ma
    vb['vol_5'] = vb['returns'].rolling(5).std()
    vb['vol_20'] = vb['returns'].rolling(20).std()
    vb['vol_ratio'] = vb['vol_5'] / vb['vol_20']
    d = vb['close'].diff()
    g = d.where(d>0,0).rolling(14).mean()
    l = (-d.where(d<0,0)).rolling(14).mean()
    vb['rsi'] = 100 - (100 / (1 + g/l))
    vb['std_20'] = vb['close'].rolling(20).std()
    vb['bb_width'] = (2 * vb['std_20']) / vb['ma20']
    vb['vol_ma5'] = vb['volume'].rolling(5).mean()
    vb['vol_ratio_v'] = vb['volume'] / vb['vol_ma5']
    mn = vb['close'].rolling(20).min()
    mx = vb['close'].rolling(20).max()
    vb['price_pos'] = (vb['close'] - mn) / (mx - mn + 1e-10)
    return vb

VOL_THRESHOLDS = [100000, 250000, 500000, 1000000, 2000000]
TRIGGERS = [0.01, 0.02, 0.03, 0.04, 0.05]

print(f"\nBuilding volume bars with thresholds: {[f'${t//1000}K' for t in VOL_THRESHOLDS]}")
volume_bars_cache = {}
for vt in VOL_THRESHOLDS:
    vb = build_volume_bars(df_m, vt)
    vb = add_indicators(vb)
    n_bars = len(vb)
    avg_dv = float(vb['dv'].mean()) if 'dv' in vb.columns else 0
    print(f"  ${vt//1000}K threshold: {n_bars} bars (avg ${avg_dv:,.0f}/bar)")
    volume_bars_cache[vt] = vb

# ============================================================
# 3. 涡轮A/B回测函数
# ============================================================
def run_bt(prices, n, sell_t, buy_t, a_mode, a_param, b_mode, b_param, adj_list=None, pos0=8894, cash0=200000.0):
    """
    Backtest Turbo A/B strategy.
    a_mode: 1=open, 2=prev_close, 3=prev_close+pct, 4=entry*retrace_down
    b_mode: 1=open, 2=prev_close, 3=prev_close+pct, 4=entry*retrace_up
    """
    pos = pos0; cash = cash0
    tA = [False, 0.0, 0.0, 0.0]  # on, entry, prev_close, open
    tB = [False, 0.0, 0.0, 0.0]  # on, entry, prev_close, open
    pA = 0.0; pB = 0.0
    n_trades = 0; nA = 0; nB = 0

    for i in range(n):
        p = float(prices[i])
        if i == 0: continue
        prv = float(prices[i-1])

        st = sell_t
        bt_trigger = buy_t
        if adj_list is not None and i < len(adj_list):
            st = max(0.01, st + adj_list[i])
            bt_trigger = max(0.01, bt_trigger - adj_list[i])

        # Turbo A: Sell high, buy back lower
        if not tA[0]:
            if p >= prv * (1 + st) and pos > 7000:
                q = min(1000, pos - 7000)
                pos -= q; cash += p * q
                tA = [True, p, prv, p]
                n_trades += 1
        else:
            bp = None
            if a_mode == 1: bp = tA[3]        # open
            elif a_mode == 2: bp = tA[2]       # prev_close
            elif a_mode == 3: bp = tA[2] * (1 + a_param)  # prev_close + pct
            elif a_mode == 4: bp = tA[1] * (1 - a_param)  # retrace from entry
            if bp is not None and p <= bp:
                q = min(1000, int(cash / p))
                if q > 0: pos += q; cash -= p * q; pA += (tA[1] - p) * q; nA += 1
                tA = [False, 0.0, 0.0, 0.0]

        # Turbo B: Buy low, sell higher
        if not tB[0]:
            if p <= prv * (1 - bt_trigger) and pos < 11000:
                q = min(1000, int(cash / p), 11000 - pos)
                if q > 0:
                    pos += q; cash -= p * q
                    tB = [True, p, prv, p]
                    n_trades += 1
        else:
            sp = None
            if b_mode == 1: sp = tB[3]        # open
            elif b_mode == 2: sp = tB[2]       # prev_close
            elif b_mode == 3: sp = tB[2] * (1 + b_param)  # prev_close + pct
            elif b_mode == 4: sp = tB[1] * (1 + b_param)  # retrace from entry
            if sp is not None and p >= sp:
                q = min(1000, pos - 7000)
                if q > 0: pos -= q; cash += p * q; pB += (p - tB[1]) * q; nB += 1
                tB = [False, 0.0, 0.0, 0.0]

    sp0 = float(prices[0]); fp = float(prices[-1])
    fv = pos * fp + cash
    sv = pos0 * sp0 + cash0
    ret = (fv - sv) / sv * 100
    bh = (fp - sp0) / sp0 * 100
    return {
        'ret': round(ret, 2), 'excess': round(ret - bh, 2),
        'pnl': round(pA + pB), 'pa': round(pA), 'pb': round(pB),
        'na': nA, 'nb': nB, 'trades': n_trades,
        'final_val': round(fv), 'bh': round(bh, 2)
    }

# ============================================================
# 4. 固定阈值扫描（无ML）
# ============================================================
print("\n" + "="*72)
print("PHASE 1: 固定阈值扫描（Volume Bars + Short Triggers, No ML）")
print("="*72)
print()
print("{:<14} {:>5} {:>7} {:>7} {:>8} {:>7} {:>7} {:>8}".format(
    "Threshold","Bars","Return","Excess","TotalPnL","TurboA","TurboB","Trades"))
print("-"*72)

results = []
bh_all = None

for vt in VOL_THRESHOLDS:
    vb = volume_bars_cache[vt]
    ps = vb['close'].values; n = len(vb)
    avg_dv = float(vb['dv'].mean())

    for sell_t in TRIGGERS:
        for buy_t in TRIGGERS:
            # Best A/B modes from previous analysis: A=prev_close+3%, B=retrace 2%
            r = run_bt(ps, n, sell_t, buy_t, a_mode=3, a_param=0.03, b_mode=4, b_param=0.02)
            bh_all = r['bh']
            results.append({
                'phase': 1, 'threshold': vt, 'bars': n, 'avg_dv': round(avg_dv),
                'sell_t': sell_t, 'buy_t': buy_t,
                'a_mode': 'prev+3%', 'b_mode': 'ret2%',
                **r
            })
            label = f"${vt//1000}K_S{int(sell_t*100)}B{int(buy_t*100)}"
            print("{:<14} {:>5} {:>+6.2f}% {:>+6.2f}% ${:>7,.0f}  {:>+6.0f}  {:>+6.0f}  {:>5}".format(
                f"${vt//1000}K / S{int(sell_t*100)}%",
                n, r['ret'], r['excess'], r['pnl'], r['pa'], r['pb'], r['na']+r['nb']))

# ============================================================
# 5. 固定阈值 + 最优短触发 vs 日线对比
# ============================================================
print("\n" + "="*72)
print("PHASE 2: 交易量K线 vs 日线（相同策略参数）")
print("="*72)

# Daily backtest
dr = run_bt(daily['close'].values, len(daily), sell_t=0.05, buy_t=0.05, a_mode=3, a_param=0.03, b_mode=4, b_param=0.02)
print(f"\nDaily (5%+5%, A+3%, Bret2%): {len(daily)} days, Ret={dr['ret']:+.2f}%, Excess={dr['excess']:+.2f}%, PnL=${dr['pnl']:,.0f}, Trades={dr['na']+dr['nb']}")
print(f"Buy&Hold (59d): {bh_all:.2f}%")

# Best volume bar result
best_v = max([x for x in results if x['threshold'] == 500000], key=lambda x: x['excess'])
best_all = max(results, key=lambda x: x['excess'])
print(f"\nBest Volume Bar ($500K): S{int(best_v['sell_t']*100)}% B{int(best_v['buy_t']*100)}%, {best_v['bars']} bars, Ret={best_v['ret']:+.2f}%, Excess={best_v['excess']:+.2f}%, PnL=${best_v['pnl']:,.0f}")
print(f"BEST OVERALL: $500K S{int(best_all['sell_t']*100)}% B{int(best_all['buy_t']*100)}%, {best_all['bars']} bars, Ret={best_all['ret']:+.2f}%, Excess={best_all['excess']:+.2f}%")

# ============================================================
# 6. ML(0.50) 动态阈值增强（仅最佳Volume Bar配置）
# ============================================================
print("\n" + "="*72)
print("PHASE 3: ML(0.50) 动态阈值增强")
print("="*72)

fc = ['returns','ma_ratio5','ma_ratio10','ma_ratio20','vol_5','vol_20',
      'vol_ratio','rsi','bb_width','vol_ratio_v','price_pos']

for vt in [250000, 500000, 1000000]:
    vb = volume_bars_cache[vt]
    n = len(vb)

    # Label
    vb2 = vb.copy()
    vb2['fr3'] = vb2['close'].shift(-3) / vb2['close'] - 1
    vb2['label'] = 0
    vb2.loc[vb2['fr3'] > 0.015, 'label'] = 1
    vb2.loc[vb2['fr3'] < -0.015, 'label'] = -1

    vb_clean = vb2.dropna(subset=fc + ['label'])
    if len(vb_clean) < 30: continue

    X = vb_clean[fc].values; y = vb_clean['label'].values
    ts = int(len(vb_clean) * 0.8)
    sc = StandardScaler()
    Xs = sc.fit_transform(X[:ts])
    ml = RandomForestClassifier(n_estimators=50, max_depth=5, min_samples_split=10,
                                 min_samples_leaf=5, random_state=42, class_weight='balanced')
    ml.fit(Xs, y[:ts])

    # Compute ML adjustments
    adj = []
    for _, row in vb.iterrows():
        fv = []; ok = True
        for c in fc:
            v = row.get(c, np.nan)
            if pd.isna(v) or np.isinf(v): ok = False; break
            fv.append(v)
        if ok:
            X2 = sc.transform(np.array(fv).reshape(1, -1))
            pred = int(ml.predict(X2)[0])
            probs = ml.predict_proba(X2)[0]
            if probs.max() > 0.50:
                adj.append(-0.005 if pred == 1 else 0.005)
            else:
                adj.append(0)
        else:
            adj.append(0)

    n_ml = sum(1 for x in adj if x != 0)
    ml_rate = n_ml / len(adj) * 100 if len(adj) > 0 else 0

    # Test with different base triggers
    for base_s in [0.02, 0.03, 0.05]:
        for base_b in [0.03, 0.05]:
            r = run_bt(vb['close'].values, n, base_s, base_b,
                       a_mode=3, a_param=0.03, b_mode=4, b_param=0.02,
                       adj_list=adj)
            results.append({
                'phase': 3, 'threshold': vt, 'bars': n,
                'sell_t': base_s, 'buy_t': base_b,
                'ml': True, 'ml_rate': round(ml_rate, 1), **r
            })
            print("  ${:<6} base={:>4}%/{:>4}%  ML({:>5.1f}%rate)  Ret={:>+6.2f}%  Excess={:>+6.2f}%  PnL=${:>7,.0f}  Trades={:>3}".format(
                f"{vt//1000}K", int(base_s*100), int(base_b*100), ml_rate, r['ret'], r['excess'], r['pnl'], r['na']+r['nb']))

# ============================================================
# 7. 最激进：超短阈值 + Volume Bars（日内涡轮）
# ============================================================
print("\n" + "="*72)
print("PHASE 4: 超短阈值 + Volume Bars（日内涡轮A/B）")
print("="*72)
print("概念：触发后当天内必须平仓（A卖→当天买回，B买→当天卖）")
print()

for vt in [100000, 250000, 500000]:
    vb = volume_bars_cache[vt]
    ps = vb['close'].values; n = len(vb)

    for sell_t in [0.01, 0.02, 0.03]:
        for buy_t in [0.01, 0.02, 0.03]:
            # Same-day-close version: A buys back at retrace 1%, B sells at retrace 1%
            r = run_bt(ps, n, sell_t, buy_t, a_mode=4, a_param=0.01, b_mode=4, b_param=0.01)
            results.append({
                'phase': 4, 'threshold': vt, 'bars': n,
                'sell_t': sell_t, 'buy_t': buy_t,
                'a_mode': 'ret1%', 'b_mode': 'ret1%', **r
            })
            print("  ${:<6} S{:<3}B{:<3} same-day  Ret={:>+6.2f}%  Excess={:>+6.2f}%  PnL=${:>7,.0f}  Trades={:>3}".format(
                f"{vt//1000}K", int(sell_t*100), int(buy_t*100), r['ret'], r['excess'], r['pnl'], r['na']+r['nb']))

# ============================================================
# 8. 保存完整结果
# ============================================================
with open(OUT, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\nSaved {len(results)} configs to {OUT}")

# ============================================================
# 9. 最终排名
# ============================================================
print("\n" + "="*72)
print("FINAL RANKING: Top 20 Configurations")
print("="*72)
print("{:<5} {:<14} {:<6} {:<8} {:>6} {:>7} {:>8} {:>7}".format(
    "Rank","Threshold","Bars","Trigger","Return","Excess","PnL","Trades"))
print("-"*72)
top = sorted(results, key=lambda x: x['excess'], reverse=True)[:20]
for i, x in enumerate(top):
    phase_tag = "[M]" if x.get('ml') else ("[D]" if x.get('phase',0)==4 else "[ ]")
    print("{:<5} ${:<12} {:>6} {:>5}%/{:>5}% {:>+6.2f}% {:>+7.2f}% ${:>6,.0f}  {:>5}  {}".format(
        f"#{i+1}", f"{x['threshold']//1000}K", x['bars'],
        int(x['sell_t']*100), int(x['buy_t']*100),
        x['ret'], x['excess'], x['pnl'], x['na']+x['nb'], phase_tag))

print(f"\nBuy&Hold (59d): {bh_all:+.2f}%")
print(f"Daily bars benchmark (5%+5%): Ret={dr['ret']:+.2f}%, Excess={dr['excess']:+.2f}%")
