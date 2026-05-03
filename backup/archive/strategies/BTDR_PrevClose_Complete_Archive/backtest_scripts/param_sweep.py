# -*- coding: utf-8 -*-
"""
BTDR PrevClose V2 优化参数扫描
目标：找到最优止损/RSI/熔断参数组合
"""
import sys, json
from datetime import datetime
from pathlib import Path

WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)

import csv

def load_csv_data(csv_path):
    data = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                data.append({
                    'date': row.get('time_key', ''),
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': float(row.get('volume', 0)),
                })
            except (ValueError, KeyError):
                continue
    return data

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_volatility(prices, period=20):
    if len(prices) < period:
        return 0.5
    recent = prices[-period:]
    mean = sum(recent) / len(recent)
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    return (variance ** 0.5) / mean if mean > 0 else 0.5

def run_backtest(data, params):
    shares = params['base_shares']
    total_pnl = 0.0
    total_trades = 0
    wins = 0; losses = 0
    max_drawdown = 0.0; peak_equity = 0.0
    stop_count = 0; filter_count = 0
    circuit = False
    
    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    price_history = []
    
    for i, bar in enumerate(data):
        price = bar['close']
        prev_close = data[i-1]['close'] if i > 0 else price
        price_history.append(price)
        
        equity = shares * price
        if equity > peak_equity: peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown: max_drawdown = dd
        
        # 熔断检查
        if dd <= params['max_drawdown']:
            circuit = True
            break
        
        rsi = calculate_rsi(price_history) if len(price_history) > 14 else 50.0
        vol = calculate_volatility(price_history) if len(price_history) >= 20 else 0.5
        vol_scale = min(2.0, max(0.5, params['vol_target'] / vol)) if vol > 0 else 1.0
        d_qty = max(100, int(params['trade_qty'] * vol_scale / 100) * 100)
        
        # 涡轮A
        if turbo_a['active']:
            turbo_a['days'] += 1
            entry = turbo_a['entry']
            stop_price = entry * (1 + params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_a['qty']
                total_pnl += pnl; shares += turbo_a['qty']
                total_trades += 1; stop_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
            else:
                buyback = turbo_a['prev_close'] * (1 + params['a_offset'])
                if price <= buyback:
                    pnl = (entry - price) * turbo_a['qty']
                    total_pnl += pnl; shares += turbo_a['qty']
                    total_trades += 1
                    if pnl >= 0: wins += 1
                    else: losses += 1
                    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            if params['rsi_filter'] and rsi <= params['rsi_sell_thresh']:
                pass  # 不阻止卖出
            sell_trigger = prev_close * (1 + params['sell_t'])
            if price >= sell_trigger and shares > params['pos_min']:
                qty = min(d_qty, shares - params['pos_min'])
                shares -= qty
                turbo_a = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
        
        # 涡轮B
        if turbo_b['active']:
            turbo_b['days'] += 1
            entry = turbo_b['entry']
            stop_price = entry * (1 - params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl; shares -= turbo_b['qty']
                total_trades += 1; stop_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
            else:
                sellback = turbo_b['prev_close'] * (1 + params['b_offset'])
                if price >= sellback:
                    pnl = (price - entry) * turbo_b['qty']
                    total_pnl += pnl; shares -= turbo_b['qty']
                    total_trades += 1
                    if pnl >= 0: wins += 1
                    else: losses += 1
                    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            if params['rsi_filter'] and rsi >= params['rsi_buy_thresh']:
                filter_count += 1
                continue
            buy_trigger = prev_close * (1 - params['buy_t'])
            if price <= buy_trigger and shares < params['pos_max']:
                qty = min(d_qty, params['pos_max'] - shares)
                shares += qty
                turbo_b = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
    
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    return {
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'stop_count': stop_count,
        'filter_count': filter_count,
        'circuit': circuit,
        'final_shares': shares,
    }

# 基准参数（V2原版）
BASE = {
    'sell_t': 0.12, 'a_offset': -0.01, 'buy_t': 0.05, 'b_offset': 0.05,
    'trade_qty': 1000, 'pos_min': 7000, 'pos_max': 11000, 'base_shares': 8894,
    'stop_loss_pct': 0, 'max_drawdown': 0, 'vol_target': 0.3,
    'rsi_filter': False, 'rsi_buy_thresh': 30, 'rsi_sell_thresh': 70,
    'volume_filter': False, 'volume_ratio': 1.2,
}

# 参数扫描配置
PARAM_GRID = {
    'stop_loss_pct': [-0.03, -0.05, -0.08, -0.10, 0],  # 0=无止损
    'max_drawdown': [-0.15, -0.20, -0.25, 0],  # 0=无熔断
    'rsi_buy_thresh': [25, 30, 35, 40],
    'rsi_sell_thresh': [60, 65, 70, 75],
}

def main():
    # 加载数据
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)} 个交易日 ({data[0]['date'][:10]} ~ {data[-1]['date'][:10]})")
    
    # 基准测试（V2原版）
    print("\n" + "="*70)
    print("  基准测试: V2原版 (无止损/无熔断/无信号过滤)")
    print("="*70)
    base_result = run_backtest(data, BASE)
    print(f"  总盈亏: ${base_result['total_pnl']:,.2f}")
    print(f"  交易次数: {base_result['total_trades']}")
    print(f"  胜率: {base_result['win_rate']:.1f}%")
    print(f"  最大回撤: {base_result['max_drawdown']:.2f}%")
    
    # 参数扫描
    results = []
    
    print("\n" + "="*70)
    print("  参数扫描: V2.1 优化版组合")
    print("="*70)
    
    from itertools import product
    count = 0
    for stop_loss, max_dd, rsi_buy, rsi_sell in product(
        PARAM_GRID['stop_loss_pct'],
        PARAM_GRID['max_drawdown'],
        PARAM_GRID['rsi_buy_thresh'],
        PARAM_GRID['rsi_sell_thresh'],
    ):
        count += 1
        params = {
            **BASE,
            'stop_loss_pct': stop_loss,
            'max_drawdown': max_dd,
            'rsi_filter': True,
            'rsi_buy_thresh': rsi_buy,
            'rsi_sell_thresh': rsi_sell,
        }
        result = run_backtest(data, params)
        
        # 只记录有意义的组合（至少1笔交易或止损触发）
        if result['total_trades'] > 0 or result['stop_count'] > 0:
            results.append({
                'stop_loss': stop_loss,
                'max_drawdown': max_dd,
                'rsi_buy': rsi_buy,
                'rsi_sell': rsi_sell,
                **result
            })
    
    print(f"[扫描] 共测试 {count} 个组合，{len(results)} 个有效结果")
    
    # 按最大回撤排序（越小越好）
    results.sort(key=lambda x: x['max_drawdown'])
    
    print("\n" + "="*70)
    print("  TOP 10 结果 (按最大回撤排序)")
    print("="*70)
    print(f"{'止损':<8} {'熔断':<8} {'RSI买':<8} {'RSI卖':<8} {'盈亏':<10} {'交易':<6} {'胜率':<8} {'回撤':<10} {'止损次':<8}")
    print("-" * 80)
    
    for r in results[:10]:
        stop_str = "无" if r['stop_loss'] == 0 else f"{r['stop_loss']:.0%}"
        dd_str = "无" if r['max_drawdown'] == 0 else f"{r['max_drawdown']:.0%}"
        print(f"{stop_str:<8} {dd_str:<8} {r['rsi_buy']:<8} {r['rsi_sell']:<8} "
              f"${r['total_pnl']:>9,.2f} {r['total_trades']:<6} {r['win_rate']:>7.1f}% "
              f"{r['max_drawdown']:>9.2f}% {r['stop_count']:<8}")
    
    # 保存完整结果
    report = {
        'timestamp': datetime.now().isoformat(),
        'base_result': base_result,
        'total_combinations': count,
        'valid_results': len(results),
        'results': sorted(results, key=lambda x: x['max_drawdown'])[:30],
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "param_sweep_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    main()