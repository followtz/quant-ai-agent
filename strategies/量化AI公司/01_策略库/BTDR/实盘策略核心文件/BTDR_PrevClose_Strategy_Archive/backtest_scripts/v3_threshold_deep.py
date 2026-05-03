# -*- coding: utf-8 -*-
"""
BTDR V3 触发阈值深度优化
基础路线: 5%+ML(0.50)

核心思路: 解耦卖出触发价与买回触发价、买入触发价与卖出触发价

涡轮A (先卖后买):
  - 卖出触发: price >= prev_close * (1 + sell_trigger%)
  - 买回触发: 多种策略
    a) 回落至开盘价 (当日open)
    b) 回落至 prev_close * (1 + X%)  (部分回撤)
    c) 回落至 prev_close * (1 - X%)  (完全反转)
    d) 相对entry回落Y%

涡轮B (先买后卖):
  - 买入触发: price <= prev_close * (1 - buy_trigger%)
  - 卖出触发: 多种策略
    a) 反弹至开盘价
    b) 反弹至 prev_close * (1 - X%)  (部分反弹)
    c) 反弹至 prev_close * (1 + X%)  (完全反转)
    d) 相对entry上涨Y%
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import TimeSeriesSplit
import warnings
warnings.filterwarnings('ignore')

DATA_DIR = Path("C:/Trading/data")

# ============ 1. 加载数据 ============
print("=" * 80)
print("BTDR V3 Trigger Threshold Deep Optimization")
print("Base: 5%+ML(0.50)")
print("=" * 80)

with open(DATA_DIR / "btdr_daily_360d.json", 'r') as f:
    daily_data = json.load(f)

df = pd.DataFrame(daily_data)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
for col in ['open', 'high', 'low', 'close', 'volume']:
    df[col] = df[col].astype(float)

print("Data: {} days, {} ~ {}".format(
    len(df), df['date'].iloc[0].strftime('%Y-%m-%d'), df['date'].iloc[-1].strftime('%Y-%m-%d')
))
print("Price: ${:.2f} - ${:.2f}".format(df['close'].min(), df['close'].max()))

# ============ 2. 计算指标 + 训练ML ============
def calc_indicators(df):
    df = df.copy()
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
    df['price_pos'] = (df['close'] - df['close'].rolling(20).min()) / \
                      (df['close'].rolling(20).max() - df['close'].rolling(20).min())
    return df

df = calc_indicators(df)

# ML
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

ml_model = RandomForestClassifier(
    n_estimators=100, max_depth=6, min_samples_split=10,
    min_samples_leaf=5, random_state=42, class_weight='balanced'
)
ml_model.fit(X_train_scaled, y_all[:train_size])
print("ML trained: {} samples".format(len(df_clean)))

# ============ 3. 回测引擎 ============
def run_backtest_decoupled(df, config):
    """
    解耦触发阈值回测
    
    config:
      sell_trigger: 涡轮A卖出触发 (e.g. 0.05 = 5%)
      buyback_mode: 买回模式
        'open' - 回落至当日开盘价
        'pct' - 回落至 prev_close*(1+buyback_pct) 
        'retrace' - 相对entry回落retrace_pct
      buyback_pct: 买回百分比 (for 'pct' mode, e.g. 0.02 = +2%)
      retrace_pct: 回撤百分比 (for 'retrace' mode, e.g. 0.03 = 3%)
      
      buy_trigger: 涡轮B买入触发 (e.g. 0.05 = 5%)
      sellout_mode: 卖出模式 (same options as buyback)
      sellout_pct: 卖出百分比
      sellout_retrace: 卖出回撤百分比
      
      use_ml: bool
      ml_confidence: float
      use_dynamic_threshold: bool
    """
    position = 8894
    cash = 200000
    min_shares = 7000
    max_shares = 11000
    trade_qty = 1000
    
    sell_trig = config['sell_trigger']
    buy_trig = config['buy_trigger']
    buyback_mode = config.get('buyback_mode', 'pct')
    buyback_pct = config.get('buyback_pct', 0.0)
    retrace_pct = config.get('retrace_pct', 0.03)
    sellout_mode = config.get('sellout_mode', 'pct')
    sellout_pct = config.get('sellout_pct', 0.0)
    sellout_retrace = config.get('sellout_retrace', 0.03)
    
    use_ml = config.get('use_ml', False)
    ml_conf = config.get('ml_confidence', 0.50)
    
    trades = []
    tA = {'active': False, 'entry': 0, 'days': 0, 'prev_close': 0, 'open': 0}
    tB = {'active': False, 'entry': 0, 'days': 0, 'prev_close': 0, 'open': 0}
    
    prev_close = None
    total_pnl_A = 0
    total_pnl_B = 0
    
    for idx in range(len(df)):
        row = df.iloc[idx]
        price = row['close']
        open_price = row['open']
        date = row['date']
        
        if prev_close is None:
            prev_close = price
            continue
        
        # ML动态阈值调整
        ml_adjustment = 0
        if use_ml:
            feat_vals = []
            valid = True
            for col in feature_cols:
                val = row.get(col, np.nan)
                if pd.isna(val) or np.isinf(val):
                    valid = False
                    break
                feat_vals.append(val)
            if valid:
                X = scaler.transform(np.array(feat_vals).reshape(1, -1))
                pred = int(ml_model.predict(X)[0])
                probs = ml_model.predict_proba(X)[0]
                classes = list(ml_model.classes_)
                max_prob = probs.max()
                if max_prob > ml_conf:
                    if pred == 1:   # 看涨
                        ml_adjustment = -0.005  # 收紧卖出阈值
                    elif pred == -1: # 看跌
                        ml_adjustment = -0.005  # 收紧买入阈值
        
        adj_sell = sell_trig + ml_adjustment
        adj_buy = buy_trig + ml_adjustment
        adj_sell = max(0.02, min(0.07, adj_sell))
        adj_buy = max(0.02, min(0.07, adj_buy))
        
        # ====== 涡轮A: 先卖后买 ======
        if not tA['active']:
            # 卖出触发
            if price >= prev_close * (1 + adj_sell) and position > min_shares:
                qty = min(trade_qty, position - min_shares)
                position -= qty
                cash += price * qty
                tA = {
                    'active': True, 'entry': price, 'days': 0,
                    'prev_close': prev_close, 'open': open_price
                }
                trades.append({
                    'date': str(date)[:10], 'turbo': 'A', 'action': 'sell',
                    'price': price, 'qty': qty, 'trigger': '+{:.1f}%'.format(sell_trig*100)
                })
        else:
            tA['days'] += 1
            # 买回触发
            buyback_price = None
            
            if buyback_mode == 'open':
                # 回落至开盘价
                buyback_price = tA['open']
            elif buyback_mode == 'pct':
                # 回落至 prev_close * (1 + buyback_pct)
                buyback_price = tA['prev_close'] * (1 + buyback_pct)
            elif buyback_mode == 'retrace':
                # 相对entry回落retrace_pct
                buyback_price = tA['entry'] * (1 - retrace_pct)
            elif buyback_mode == 'prev_close':
                # 回落至前日收盘价
                buyback_price = tA['prev_close']
            
            if buyback_price is not None and price <= buyback_price:
                qty = min(trade_qty, int(cash / price))
                if qty > 0:
                    position += qty
                    cash -= price * qty
                    pnl = (tA['entry'] - price) * qty
                    total_pnl_A += pnl
                    trades.append({
                        'date': str(date)[:10], 'turbo': 'A', 'action': 'buy',
                        'price': price, 'qty': qty, 'pnl': pnl,
                        'hold_days': tA['days'],
                        'buyback_mode': buyback_mode,
                        'spread': (tA['entry'] - price) / tA['entry'] * 100
                    })
                tA = {'active': False, 'entry': 0, 'days': 0, 'prev_close': 0, 'open': 0}
        
        # ====== 涡轮B: 先买后卖 ======
        if not tB['active']:
            # 买入触发
            if price <= prev_close * (1 - adj_buy) and position < max_shares:
                qty = min(trade_qty, int(cash / price), max_shares - position)
                if qty > 0:
                    position += qty
                    cash -= price * qty
                    tB = {
                        'active': True, 'entry': price, 'days': 0,
                        'prev_close': prev_close, 'open': open_price
                    }
                    trades.append({
                        'date': str(date)[:10], 'turbo': 'B', 'action': 'buy',
                        'price': price, 'qty': qty, 'trigger': '-{:.1f}%'.format(buy_trig*100)
                    })
        else:
            tB['days'] += 1
            # 卖出触发
            sellout_price = None
            
            if sellout_mode == 'open':
                # 反弹至开盘价
                sellout_price = tB['open']
            elif sellout_mode == 'pct':
                # 反弹至 prev_close * (1 - sellout_pct)
                sellout_price = tB['prev_close'] * (1 - sellout_pct)
            elif sellout_mode == 'retrace':
                # 相对entry上涨sellout_retrace
                sellout_price = tB['entry'] * (1 + sellout_retrace)
            elif sellout_mode == 'prev_close':
                # 反弹至前日收盘价
                sellout_price = tB['prev_close']
            
            if sellout_price is not None and price >= sellout_price:
                qty = min(trade_qty, position - min_shares)
                if qty > 0:
                    position -= qty
                    cash += price * qty
                    pnl = (price - tB['entry']) * qty
                    total_pnl_B += pnl
                    trades.append({
                        'date': str(date)[:10], 'turbo': 'B', 'action': 'sell',
                        'price': price, 'qty': qty, 'pnl': pnl,
                        'hold_days': tB['days'],
                        'sellout_mode': sellout_mode,
                        'spread': (price - tB['entry']) / tB['entry'] * 100
                    })
                tB = {'active': False, 'entry': 0, 'days': 0, 'prev_close': 0, 'open': 0}
        
        prev_close = price
    
    # 统计
    final_price = df['close'].iloc[-1]
    final_value = position * final_price + cash
    start_price = df['close'].iloc[0]
    start_value = 8894 * start_price + 200000
    total_return = (final_value - start_value) / start_value
    buyhold_return = (final_price - start_price) / start_price
    excess_return = total_return - buyhold_return
    
    completed = [t for t in trades if 'pnl' in t]
    total_pnl = sum(t['pnl'] for t in completed)
    wins = sum(1 for t in completed if t['pnl'] > 0)
    win_rate = wins / len(completed) * 100 if completed else 0
    
    # 分涡轮统计
    tA_trades = [t for t in completed if t['turbo'] == 'A']
    tB_trades = [t for t in completed if t['turbo'] == 'B']
    
    avg_spread_A = np.mean([t['spread'] for t in tA_trades]) if tA_trades else 0
    avg_spread_B = np.mean([t['spread'] for t in tB_trades]) if tB_trades else 0
    avg_hold_A = np.mean([t['hold_days'] for t in tA_trades]) if tA_trades else 0
    avg_hold_B = np.mean([t['hold_days'] for t in tB_trades]) if tB_trades else 0
    
    return {
        'strategy': config.get('strategy_name', 'unknown'),
        'total_return': total_return,
        'excess_return': excess_return,
        'buyhold_return': buyhold_return,
        'total_pnl': total_pnl,
        'pnl_A': total_pnl_A,
        'pnl_B': total_pnl_B,
        'trades': len(trades),
        'completed': len(completed),
        'trades_A': len(tA_trades),
        'trades_B': len(tB_trades),
        'win_rate': win_rate,
        'avg_spread_A': avg_spread_A,
        'avg_spread_B': avg_spread_B,
        'avg_hold_A': avg_hold_A,
        'avg_hold_B': avg_hold_B,
        'final_position': position,
        'final_cash': cash,
        'final_value': final_value,
    }


# ============ 4. 运行全面测试 ============
results = []

# ---- Part A: 涡轮A买回策略 ----
print("\n" + "=" * 80)
print("PART A: Turbo A Buy-back Strategy (Sell trigger=5%)")
print("=" * 80)

sell_trigger = 0.05

# A1: 买回=开盘价
configs_A = [
    # (mode, description, params)
    ('open', 'A:Sell+5%,Buyback=Open', {'buyback_pct': 0, 'retrace_pct': 0}),
    ('prev_close', 'A:Sell+5%,Buyback=PrevClose', {'buyback_pct': 0, 'retrace_pct': 0}),
    ('pct', 'A:Sell+5%,Buyback=+1%', {'buyback_pct': 0.01, 'retrace_pct': 0}),
    ('pct', 'A:Sell+5%,Buyback=+2%', {'buyback_pct': 0.02, 'retrace_pct': 0}),
    ('pct', 'A:Sell+5%,Buyback=+3%', {'buyback_pct': 0.03, 'retrace_pct': 0}),
    ('pct', 'A:Sell+5%,Buyback=-1%', {'buyback_pct': -0.01, 'retrace_pct': 0}),
    ('pct', 'A:Sell+5%,Buyback=-3%', {'buyback_pct': -0.03, 'retrace_pct': 0}),
    ('pct', 'A:Sell+5%,Buyback=-5%', {'buyback_pct': -0.05, 'retrace_pct': 0}),
    ('retrace', 'A:Sell+5%,Buyback=retrace2%', {'buyback_pct': 0, 'retrace_pct': 0.02}),
    ('retrace', 'A:Sell+5%,Buyback=retrace3%', {'buyback_pct': 0, 'retrace_pct': 0.03}),
    ('retrace', 'A:Sell+5%,Buyback=retrace5%', {'buyback_pct': 0, 'retrace_pct': 0.05}),
    ('retrace', 'A:Sell+5%,Buyback=retrace7%', {'buyback_pct': 0, 'retrace_pct': 0.07}),
]

# 涡轮B用默认5%对称逻辑
for mode, name, params in configs_A:
    cfg = {
        'strategy_name': name,
        'sell_trigger': sell_trigger,
        'buyback_mode': mode,
        'buyback_pct': params['buyback_pct'],
        'retrace_pct': params['retrace_pct'],
        'buy_trigger': 0.05,
        'sellout_mode': 'retrace',
        'sellout_pct': 0,
        'sellout_retrace': 0.05,
        'use_ml': True,
        'ml_confidence': 0.50,
    }
    r = run_backtest_decoupled(df, cfg)
    results.append(r)
    print("  {}: Ret={:+.2f}%, Excess={:+.2f}%, A_PnL=${:,.0f}({:d}t,avg{:.1f}%spread,{:.0f}d), B_PnL=${:,.0f}({:d}t)".format(
        name, r['total_return']*100, r['excess_return']*100,
        r['pnl_A'], r['trades_A'], r['avg_spread_A'], r['avg_hold_A'],
        r['pnl_B'], r['trades_B']
    ))

# ---- Part B: 涡轮B卖出策略 ----
print("\n" + "=" * 80)
print("PART B: Turbo B Sell-out Strategy (Buy trigger=5%)")
print("=" * 80)

buy_trigger = 0.05
# 涡轮A用最优结果（先暂用retrace5%）
best_A_mode = 'retrace'
best_A_retrace = 0.05

configs_B = [
    ('open', 'B:Buy-5%,Sellout=Open', {'sellout_pct': 0, 'sellout_retrace': 0}),
    ('prev_close', 'B:Buy-5%,Sellout=PrevClose', {'sellout_pct': 0, 'sellout_retrace': 0}),
    ('pct', 'B:Buy-5%,Sellout=-1%', {'sellout_pct': -0.01, 'sellout_retrace': 0}),
    ('pct', 'B:Buy-5%,Sellout=-2%', {'sellout_pct': -0.02, 'sellout_retrace': 0}),
    ('pct', 'B:Buy-5%,Sellout=-3%', {'sellout_pct': -0.03, 'sellout_retrace': 0}),
    ('pct', 'B:Buy-5%,Sellout=+1%', {'sellout_pct': 0.01, 'sellout_retrace': 0}),
    ('pct', 'B:Buy-5%,Sellout=+3%', {'sellout_pct': 0.03, 'sellout_retrace': 0}),
    ('pct', 'B:Buy-5%,Sellout=+5%', {'sellout_pct': 0.05, 'sellout_retrace': 0}),
    ('retrace', 'B:Buy-5%,Sellout=retrace2%', {'sellout_pct': 0, 'sellout_retrace': 0.02}),
    ('retrace', 'B:Buy-5%,Sellout=retrace3%', {'sellout_pct': 0, 'sellout_retrace': 0.03}),
    ('retrace', 'B:Buy-5%,Sellout=retrace5%', {'sellout_pct': 0, 'sellout_retrace': 0.05}),
    ('retrace', 'B:Buy-5%,Sellout=retrace7%', {'sellout_pct': 0, 'sellout_retrace': 0.07}),
]

for mode, name, params in configs_B:
    cfg = {
        'strategy_name': name,
        'sell_trigger': sell_trigger,
        'buyback_mode': best_A_mode,
        'buyback_pct': 0,
        'retrace_pct': best_A_retrace,
        'buy_trigger': buy_trigger,
        'sellout_mode': mode,
        'sellout_pct': params['sellout_pct'],
        'sellout_retrace': params['sellout_retrace'],
        'use_ml': True,
        'ml_confidence': 0.50,
    }
    r = run_backtest_decoupled(df, cfg)
    results.append(r)
    print("  {}: Ret={:+.2f}%, Excess={:+.2f}%, A_PnL=${:,.0f}({:d}t), B_PnL=${:,.0f}({:d}t,avg{:.1f}%spread,{:.0f}d)".format(
        name, r['total_return']*100, r['excess_return']*100,
        r['pnl_A'], r['trades_A'],
        r['pnl_B'], r['trades_B'], r['avg_spread_B'], r['avg_hold_B']
    ))

# ---- Part C: 不同卖出触发阈值 × 最优买回策略 ----
print("\n" + "=" * 80)
print("PART C: Sell Trigger Scan x Best Buyback")
print("=" * 80)

# 用Part A/B找出的最优模式，扫描不同触发阈值
for sell_pct in [3, 4, 5, 6]:
    for buy_pct in [3, 4, 5, 6]:
        for bb_mode in ['pct', 'retrace']:
            for so_mode in ['pct', 'retrace']:
                # 选几个关键参数组合
                bb_pct_val = 0.02 if bb_mode == 'pct' else 0
                bb_retrace = 0.03 if bb_mode == 'retrace' else 0
                so_pct_val = -0.02 if so_mode == 'pct' else 0
                so_retrace = 0.03 if so_mode == 'retrace' else 0
                
                cfg = {
                    'strategy_name': 'S{}%B{}%_{}{}_{}{}'.format(
                        sell_pct, buy_pct,
                        bb_mode[0].upper(), '2%' if bb_mode=='pct' else '3%',
                        so_mode[0].upper(), '2%' if so_mode=='pct' else '3%'
                    ),
                    'sell_trigger': sell_pct / 100.0,
                    'buyback_mode': bb_mode,
                    'buyback_pct': bb_pct_val,
                    'retrace_pct': bb_retrace,
                    'buy_trigger': buy_pct / 100.0,
                    'sellout_mode': so_mode,
                    'sellout_pct': so_pct_val,
                    'sellout_retrace': so_retrace,
                    'use_ml': True,
                    'ml_confidence': 0.50,
                }
                r = run_backtest_decoupled(df, cfg)
                results.append(r)

# 只打印收益最高的几个
print("\n--- Top 10 combos from Part C ---")
part_c = results[len(configs_A) + len(configs_B):]
part_c_sorted = sorted(part_c, key=lambda x: x['total_return'], reverse=True)
for r in part_c_sorted[:10]:
    print("  {}: Ret={:+.2f}%, Excess={:+.2f}%, A=${:,.0f}({:d}t), B=${:,.0f}({:d}t)".format(
        r['strategy'], r['total_return']*100, r['excess_return']*100,
        r['pnl_A'], r['trades_A'], r['pnl_B'], r['trades_B']
    ))

# ---- Part D: 最优组合精调 ----
print("\n" + "=" * 80)
print("PART D: Fine-tuning Best Combos")
print("=" * 80)

# 基于前面的结果，精调最有前景的参数
fine_tune_configs = [
    # (sell%, buy%, buyback_mode, buyback_param, sellout_mode, sellout_param)
    (5, 5, 'pct', 0.02, 'pct', -0.02),    # A:+2%买回, B:-2%卖出
    (5, 5, 'pct', 0.02, 'retrace', 0.03),  # A:+2%买回, B:retrace3%
    (5, 5, 'retrace', 0.03, 'pct', -0.02), # A:retrace3%, B:-2%卖出
    (5, 5, 'retrace', 0.03, 'retrace', 0.03), # 双retrace3%
    (5, 5, 'pct', 0.01, 'pct', -0.01),     # 更紧密: A:+1%, B:-1%
    (5, 5, 'pct', 0.03, 'pct', -0.03),     # 更宽松: A:+3%, B:-3%
    (4, 4, 'pct', 0.02, 'pct', -0.02),     # 4%触发
    (4, 4, 'retrace', 0.03, 'retrace', 0.03),
    (3, 3, 'pct', 0.01, 'pct', -0.01),     # 3%触发
    (3, 3, 'retrace', 0.02, 'retrace', 0.02),
    (5, 5, 'open', 0, 'open', 0),           # 双Open
    (5, 5, 'prev_close', 0, 'prev_close', 0), # 双PrevClose
    (4, 5, 'pct', 0.02, 'retrace', 0.03),   # 不对称: A4%B5%
    (5, 4, 'pct', 0.02, 'retrace', 0.03),   # 不对称: A5%B4%
    (3, 5, 'pct', 0.01, 'retrace', 0.03),   # 不对称: A3%B5%
    (5, 3, 'retrace', 0.03, 'pct', -0.01),  # 不对称: A5%B3%
]

for params in fine_tune_configs:
    sp, bp, bb_m, bb_p, so_m, so_p = params
    cfg = {
        'strategy_name': 'Fine:S{}B{}_{}{}_{}{}'.format(
            sp, bp,
            bb_m[:3], '{:.0f}%'.format(bb_p*100) if bb_m=='pct' else '{:.0f}%'.format(bb_p*100),
            so_m[:3], '{:.0f}%'.format(so_p*100) if so_m=='pct' else '{:.0f}%'.format(so_p*100)
        ),
        'sell_trigger': sp / 100.0,
        'buyback_mode': bb_m,
        'buyback_pct': bb_p,
        'retrace_pct': bb_p,
        'buy_trigger': bp / 100.0,
        'sellout_mode': so_m,
        'sellout_pct': so_p,
        'sellout_retrace': so_p,
        'use_ml': True,
        'ml_confidence': 0.50,
    }
    r = run_backtest_decoupled(df, cfg)
    results.append(r)
    print("  {}: Ret={:+.2f}%, Excess={:+.2f}%, A=${:,.0f}({:d}t,avg{:.1f}%), B=${:,.0f}({:d}t,avg{:.1f}%), Total=${:,.0f}".format(
        r['strategy'], r['total_return']*100, r['excess_return']*100,
        r['pnl_A'], r['trades_A'], r['avg_spread_A'],
        r['pnl_B'], r['trades_B'], r['avg_spread_B'],
        r['total_pnl']
    ))

# ============ 5. 最终排名 ============
print("\n" + "=" * 80)
print("FINAL RANKING (all strategies)")
print("=" * 80)

results_sorted = sorted(results, key=lambda x: x['total_return'], reverse=True)

print("{:<35} {:>9} {:>9} {:>6} {:>7} {:>10} {:>10}".format(
    'Strategy', 'Return', 'Excess', 'A#', 'B#', 'A_PnL', 'B_PnL'
))
print("-" * 90)
for i, r in enumerate(results_sorted[:25]):
    print("{:<35} {:>+8.2f}% {:>+8.2f}% {:>6d} {:>7d} ${:>9,.0f} ${:>9,.0f}".format(
        r['strategy'],
        r['total_return']*100,
        r['excess_return']*100,
        r['trades_A'],
        r['trades_B'],
        r['pnl_A'],
        r['pnl_B']
    ))

# 保存
with open(DATA_DIR / "v3_threshold_optimization.json", 'w') as f:
    json.dump(results_sorted, f, indent=2, default=str)
print("\n[Saved] {}".format(DATA_DIR / "v3_threshold_optimization.json"))

# 买入持有基准
print("\nBuy & Hold: {:+.2f}%".format(results[0]['buyhold_return']*100))
