# -*- coding: utf-8 -*-
"""Part C+D: Trigger and combo optimization with best A/B params"""
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

# Indicators (same as before)
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
    prev = None; pA = 0; pB = 0
    
    for idx in range(len(df)):
        row = df.iloc[idx]
        price = row['close']; op = row['open']
        if prev is None: prev = price; continue
        
        adj_s = sell_trig; adj_b = buy_trig
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
        
        if not tA['on']:
            if price >= prev * (1 + adj_s) and position > min_s:
                q = min(qty, position - min_s)
                position -= q; cash += price * q
                tA = {'on': True, 'e': price, 'd': 0, 'pc': prev, 'op': op}
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
                    pA += (tA['e'] - price) * q
                tA = {'on': False, 'e': 0, 'd': 0, 'pc': 0, 'op': 0}
        
        if not tB['on']:
            if price <= prev * (1 - adj_b) and position < max_s:
                q = min(qty, int(cash / price), max_s - position)
                if q > 0:
                    position += q; cash -= price * q
                    tB = {'on': True, 'e': price, 'd': 0, 'pc': prev, 'op': op}
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
                    pB += (price - tB['e']) * q
                tB = {'on': False, 'e': 0, 'd': 0, 'pc': 0, 'op': 0}
        prev = price
    
    fp = df['close'].iloc[-1]; fv = position * fp + cash
    sp2 = df['close'].iloc[0]; sv = 8894 * sp2 + 200000
    ret = (fv - sv) / sv; bh = (fp - sp2) / sp2
    return {'name': name, 'ret': ret, 'excess': ret - bh, 'pnl': pA + pB, 'pnl_A': pA, 'pnl_B': pB}

# Based on Part A result: Best A buyback = pct +3% (buyback when price returns to prev_close+3%)
# Based on Part B result: Best B sellout = retrace 2% (sell when price rises 2% from entry)
# BUT Part B used a_bb from Part A best = pct+3%, and B's own best was retrace_00.02

print("=" * 80)
print("PART C: Trigger Threshold x Best A(pct+3%) x B(retrace2%)")
print("=" * 80)

resC = []
for sp in [2, 3, 4, 5, 6]:
    for bp in [2, 3, 4, 5, 6]:
        n = "S{}B{}_A+3%_Br2%".format(sp, bp)
        r = run_bt(sp/100, bp/100, 'pct', 0.03, 0, 'retrace', 0, 0.02, n)
        resC.append(r)
        print("  {}: Ret={:+.2f}% Excess={:+.2f}% PnL=${:,.0f}(A${:,.0f} B${:,.0f})".format(
            n, r['ret']*100, r['excess']*100, r['pnl'], r['pnl_A'], r['pnl_B']))

print("\n" + "=" * 80)
print("PART D: All Combos Fine-tuning")
print("=" * 80)

# Now test the most interesting combos with different A/B exit strategies
configs = [
    # Format: (sell%, buy%, bb_mode, bb_pct, bb_retrace, so_mode, so_pct, so_retrace, name)
    # ---- A: sell+5%, buyback=+3% (Part A best) ----
    (5, 5, 'pct', 0.03, 0, 'retrace', 0, 0.02, '5+5_A+3%_Br2%'),
    (5, 5, 'pct', 0.03, 0, 'retrace', 0, 0.03, '5+5_A+3%_Br3%'),
    (5, 5, 'pct', 0.03, 0, 'pct', -0.02, 0, '5+5_A+3%_B-2%'),
    (5, 5, 'pct', 0.03, 0, 'pct', -0.03, 0, '5+5_A+3%_B-3%'),
    # ---- A: sell+5%, buyback=+2% ----
    (5, 5, 'pct', 0.02, 0, 'retrace', 0, 0.02, '5+5_A+2%_Br2%'),
    (5, 5, 'pct', 0.02, 0, 'pct', -0.02, 0, '5+5_A+2%_B-2%'),
    # ---- A: sell+5%, buyback=open ----
    (5, 5, 'open', 0, 0, 'retrace', 0, 0.02, '5+5_Aopen_Br2%'),
    (5, 5, 'open', 0, 0, 'open', 0, 0, '5+5_Aopen_Bopen'),
    # ---- A: sell+5%, buyback=prev_close ----
    (5, 5, 'prev', 0, 0, 'prev', 0, 0, '5+5_Aprev_Bprev'),
    # ---- Asymmetric triggers ----
    (4, 5, 'pct', 0.03, 0, 'retrace', 0, 0.02, '4+5_A+3%_Br2%'),
    (5, 4, 'pct', 0.03, 0, 'retrace', 0, 0.02, '5+4_A+3%_Br2%'),
    (3, 5, 'pct', 0.02, 0, 'retrace', 0, 0.02, '3+5_A+2%_Br2%'),
    (5, 3, 'pct', 0.03, 0, 'pct', -0.01, 0, '5+3_A+3%_B-1%'),
    # ---- Tighter: 3% trigger ----
    (3, 3, 'pct', 0.01, 0, 'pct', -0.01, 0, '3+3_A+1%_B-1%'),
    (3, 3, 'pct', 0.02, 0, 'retrace', 0, 0.02, '3+3_A+2%_Br2%'),
    (3, 3, 'retrace', 0, 0.02, 'retrace', 0, 0.02, '3+3_Ar2%_Br2%'),
    # ---- 4% trigger ----
    (4, 4, 'pct', 0.02, 0, 'retrace', 0, 0.02, '4+4_A+2%_Br2%'),
    (4, 4, 'pct', 0.03, 0, 'pct', -0.02, 0, '4+4_A+3%_B-2%'),
    # ---- Original V3 (5% symmetric, retrace 5%) ----
    (5, 5, 'retrace', 0, 0.05, 'retrace', 0, 0.05, 'ORIG_5+5_Ar5%_Br5%'),
]

resD = []
for sp, bp, bb_m, bb_p, bb_r, so_m, so_p, so_r, name in configs:
    r = run_bt(sp/100, bp/100, bb_m, bb_p, bb_r, so_m, so_p, so_r, name)
    resD.append(r)
    print("  {}: Ret={:+.2f}% Excess={:+.2f}% PnL=${:,.0f}(A${:,.0f} B${:,.0f})".format(
        name, r['ret']*100, r['excess']*100, r['pnl'], r['pnl_A'], r['pnl_B']))

# ============ FINAL RANKING ============
all_res = resC + resD
all_sorted = sorted(all_res, key=lambda x: x['ret'], reverse=True)

print("\n" + "=" * 80)
print("FINAL TOP 20 (from Parts C+D)")
print("=" * 80)
print("{:<25} {:>9} {:>9} {:>10} {:>10} {:>10}".format(
    'Strategy', 'Return', 'Excess', 'TotalPnL', 'A_PnL', 'B_PnL'))
print("-" * 75)
for r in all_sorted[:20]:
    print("{:<25} {:>+8.2f}% {:>+8.2f}% ${:>9,.0f} ${:>9,.0f} ${:>9,.0f}".format(
        r['name'], r['ret']*100, r['excess']*100, r['pnl'], r['pnl_A'], r['pnl_B']))

# Combine with Part A/B results from previous run
prev_results = [
    {'name': 'A_bb=pct_0.030', 'ret': -0.0197, 'excess': 0.1009, 'pnl': 22495, 'pnl_A': 11145, 'pnl_B': 11350},
    {'name': 'B_so=retrace_0.02', 'ret': -0.0095, 'excess': 0.1111, 'pnl': 19630, 'pnl_A': 10280, 'pnl_B': 9350},
]
all_with_prev = all_sorted + prev_results
all_with_prev.sort(key=lambda x: x['ret'], reverse=True)

print("\n" + "=" * 80)
print("COMPLETE TOP 15 (all parts combined)")
print("=" * 80)
for r in all_with_prev[:15]:
    print("{:<25} {:>+8.2f}% {:>+8.2f}% ${:>9,.0f}".format(
        r['name'], r['ret']*100, r['excess']*100, r['pnl']))

# Save
with open(DATA_DIR / "v3_threshold_final.json", 'w') as f:
    json.dump(all_sorted, f, indent=2, default=str)

bh = (df['close'].iloc[-1] / df['close'].iloc[0] - 1)
print("\nBuy&Hold: {:+.2f}%".format(bh*100))
