# -*- coding: utf-8 -*-
"""
BTDR V3 综合策略回测 v3.1 (修复版)
核心修复: 当日开盘价 = 前一日收盘价，跳空后以跳空价为基准
"""
import sys
import json
import warnings
warnings.filterwarnings('ignore')

from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, "C:/Trading")
DATA_DIR = Path("C:/Trading/data")
OUT_DIR = Path("C:/Trading/research")
OUT_DIR.mkdir(exist_ok=True)

# ====== 加载日线数据 ======
with open(DATA_DIR / "btdr_daily_90d.json", "r") as f:
    daily_raw = json.load(f)
ddf = pd.DataFrame(daily_raw)
ddf['date'] = pd.to_datetime(ddf['date'])
ddf = ddf.sort_values('date').reset_index(drop=True)
ddf['ret'] = ddf['close'].pct_change()
ddf['vol5'] = ddf['ret'].rolling(5).std() * 100
ddf['ma5'] = ddf['close'].rolling(5).mean()
ddf['ma20'] = ddf['close'].rolling(20).mean()
ddf['ema12'] = ddf['close'].ewm(span=12).mean()
ddf['ema26'] = ddf['close'].ewm(span=26).mean()
ddf['macd'] = ddf['ema12'] - ddf['ema26']
ddf['macd_sig'] = ddf['macd'].ewm(span=9).mean()

ddf['trend'] = 0
for i in range(20, len(ddf)):
    m = ddf.loc[i,'ma5'] > ddf.loc[i,'ma20']
    macd_ok = ddf.loc[i,'macd'] > 0
    p = ddf.loc[i,'close'] > ddf.loc[i,'ma20']
    if m and macd_ok and p: ddf.loc[ddf.index[i],'trend'] = 1
    elif not m and not macd_ok and not p: ddf.loc[ddf.index[i],'trend'] = -1

def vol_r(v):
    if pd.isna(v): return 'unknown'
    elif v < 4: return 'low'
    elif v < 7: return 'medium'
    elif v < 10: return 'high'
    else: return 'extreme'
ddf['vol_r'] = ddf['vol5'].apply(vol_r)

# ====== 加载小时K数据 ======
with open(DATA_DIR / "btdr_mins_90d.json", "r") as f:
    mins_raw = json.load(f)

all_bars = []
for date, bars in mins_raw.items():
    for bar in bars:
        all_bars.append({
            'dt': pd.to_datetime(bar['time_key']),
            'date': date,
            'open': bar['open'],
            'high': bar['high'],
            'low': bar['low'],
            'close': bar['close'],
            'volume': bar['volume'],
            'offset': bar['offset']  # 0=开盘小时, 390=收盘小时
        })
df = pd.DataFrame(all_bars).sort_values('dt').reset_index(drop=True)

# ====== 构建每日基准价 ======
# 基准 = 前一日收盘（美股跳空后，以跳空价为基准）
# 构建 prev_close_map
date_to_prev_close = {}
dates = ddf['date'].dt.strftime('%Y-%m-%d').tolist()
closes = ddf['close'].tolist()
for i in range(1, len(dates)):
    date_to_prev_close[dates[i]] = closes[i-1]
# 第一天没有前收盘，用当天开盘
date_to_prev_close[dates[0]] = ddf.loc[0, 'open']

# 当日开盘（第一个小时K的开盘 = 跳空后的开盘价）
first_bar_open = df.groupby('date')['open'].first().to_dict()

# 当日最低/最高（盘中高点/低点）
day_low = df.groupby('date')['low'].min().to_dict()
day_high = df.groupby('date')['high'].max().to_dict()

# 合并
df['prev_close'] = df['date'].map(date_to_prev_close)
df['day_open'] = df['date'].map(lambda d: first_bar_open.get(d, ddf.loc[0,'open']))
df['day_high'] = df['date'].map(day_high)
df['day_low'] = df['date'].map(day_low)

# 合并日线指标
ddf['date_str'] = ddf['date'].dt.strftime('%Y-%m-%d')
df = df.merge(ddf[['date_str','vol5','vol_r','trend']], left_on='date', right_on='date_str', how='left')
df = df.drop('date_str', axis=1)
df['vol5'] = df['vol5'].ffill().bfill()
df['vol_r'] = df['vol_r'].fillna('medium')
df['trend'] = df['trend'].fillna(0)

print(f"Hourly data: {len(df)} bars, {df['date'].nunique()} days")
print(f"Period: {df['dt'].min()} ~ {df['dt'].max()}")

# ====== 回测引擎 v3.1 ======
def backtest(df, params, name="Strategy"):
    BASE = params.get('base_shares', 8894)
    QTY_A = params.get('a_qty', 500)
    QTY_B = params.get('b_qty', 500)
    A_SELL = params.get('a_sell_th', 5.0) / 100.0
    A_BUY = params.get('a_buy_th', 5.0) / 100.0
    B_SELL = params.get('b_sell_th', 5.0) / 100.0
    B_BUY = params.get('b_buy_th', 5.0) / 100.0
    vol_filt = params.get('vol_filter', 'off')
    use_asym = params.get('use_asym', False)
    asym_take = params.get('asym_take', 4.0) / 100.0
    asym_stop = params.get('asym_stop', 2.0) / 100.0
    trend_filt = params.get('trend_filter', False)
    
    # === 涡轮A: 底仓做T ===
    a_sold_qty = 0
    a_proceeds = 0.0
    
    # === 涡轮B: 现金做T ===
    b_qty = 0
    b_cost = 0.0
    b_entry = 0.0
    cash = 50000.0
    
    last_date = None
    equity_list = []
    trades = []
    trade_pnl_a = 0.0
    trade_pnl_b = 0.0
    
    for i, row in df.iterrows():
        if i < 1: 
            last_date = row['date']
            continue
        
        cur_date = row['date']
        price = row['close']
        day_open = row['day_open']
        prev_close = row['prev_close']
        vol_r = row['vol_r']
        trend = row['trend']
        
        # === 每日初始化 ===
        if cur_date != last_date:
            last_date = cur_date
            
            # 涡轮A: 日末强制平仓（没来得及买回则当日买回）
            if a_sold_qty > 0:
                cost = a_sold_qty * price
                if cash >= cost:
                    cash -= cost
                    pnl = a_proceeds - cost
                    trade_pnl_a += pnl
                    trades.append(('BUY_A', str(cur_date), price, a_sold_qty, f'EOD_pnl={pnl:+.0f}'))
                    a_sold_qty = 0
                    a_proceeds = 0.0
            
            # 涡轮B: 日末强制平仓
            if b_qty > 0:
                rev = b_qty * price
                pnl = rev - b_cost
                trade_pnl_b += pnl
                cash += rev
                trades.append(('SELL_B', str(cur_date), price, b_qty, f'EOD_pnl={pnl:+.0f}'))
                b_qty = 0
                b_cost = 0.0
        
        # === 波动率仓位控制 ===
        eff_a = QTY_A
        eff_b = QTY_B
        if vol_filt == 'low_risk':
            if vol_r in ['low', 'extreme']:
                eff_a = int(QTY_A * 0.3)
                eff_b = int(QTY_B * 0.3)
        elif vol_filt == 'medium_only':
            if vol_r not in ['medium', 'high']:
                eff_a = 0
                eff_b = 0
        
        # === 计算当日相对基准的偏离 ===
        # 基准 = 前一日收盘（跳空后开盘）
        day_change = (price - day_open) / day_open if day_open > 0 else 0  # 相对开盘涨跌幅
        day_change_from_prev = (price - prev_close) / prev_close if prev_close > 0 else 0  # 相对昨收涨跌幅
        
        # === 涡轮A: 底仓做T（涨卖，跌买回）===
        # 触发：日内从开盘涨幅 >= A_SELL
        if eff_a > 0 and a_sold_qty == 0:
            if day_change >= A_SELL:
                sqty = min(eff_a, BASE)
                proceeds = sqty * price
                a_sold_qty = sqty
                a_proceeds = proceeds
                trades.append(('SELL_A', str(cur_date), price, sqty, f'dr={day_change*100:+.1f}%'))
        
        elif a_sold_qty > 0:
            # 非对称：价格回落就买回
            if use_asym:
                if day_change <= 0:  # 跌回开盘价就买回（激进）
                    cost = a_sold_qty * price
                    if cash >= cost:
                        cash -= cost
                        pnl = a_proceeds - cost
                        trade_pnl_a += pnl
                        trades.append(('BUY_A', str(cur_date), price, a_sold_qty, f'asym_dr={day_change*100:+.1f}%'))
                        a_sold_qty = 0
                        a_proceeds = 0.0
            else:
                # 固定阈值：涨回来A_BUY就买回
                if day_change <= A_BUY:
                    cost = a_sold_qty * price
                    if cash >= cost:
                        cash -= cost
                        pnl = a_proceeds - cost
                        trade_pnl_a += pnl
                        trades.append(('BUY_A', str(cur_date), price, a_sold_qty, f'fix_dr={day_change*100:+.1f}%'))
                        a_sold_qty = 0
                        a_proceeds = 0.0
        
        # === 涡轮B: 现金做T（跌买，涨卖）===
        # 趋势过滤：下跌趋势不建仓
        if trend_filt and trend == -1:
            if b_qty > 0:
                rev = b_qty * price
                pnl = rev - b_cost
                trade_pnl_b += pnl
                cash += rev
                trades.append(('SELL_B', str(cur_date), price, b_qty, f'trend_pnl={pnl:+.0f}'))
                b_qty = 0
                b_cost = 0.0
            eff_b = 0
        
        if eff_b > 0 and b_qty == 0:
            # 涡轮B建仓：日内从开盘跌幅 >= B_BUY
            if day_change <= -B_BUY:
                budget = min(cash * 0.4, eff_b * price * 2)
                qty = int(budget / price)
                if qty >= 100:
                    cost = qty * price
                    cash -= cost
                    b_qty += qty
                    b_cost += cost
                    b_entry = price
        
        elif b_qty > 0:
            pnl_pct = (price - b_entry) / b_entry if b_entry > 0 else 0
            
            if use_asym:
                if pnl_pct >= asym_take:
                    rev = b_qty * price
                    pnl = rev - b_cost
                    trade_pnl_b += pnl
                    cash += rev
                    trades.append(('SELL_B', str(cur_date), price, b_qty, f'asym_take_pnl={pnl:+.0f}'))
                    b_qty = 0
                    b_cost = 0.0
                    b_entry = 0.0
                elif pnl_pct <= -asym_stop:
                    rev = b_qty * price
                    pnl = rev - b_cost
                    trade_pnl_b += pnl
                    cash += rev
                    trades.append(('SELL_B', str(cur_date), price, b_qty, f'asym_stop_pnl={pnl:+.0f}'))
                    b_qty = 0
                    b_cost = 0.0
                    b_entry = 0.0
            else:
                # 固定：日内从开盘涨幅 >= B_SELL 则止盈
                if day_change >= B_SELL:
                    rev = b_qty * price
                    pnl = rev - b_cost
                    trade_pnl_b += pnl
                    cash += rev
                    trades.append(('SELL_B', str(cur_date), price, b_qty, f'fix_pnl={pnl:+.0f}'))
                    b_qty = 0
                    b_cost = 0.0
                    b_entry = 0.0
        
        # === 权益计算 ===
        base_val = BASE * price
        a_val = -a_sold_qty * price  # 做空部分（欠股票）
        b_val = b_qty * price
        total_val = base_val + a_val + b_val + cash
        turbo_pnl_total = trade_pnl_a + trade_pnl_b
        
        equity_list.append({
            'dt': row['dt'],
            'date': cur_date,
            'price': price,
            'base_val': base_val,
            'a_val': a_val,
            'b_val': b_val,
            'cash': cash,
            'total_val': total_val,
            'turbo_pnl': turbo_pnl_total
        })
    
    # === 绩效 ===
    eq_df = pd.DataFrame(equity_list)
    if len(eq_df) < 2:
        return {'error': 'insufficient data'}
    
    equity = eq_df['total_val'].values
    base_vals = eq_df['base_val'].values
    initial = equity[0]
    final = equity[-1]
    
    total_ret = (final / initial - 1) * 100
    buy_hold_ret = (base_vals[-1] / base_vals[0] - 1) * 100
    turbo_pnl_abs = (final - base_vals[-1]) - (initial - base_vals[0])
    
    returns = np.diff(equity) / equity[:-1]
    returns = np.nan_to_num(returns, nan=0)
    sharpe = returns.mean() / returns.std() * (252**0.5) if returns.std() > 0 else 0
    max_dd = ((equity / np.maximum.accumulate(equity)) - 1).min() * 100
    
    return {
        'name': name,
        'total_return': total_ret,
        'buy_hold': buy_hold_ret,
        'turbo_pnl': turbo_pnl_abs,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'trades': len(trades),
        'trade_list': trades,
        'eq_df': eq_df
    }

# ====== 运行测试 ======
print("\n" + "="*72)
print("V3 Hybrid Backtest v3.1 - Fixed Reference Price")
print("="*72)

results = []

tests = [
    ("1. Buy & Hold (baseline)", {'base_shares':8894,'a_qty':0,'b_qty':0,'vol_filter':'off','use_asym':False,'trend_filter':False}, "Buy&Hold"),
    
    ("2. V2 Original 5%/5% both turbos", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':5,'a_buy_th':5,'b_sell_th':5,'b_buy_th':5,
      'vol_filter':'off','use_asym':False,'trend_filter':False}, "V2 Original"),
    
    ("3. V2 + Asymmetric +4%/-2%", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':5,'a_buy_th':5,'b_sell_th':5,'b_buy_th':5,
      'vol_filter':'off','use_asym':True,'asym_take':4,'asym_stop':2,'trend_filter':False}, "V2+Asym"),
    
    ("4. V2 + Volatility Filter", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':5,'a_buy_th':5,'b_sell_th':5,'b_buy_th':5,
      'vol_filter':'low_risk','use_asym':False,'trend_filter':False}, "V2+Vol"),
    
    ("5. V2 + Trend Filter", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':5,'a_buy_th':5,'b_sell_th':5,'b_buy_th':5,
      'vol_filter':'off','use_asym':False,'trend_filter':True}, "V2+Trend"),
    
    ("6. V2 Full Combo (Vol+Trend+Asym)", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':5,'a_buy_th':5,'b_sell_th':5,'b_buy_th':5,
      'vol_filter':'low_risk','use_asym':True,'asym_take':4,'asym_stop':2,'trend_filter':True}, "V2 Full"),
    
    ("7. Turbo A Only (no B, safer)", 
     {'base_shares':8894,'a_qty':500,'b_qty':0,'a_sell_th':5,'a_buy_th':5,
      'vol_filter':'low_risk','use_asym':True,'asym_take':4,'asym_stop':2,'trend_filter':False}, "TurboA Only"),
    
    ("8. Wider 7%/7% + Full Combo", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':7,'a_buy_th':7,'b_sell_th':7,'b_buy_th':7,
      'vol_filter':'low_risk','use_asym':True,'asym_take':5,'asym_stop':3,'trend_filter':True}, "Wider 7%"),
    
    ("9. Narrower 3%/3% + Full Combo", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':3,'a_buy_th':3,'b_sell_th':3,'b_buy_th':3,
      'vol_filter':'low_risk','use_asym':True,'asym_take':2.5,'asym_stop':1.5,'trend_filter':True}, "Narrow 3%"),
    
    ("10. No stop loss, hold longer", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':5,'a_buy_th':5,'b_sell_th':5,'b_buy_th':5,
      'vol_filter':'low_risk','use_asym':False,'trend_filter':True}, "No Asym"),
    
    ("11. Turbo A 3% / Turbo B 5%", 
     {'base_shares':8894,'a_qty':500,'b_qty':500,'a_sell_th':3,'a_buy_th':3,'b_sell_th':5,'b_buy_th':5,
      'vol_filter':'low_risk','use_asym':True,'asym_take':3,'asym_stop':1.5,'trend_filter':True}, "A3B5"),
]

for desc, params, label in tests:
    print(f"\n{desc}")
    r = backtest(df, params, label)
    results.append(r)
    print(f"  Total: {r['total_return']:+.2f}%  vs B&H: {r['buy_hold']:+.2f}%  TurboPnl: ${r.get('turbo_pnl',0):+.0f}  MaxDD: {r['max_dd']:.2f}%  Trades: {r['trades']}")

# ====== 排名 ======
print("\n" + "="*75)
print("FINAL RANKING (by Total Return)")
print("="*75)

valid = [r for r in results if 'error' not in r]
valid.sort(key=lambda x: x['total_return'], reverse=True)

print(f"\n{'Rank':<5}{'Strategy':<22}{'Total':>10}{'B&H':>10}{'Turbo$':>10}{'Sharpe':>8}{'MaxDD':>10}{'Trds':>6}")
print("-"*80)

for i, r in enumerate(valid):
    delta = r['total_return'] - r['buy_hold']
    flag = "+" if delta > 0 else "-"
    print(f"{i+1:<5}{r['name']:<22}{r['total_return']:>+9.2f}%{r['buy_hold']:>+9.2f}%${r['turbo_pnl']:>+8.0f}{r['sharpe']:>8.2f}{r['max_dd']:>10.2f}%{r['trades']:>6}")

# ====== 涡轮增强贡献 ======
print("\n" + "="*75)
print("Turbo Enhancement vs Buy & Hold")
print("="*75)
bhh = [r for r in valid if r['name']=='Buy&Hold'][0]['buy_hold']
for r in valid:
    delta = r['total_return'] - r['buy_hold']
    if delta > 0:
        print(f"  {r['name']:<22} TURBO OUTPERFORMS B&H by {delta:+.2f}% (Total: {r['total_return']:+.2f}%)")
    else:
        print(f"  {r['name']:<22} TURBO UNDERPERFORMS by {delta:+.2f}% (Total: {r['total_return']:+.2f}%)")

# ====== Top3 交易详情 ======
print("\n" + "="*75)
print("Top3 Strategy - Recent Trade Examples")
print("="*75)
for i in range(min(3, len(valid))):
    r = valid[i]
    trades = r['trade_list']
    # 分析涡轮A和涡轮B分别的盈亏
    a_trades = [t for t in trades if t[0] in ('SELL_A', 'BUY_A', 'CLOSE_A')]
    b_trades = [t for t in trades if t[0] in ('SELL_B', 'BUY_B', 'CLOSE_B')]
    print(f"\n【{r['name']}】 Total: {r['total_return']:+.2f}%")
    print(f"  TurboA trades: {len(a_trades)} | TurboB trades: {len(b_trades)}")
    print(f"  Last 5 trades: {trades[-5:]}")

# ====== 保存 ======
save = {
    'data_range': f"{df['dt'].min()} ~ {df['dt'].max()}",
    'rankings': [{'name':r['name'],'total_return':round(r['total_return'],4),
        'buy_hold':round(r['buy_hold'],4),'turbo_pnl':round(r['turbo_pnl'],2),
        'sharpe':round(r['sharpe'],4),'max_dd':round(r['max_dd'],4),'trades':r['trades']} for r in valid]
}
with open(OUT_DIR / "v3_hybrid_v31_results.json", "w", encoding="utf-8") as f:
    json.dump(save, f, ensure_ascii=False, indent=2)
print(f"\nSaved: research/v3_hybrid_v31_results.json")