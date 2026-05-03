# -*- coding: utf-8 -*-
"""Part A: Turbo A buy-back strategies"""
import json, numpy as np, pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import warnings; warnings.filterwarnings('ignore')

DATA_DIR = Path("C:/Trading/data")
with open(DATA_DIR / "btdr_daily_360d.json", 'r') as f:
    daily_data = json.load(f)
df = pd.DataFrame(daily_data)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
for col in ['open', 'high', 'low', 'close', 'volume']:
    df[col] = df[col].astype(float)

# Indicators
df['returns'] = df['close'].pct_change()
df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
for w in [5, 10, 20, 60]:
    df['ma{}'.format(w)] = df['close'].rolling(w).mean()
    df['ma_ratio{}'.format(w)] = df['close'] / df['ma{}'.format(w)]
df['ma_20'] = df['close'].rolling(20).mean()
df['std_20'] = df['close'].rolling(20).std()
df['zscore'] = (df['close'] - df['ma_20']) / df['std_20']
df['vol_5'] = df['returns'].rolling(5).std()
df['vol_20'] = df['returns'].rolling(20).std()
df['vol_ratio'] = df['vol_5'] / df['vol_20']
delta = df['close'].diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rs = gain / loss
df['rsi'] = 100 - (100 / (1 + rs))
ema12 = df['close'].ewm(span=12).mean()
ema26 = df['close'].ewm(span=26).mean()
df['macd'] = ema12 - ema26
df['macd_sig'] = df['macd'].ewm(span=9).mean()
df['macd_hist'] = df['macd'] - df['macd_sig']
df['bb_width'] = (2 * df['std_20']) / df['ma_20']
df['bb_pos'] = (df['close'] - (df['ma_20'] - df['std_20']*2)) / (df['std_20']*4)
df['vol_ma5'] = df['volume'].rolling(5).mean()
df['vol_ratio_v'] = df['volume'] / df['vol_ma5']
df['gap'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)
df['abs_gap'] = df['gap'].abs()
df['price_pos'] = (df['close'] - df['close'].rolling(20).min()) / (df['close'].rolling(20).max() - df['close'].rolling(20).min())

feature_cols = [
    'returns', 'log_ret', 'ma_ratio5', 'ma_ratio10', 'ma_ratio20', 'ma_ratio60',
    'vol_5', 'vol_20', 'vol_ratio', 'rsi', 'macd', 'macd_sig', 'macd_hist',
    'bb_width', 'bb_pos', 'vol_ratio_v', 'gap', 'abs_gap', 'price_pos', 'zscore'
]
df['fut_ret_3d'] = df['close'].shift(-3) / df['close'] - 1
df['label'] = 0
df.loc[df['fut_ret_3d'] > 0.015, 'label'] = 1
df.loc[df['fut_ret_3d'] < -0.015, 'label'] = -1
df_clean = df.dropna(subset=feature_cols + ['label'])
X_all = df_clean[feature_cols].values
y_all = df_clean['label'].values
train_size = int(len(df_clean) * 0.8)
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_all[:train_size])
ml_model = RandomForestClassifier(n_estimators=100, max_depth=6, min_samples_split=10, min_samples_leaf=5, random_state=42, class_weight='balanced')
ml_model.fit(X_train_scaled, y_all[:train_size])
print("ML trained: {} samples".format(len(df_clean)))

def run_bt(sell_trig, buy_trig, bb_mode, bb_pct, bb_retrace, so_mode, so_pct, so_retrace, name):
    position = 8894; cash = 200000; min_s = 7000; max_s = 11000; qty = 1000
    trades = []
    tA = {'on': False, 'e': 0, 'd': 0, 'pc': 0, 'op': 0}
    tB = {'on': False, 'e': 0, 'd': 0, 'pc': 0, 'op': 0}
    prev = None
    pA = 0; pB = 0
    
    for idx in range(len(df)):
        row = df.iloc[idx]
        price = row['close']; op = row['open']
        if prev is None: prev = price; continue
        
        adj_s = sell_trig; adj_b = buy_trig
        # ML
        fv = []; ok = True
        for c in feature_cols:
            v = row.get(c, np.nan)
            if pd.isna(v) or np.isinf(v): ok = False; break
            fv.append(v)
        if ok:
            X = scaler.transform(np.array(fv).reshape(1, -1))
            pred = int(ml_model.predict(X)[0])
            probs = ml_model.predict_proba(X)[0]
            mp = probs.max()
            if mp > 0.50:
                if pred == 1: adj_s = max(0.02, sell_trig - 0.005)
                elif pred == -1: adj_b = max(0.02, buy_trig - 0.005)
        
        # Turbo A
        if not tA['on']:
            if price >= prev * (1 + adj_s) and position > min_s:
                q = min(qty, position - min_s)
                position -= q; cash += price * q
                tA = {'on': True, 'e': price, 'd': 0, 'pc': prev, 'op': op}
                trades.append({'t': 'A', 'a': 'sell', 'p': price, 'q': q})
        else:
            tA['d'] += 1
            bp = None
            if bb_mode == 'open': bp = tA['op']
            elif bb_mode == 'prev': bp = tA['pc']
            elif bb_mode == 'pct': bp = tA['pc'] * (1 + bb_pct)
            elif bb_mode == 'retrace': bp = tA['e'] * (1 - bb_retrace)
            if bp is not None and price <= bp:
                q = min(qty, int(cash / price))
                if q > 0:
                    position += q; cash -= price * q
                    pnl = (tA['e'] - price) * q; pA += pnl
                    trades.append({'t': 'A', 'a': 'buy', 'p': price, 'q': q, 'pnl': pnl, 'd': tA['d']})
                tA = {'on': False, 'e': 0, 'd': 0, 'pc': 0, 'op': 0}
        
        # Turbo B
        if not tB['on']:
            if price <= prev * (1 - adj_b) and position < max_s:
                q = min(qty, int(cash / price), max_s - position)
                if q > 0:
                    position += q; cash -= price * q
                    tB = {'on': True, 'e': price, 'd': 0, 'pc': prev, 'op': op}
                    trades.append({'t': 'B', 'a': 'buy', 'p': price, 'q': q})
        else:
            tB['d'] += 1
            sp = None
            if so_mode == 'open': sp = tB['op']
            elif so_mode == 'prev': sp = tB['pc']
            elif so_mode == 'pct': sp = tB['pc'] * (1 + so_pct)
            elif so_mode == 'retrace': sp = tB['e'] * (1 + so_retrace)
            if sp is not None and price >= sp:
                q = min(qty, position - min_s)
                if q > 0:
                    position -= q; cash += price * q
                    pnl = (price - tB['e']) * q; pB += pnl
                    trades.append({'t': 'B', 'a': 'sell', 'p': price, 'q': q, 'pnl': pnl, 'd': tB['d']})
                tB = {'on': False, 'e': 0, 'd': 0, 'pc': 0, 'op': 0}
        prev = price
    
    fp = df['close'].iloc[-1]; fv = position * fp + cash
    sp = df['close'].iloc[0]; sv = 8894 * sp + 200000
    ret = (fv - sv) / sv; bh = (fp - sp) / sp
    comp = [t for t in trades if 'pnl' in t]
    tA_c = [t for t in comp if t['t'] == 'A']
    tB_c = [t for t in comp if t['t'] == 'B']
    wr = sum(1 for t in comp if t['pnl'] > 0) / len(comp) * 100 if comp else 0
    avg_dA = np.mean([t['d'] for t in tA_c]) if tA_c else 0
    avg_dB = np.mean([t['d'] for t in tB_c]) if tB_c else 0
    
    return {
        'name': name, 'ret': ret, 'excess': ret - bh, 'pnl': pA + pB,
        'pnl_A': pA, 'pnl_B': pB, 'nA': len(tA_c), 'nB': len(tB_c),
        'wr': wr, 'avg_dA': avg_dA, 'avg_dB': avg_dB, 'pos': position
    }

# ============ PART A: Turbo A buyback strategies ============
print("=" * 80)
print("PART A: Turbo A Buy-back (Sell=5%, B=retrace5%)")
print("=" * 80)

a_configs = [
    ('open', 0, 0, 'retrace', 0, 0.05),
    ('prev', 0, 0, 'retrace', 0, 0.05),
    ('pct', 0.01, 0, 'retrace', 0, 0.05),
    ('pct', 0.02, 0, 'retrace', 0, 0.05),
    ('pct', 0.03, 0, 'retrace', 0, 0.05),
    ('pct', -0.01, 0, 'retrace', 0, 0.05),
    ('pct', -0.03, 0, 'retrace', 0, 0.05),
    ('pct', -0.05, 0, 'retrace', 0, 0.05),
    ('retrace', 0, 0.02, 'retrace', 0, 0.05),
    ('retrace', 0, 0.03, 'retrace', 0, 0.05),
    ('retrace', 0, 0.05, 'retrace', 0, 0.05),
    ('retrace', 0, 0.07, 'retrace', 0, 0.05),
]

resA = []
for bb_m, bb_p, bb_r, so_m, so_p, so_r in a_configs:
    n = "A_bb={}_{}{}".format(bb_m, bb_p, bb_r)
    r = run_bt(0.05, 0.05, bb_m, bb_p, bb_r, so_m, so_p, so_r, n)
    resA.append(r)
    print("  {}: Ret={:+.2f}% Excess={:+.2f}% A=${:,.0f}({:d}t,{:.0f}d) B=${:,.0f}({:d}t,{:.0f}d)".format(
        n, r['ret']*100, r['excess']*100, r['pnl_A'], r['nA'], r['avg_dA'], r['pnl_B'], r['nB'], r['avg_dB']))

best_A = max(resA, key=lambda x: x['ret'])
print("\n  >>> Best A buyback: {} (Ret={:+.2f}%)".format(best_A['name'], best_A['ret']*100))

# ============ PART B: Turbo B sellout strategies ============
print("\n" + "=" * 80)
print("PART B: Turbo B Sell-out (Buy=5%, A=best from above)")
print("=" * 80)

# Use best A buyback
best_bb_m = best_A['name'].split('=')[1].split('_')[0]
best_bb_param = best_A['name'].split('_')[2]

b_configs = [
    ('open', 0, 0), ('prev', 0, 0),
    ('pct', -0.01, 0), ('pct', -0.02, 0), ('pct', -0.03, 0),
    ('pct', 0.01, 0), ('pct', 0.03, 0), ('pct', 0.05, 0),
    ('retrace', 0, 0.02), ('retrace', 0, 0.03), ('retrace', 0, 0.05), ('retrace', 0, 0.07),
]

# Parse best A params for reuse
if best_bb_m == 'open': a_bb = ('open', 0, 0)
elif best_bb_m == 'prev': a_bb = ('prev', 0, 0)
elif best_bb_m == 'pct': a_bb = ('pct', float(best_bb_param.replace('%',''))/100, 0)
elif best_bb_m == 'retrace': a_bb = ('retrace', 0, float(best_bb_param.replace('%',''))/100)
else: a_bb = ('retrace', 0, 0.05)

resB = []
for so_m, so_p, so_r in b_configs:
    n = "B_so={}_{}{}".format(so_m, so_p, so_r)
    r = run_bt(0.05, 0.05, a_bb[0], a_bb[1], a_bb[2], so_m, so_p, so_r, n)
    resB.append(r)
    print("  {}: Ret={:+.2f}% Excess={:+.2f}% A=${:,.0f}({:d}t) B=${:,.0f}({:d}t,{:.0f}d)".format(
        n, r['ret']*100, r['excess']*100, r['pnl_A'], r['nA'], r['pnl_B'], r['nB'], r['avg_dB']))

best_B = max(resB, key=lambda x: x['ret'])
print("\n  >>> Best B sellout: {} (Ret={:+.2f}%)".format(best_B['name'], best_B['ret']*100))

# ============ PART C: Different trigger thresholds x best A/B ============
print("\n" + "=" * 80)
print("PART C: Trigger Threshold x Best A/B combo")
print("=" * 80)

# Best B params
best_so_m = best_B['name'].split('=')[1].split('_')[0]
best_so_param = best_B['name'].split('_')[2]
if best_so_m == 'open': b_so = ('open', 0, 0)
elif best_so_m == 'prev': b_so = ('prev', 0, 0)
elif best_so_m == 'pct': b_so = ('pct', float(best_so_param.replace('%',''))/100, 0)
elif best_so_m == 'retrace': b_so = ('retrace', 0, float(best_so_param.replace('%',''))/100)
else: b_so = ('retrace', 0, 0.05)

resC = []
for sp in [2, 3, 4, 5, 6]:
    for bp in [2, 3, 4, 5, 6]:
        n = "T:S{}B{}".format(sp, bp)
        r = run_bt(sp/100, bp/100, a_bb[0], a_bb[1], a_bb[2], b_so[0], b_so[1], b_so[2], n)
        resC.append(r)
        print("  {}: Ret={:+.2f}% Excess={:+.2f}% A=${:,.0f}({:d}t) B=${:,.0f}({:d}t)".format(
            n, r['ret']*100, r['excess']*100, r['pnl_A'], r['nA'], r['pnl_B'], r['nB']))

best_C = max(resC, key=lambda x: x['ret'])
print("\n  >>> Best trigger: {} (Ret={:+.2f}%)".format(best_C['name'], best_C['ret']*100))

# ============ PART D: Fine-tune around best combo ============
print("\n" + "=" * 80)
print("PART D: Fine-tuning All Parameters")
print("=" * 80)

# Now test all interesting combos from A/B with the best trigger thresholds
all_results = resA + resB + resC

# Additional fine-tuning: try different A/B combos with top thresholds
fine_configs = [
    # (sell%, buy%, bb_mode, bb_pct, bb_retrace, so_mode, so_pct, so_retrace)
    (5, 5, 'pct', 0.01, 0, 'pct', -0.01, 0),      # A+1% B-1%
    (5, 5, 'pct', 0.02, 0, 'pct', -0.02, 0),      # A+2% B-2%
    (5, 5, 'retrace', 0, 0.03, 'retrace', 0, 0.03),# A retr3% B retr3%
    (4, 5, 'pct', 0.01, 0, 'retrace', 0, 0.03),    # A4%+1% B5%retr3%
    (5, 4, 'retrace', 0, 0.03, 'pct', -0.01, 0),   # A5%retr3% B4%-1%
    (3, 5, 'pct', 0.01, 0, 'retrace', 0, 0.03),
    (5, 3, 'retrace', 0, 0.03, 'pct', -0.01, 0),
    (3, 3, 'pct', 0.01, 0, 'pct', -0.01, 0),
    (3, 3, 'retrace', 0, 0.02, 'retrace', 0, 0.02),
    (4, 4, 'pct', 0.02, 0, 'pct', -0.02, 0),
    (5, 5, 'open', 0, 0, 'open', 0, 0),            # Double Open
    (5, 5, 'prev', 0, 0, 'prev', 0, 0),            # Double PrevClose
    (5, 5, 'pct', 0.03, 0, 'pct', -0.03, 0),       # A+3% B-3%
    (5, 5, 'pct', 0.02, 0, 'retrace', 0, 0.03),    # Mixed
    (5, 5, 'retrace', 0, 0.03, 'pct', -0.02, 0),   # Mixed
]

resD = []
for sp, bp, bb_m, bb_p, bb_r, so_m, so_p, so_r in fine_configs:
    n = "F:S{}B{}_{}_{}".format(sp, bp, 
        "{}+{}%".format(bb_m[:3], bb_p*100) if bb_m=='pct' else "{}r{}%".format(bb_m[:3], bb_r*100) if bb_m=='retrace' else bb_m[:3],
        "{}{}%".format(so_m[:3], so_p*100) if so_m=='pct' else "{}r{}%".format(so_m[:3], so_r*100) if so_m=='retrace' else so_m[:3])
    r = run_bt(sp/100, bp/100, bb_m, bb_p, bb_r, so_m, so_p, so_r, n)
    resD.append(r)
    print("  {}: Ret={:+.2f}% Excess={:+.2f}% PnL=${:,.0f}(A${:,.0f}/{:d}t B${:,.0f}/{:d}t) WR={:.1f}%".format(
        n, r['ret']*100, r['excess']*100, r['pnl'], r['pnl_A'], r['nA'], r['pnl_B'], r['nB'], r['wr']))

# ============ FINAL RANKING ============
all_results = resA + resB + resC + resD
all_sorted = sorted(all_results, key=lambda x: x['ret'], reverse=True)

print("\n" + "=" * 80)
print("FINAL TOP 20 RANKING")
print("=" * 80)
print("{:<30} {:>9} {:>9} {:>10} {:>5} {:>5} {:>7}".format(
    'Strategy', 'Return', 'Excess', 'TotalPnL', 'A#', 'B#', 'WR'))
print("-" * 80)
for r in all_sorted[:20]:
    print("{:<30} {:>+8.2f}% {:>+8.2f}% ${:>9,.0f} {:>5d} {:>5d} {:>6.1f}%".format(
        r['name'], r['ret']*100, r['excess']*100, r['pnl'], r['nA'], r['nB'], r['wr']))

# Save
with open(DATA_DIR / "v3_threshold_deep_results.json", 'w') as f:
    json.dump(all_sorted, f, indent=2, default=str)
print("\n[Saved] v3_threshold_deep_results.json")
print("Buy&Hold: {:+.2f}%".format((df['close'].iloc[-1] / df['close'].iloc[0] - 1)*100))
