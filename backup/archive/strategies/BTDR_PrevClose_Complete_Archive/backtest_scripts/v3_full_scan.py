# -*- coding: utf-8 -*-
"""Full threshold scan - writes results to JSON"""
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
df['bb_width'] = (2 * df['std_20']) / df['ma_20']
df['bb_pos'] = (df['close'] - (df['ma_20'] - df['std_20']*2)) / (df['std_20']*4)
df['vol_ma5'] = df['volume'].rolling(5).mean()
df['vol_ratio_v'] = df['volume'] / df['vol_ma5']
df['gap'] = (df['open'] - df['close'].shift(1)) / df['close'].shift(1)
df['abs_gap'] = df['gap'].abs()
df['price_pos'] = (df['close'] - df['close'].rolling(20).min()) / (df['close'].rolling(20).max() - df['close'].rolling(20).min())

fc = ['returns','log_ret','ma_ratio5','ma_ratio10','ma_ratio20','ma_ratio60',
      'vol_5','vol_20','vol_ratio','rsi','macd','macd_sig','bb_width','bb_pos',
      'vol_ratio_v','gap','abs_gap','price_pos','zscore']
df['fr3'] = df['close'].shift(-3) / df['close'] - 1
df['label'] = 0
df.loc[df['fr3'] > 0.015, 'label'] = 1
df.loc[df['fr3'] < -0.015, 'label'] = -1
dc = df.dropna(subset=fc + ['label'])
Xa = dc[fc].values; ya = dc['label'].values
ts = int(len(dc) * 0.8)
sc = StandardScaler()
Xs = sc.fit_transform(Xa[:ts])
ml = RandomForestClassifier(n_estimators=100, max_depth=6, min_samples_split=10,
                            min_samples_leaf=5, random_state=42, class_weight='balanced')
ml.fit(Xs, ya[:ts])

def bt(st, bt2, bbm, bbp, bbr, som, sop, sor):
    """Run one backtest config. Returns (ret, excess, pnl_A, pnl_B)"""
    pos = 8894; cash = 200000
    tA = [False, 0.0, 0, 0.0, 0.0]  # on, entry, days, prev_close, open
    tB = [False, 0.0, 0, 0.0, 0.0]
    prev = None; pA = 0.0; pB = 0.0
    
    for idx in range(len(df)):
        row = df.iloc[idx]
        price = float(row['close']); op = float(row['open'])
        if prev is None: prev = price; continue
        
        adj_s = st; adj_b = bt2
        fv = []; ok = True
        for c in fc:
            v = row.get(c, np.nan)
            if pd.isna(v) or np.isinf(v): ok = False; break
            fv.append(v)
        if ok:
            X = sc.transform(np.array(fv).reshape(1, -1))
            pred = int(ml.predict(X)[0])
            probs = ml.predict_proba(X)[0]
            if probs.max() > 0.50:
                if pred == 1: adj_s = max(0.02, st - 0.005)
                elif pred == -1: adj_b = max(0.02, bt2 - 0.005)
        
        # Turbo A
        if not tA[0]:
            if price >= prev * (1 + adj_s) and pos > 7000:
                q = min(1000, pos - 7000)
                pos -= q; cash += price * q
                tA = [True, price, 0, prev, op]
        else:
            tA[2] += 1
            bp = None
            if bbm == 'open': bp = tA[4]
            elif bbm == 'prev': bp = tA[3]
            elif bbm == 'pct': bp = tA[3] * (1 + bbp)
            elif bbm == 'retrace': bp = tA[1] * (1 - bbr)
            if bp is not None and price <= bp:
                q = min(1000, int(cash / price))
                if q > 0:
                    pos += q; cash -= price * q
                    pA += (tA[1] - price) * q
                tA = [False, 0.0, 0, 0.0, 0.0]
        
        # Turbo B
        if not tB[0]:
            if price <= prev * (1 - adj_b) and pos < 11000:
                q = min(1000, int(cash / price), 11000 - pos)
                if q > 0:
                    pos += q; cash -= price * q
                    tB = [True, price, 0, prev, op]
        else:
            tB[2] += 1
            sp = None
            if som == 'open': sp = tB[4]
            elif som == 'prev': sp = tB[3]
            elif som == 'pct': sp = tB[3] * (1 + sop)
            elif som == 'retrace': sp = tB[1] * (1 + sor)
            if sp is not None and price >= sp:
                q = min(1000, pos - 7000)
                if q > 0:
                    pos -= q; cash += price * q
                    pB += (price - tB[1]) * q
                tB = [False, 0.0, 0, 0.0, 0.0]
        prev = price
    
    fp = df['close'].iloc[-1]
    fv = pos * fp + cash
    sv = 8894 * df['close'].iloc[0] + 200000
    ret = (fv - sv) / sv
    bh = (fp - df['close'].iloc[0]) / df['close'].iloc[0]
    return round(ret * 100, 2), round((ret - bh) * 100, 2), round(pA), round(pB)

# Run all configs
results = []

# Part A: A buyback strategies (sell=5%, B=retrace5%)
a_modes = [
    ('open', 0, 0), ('prev', 0, 0),
    ('pct', 0.01, 0), ('pct', 0.02, 0), ('pct', 0.03, 0),
    ('pct', -0.01, 0), ('pct', -0.03, 0), ('pct', -0.05, 0),
    ('retrace', 0, 0.02), ('retrace', 0, 0.03), ('retrace', 0, 0.05), ('retrace', 0, 0.07),
]
for bbm, bbp, bbr in a_modes:
    r, e, pa, pb = bt(0.05, 0.05, bbm, bbp, bbr, 'retrace', 0, 0.05)
    results.append({'n': 'A_{}+{}_Br5%'.format(bbm, bbp*100 if bbm=='pct' else bbr*100 if bbm=='retrace' else '0'),
                    'r': r, 'e': e, 'pa': pa, 'pb': pb, 'st': 5, 'bt': 5})

# Part B: B sellout strategies (sell=5%, A=pct+3%, B varies)
# Best A from Part A was pct+3%
b_modes = [
    ('open', 0, 0), ('prev', 0, 0),
    ('pct', -0.01, 0), ('pct', -0.02, 0), ('pct', -0.03, 0),
    ('pct', 0.01, 0), ('pct', 0.03, 0), ('pct', 0.05, 0),
    ('retrace', 0, 0.02), ('retrace', 0, 0.03), ('retrace', 0, 0.05), ('retrace', 0, 0.07),
]
for som, sop, sor in b_modes:
    r, e, pa, pb = bt(0.05, 0.05, 'pct', 0.03, 0, som, sop, sor)
    results.append({'n': 'A+3%_B_{}+{}'.format(som, sop*100 if som=='pct' else sor*100 if som=='retrace' else '0'),
                    'r': r, 'e': e, 'pa': pa, 'pb': pb, 'st': 5, 'bt': 5})

# Part C: Different triggers with best A(pct+3%) B(retrace2%)
for sp in [2, 3, 4, 5, 6]:
    for bp in [2, 3, 4, 5, 6]:
        r, e, pa, pb = bt(sp/100, bp/100, 'pct', 0.03, 0, 'retrace', 0, 0.02)
        results.append({'n': 'S{}B{}_A+3%_Br2%'.format(sp, bp), 'r': r, 'e': e, 'pa': pa, 'pb': pb, 'st': sp, 'bt': bp})

# Part D: Fine-tuning all combos
fine = [
    (5, 5, 'pct', 0.03, 0, 'retrace', 0, 0.02, '5+5_A+3%_Br2%'),
    (5, 5, 'pct', 0.03, 0, 'retrace', 0, 0.03, '5+5_A+3%_Br3%'),
    (5, 5, 'pct', 0.02, 0, 'retrace', 0, 0.02, '5+5_A+2%_Br2%'),
    (5, 5, 'pct', 0.02, 0, 'pct', -0.02, 0, '5+5_A+2%_B-2%'),
    (5, 5, 'pct', 0.01, 0, 'pct', -0.01, 0, '5+5_A+1%_B-1%'),
    (5, 5, 'pct', 0.03, 0, 'pct', -0.02, 0, '5+5_A+3%_B-2%'),
    (5, 5, 'pct', 0.03, 0, 'pct', -0.03, 0, '5+5_A+3%_B-3%'),
    (5, 5, 'open', 0, 0, 'retrace', 0, 0.02, '5+5_Aop_Br2%'),
    (5, 5, 'open', 0, 0, 'open', 0, 0, '5+5_Aop_Bop'),
    (5, 5, 'prev', 0, 0, 'prev', 0, 0, '5+5_Apv_Bpv'),
    (4, 5, 'pct', 0.03, 0, 'retrace', 0, 0.02, '4+5_A+3%_Br2%'),
    (5, 4, 'pct', 0.03, 0, 'retrace', 0, 0.02, '5+4_A+3%_Br2%'),
    (3, 5, 'pct', 0.02, 0, 'retrace', 0, 0.02, '3+5_A+2%_Br2%'),
    (5, 3, 'pct', 0.03, 0, 'pct', -0.01, 0, '5+3_A+3%_B-1%'),
    (3, 3, 'pct', 0.01, 0, 'pct', -0.01, 0, '3+3_A+1%_B-1%'),
    (3, 3, 'retrace', 0, 0.02, 'retrace', 0, 0.02, '3+3_Ar2%_Br2%'),
    (4, 4, 'pct', 0.02, 0, 'retrace', 0, 0.02, '4+4_A+2%_Br2%'),
    (4, 4, 'pct', 0.03, 0, 'pct', -0.02, 0, '4+4_A+3%_B-2%'),
    (5, 5, 'retrace', 0, 0.05, 'retrace', 0, 0.05, 'ORIG_5+5'),
]

for sp, bp, bbm, bbp, bbr, som, sop, sor, name in fine:
    r, e, pa, pb = bt(sp/100, bp/100, bbm, bbp, bbr, som, sop, sor)
    results.append({'n': name, 'r': r, 'e': e, 'pa': pa, 'pb': pb, 'st': sp, 'bt': bp})

# Sort and save
results.sort(key=lambda x: x['r'], reverse=True)

with open(DATA_DIR / "v3_threshold_full.json", 'w') as f:
    json.dump(results, f, indent=2)

# Print top 20
print("TOP 20 Strategies:")
print("{:<25} {:>9} {:>9} {:>10} {:>10}".format('Strategy', 'Return', 'Excess', 'A_PnL', 'B_PnL'))
print("-" * 65)
for r in results[:20]:
    print("{:<25} {:>+8.2f}% {:>+8.2f}% {:>10} {:>10}".format(
        r['n'], r['r'], r['e'], r['pa'], r['pb']))

bh = (df['close'].iloc[-1] / df['close'].iloc[0] - 1) * 100
print("\nBuy&Hold: {:+.2f}%".format(bh))
print("Total configs tested: {}".format(len(results)))
