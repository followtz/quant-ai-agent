# -*- coding: utf-8 -*-
"""
V2.4 Zero-Beta 策略
底仓=0，允许融券卖空，完全消除市场风险

核心逻辑：
1. 底仓=0（无市场风险暴露）
2. B交易：买入做多 → 卖出平仓
3. A交易：融券卖空 → 买回平仓
4. 可同时持有多仓和空仓（对冲）
5. 回测对比V2原版
"""
import sys, json
from datetime import datetime
from pathlib import Path
import csv

WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)

# ===================== 数据加载 =====================
def load_csv_data(csv_path):
    data = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                data.append({
                    'date': row.get('time_key', ''),
                    'open': float(row.get('open',0)),
                    'high': float(row.get('high',0)),
                    'low': float(row.get('low',0)),
                    'close': float(row.get('close',0)),
                    'volume': float(row.get('volume',0)),
                })
            except (ValueError, KeyError):
                continue
    return data

# ===================== V2.4 Zero-Beta 回测 =====================
def backtest_v24_zero_beta(data, params):
    """
    V2.4 回测引擎
    - 底仓=0
    - 允许融券卖空
    - 可同时持有多仓(long)和空仓(short)
    """
    # 策略参数
    BASE = params or {}
    buy_t = BASE.get('buy_t', 0.05)          # B买入阈值
    sell_t = BASE.get('sell_t', 0.12)        # A卖出阈值
    b_offset = BASE.get('b_offset', 0.05)     # B卖出偏移
    a_offset = BASE.get('a_offset', -0.01)    # A买回偏移
    stop_loss_pct = BASE.get('stop_loss_pct', 0.05)
    trade_qty = BASE.get('trade_qty', 1000)
    
    # 持仓状态
    long_pos = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    short_pos = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    
    # 统计变量
    cash = 0.0  # 现金（盈亏累积）
    total_trades = 0
    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_equity = 0.0
    trade_log = []
    
    for i, bar in enumerate(data):
        if i == 0:
            continue
        
        price = bar['close']
        prev_close = data[i-1]['close']
        
        # =============== 多仓检查 ===============
        if long_pos['active']:
            long_pos['days'] += 1
            entry = long_pos['entry']
            qty = long_pos['qty']
            
            # 止损
            if price <= entry * (1 - stop_loss_pct):
                pnl = (price - entry) * qty
                cash += pnl
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_STOP', 'price': price, 'qty': qty,
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                long_pos = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 止盈（卖出平仓）
            sell_price = long_pos['prev_close'] * (1 + b_offset)
            if price >= sell_price:
                pnl = (price - entry) * qty
                cash += pnl
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_SELL', 'price': price, 'qty': qty,
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                long_pos = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查B买入信号（做多）
            buy_price = prev_close * (1 - buy_t)
            if price <= buy_price:
                qty = trade_qty
                long_pos = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'B_BUY', 'price': price, 'qty': qty, 'pnl': 0,
                    'date': bar['date'][:10],
                })
        
        # =============== 空仓检查 ===============
        if short_pos['active']:
            short_pos['days'] += 1
            entry = short_pos['entry']
            qty = short_pos['qty']
            
            # 止损（买回平仓）
            if price >= entry * (1 + stop_loss_pct):
                pnl = (entry - price) * qty  # 卖空盈利 = 卖出价 - 买回价
                cash += pnl
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_STOP', 'price': price, 'qty': qty,
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                short_pos = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 止盈（买回平仓）
            buyback_price = short_pos['prev_close'] * (1 + a_offset)
            if price <= buyback_price:
                pnl = (entry - price) * qty
                cash += pnl
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_BACK', 'price': price, 'qty': qty,
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                short_pos = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查A卖出信号（融券卖空）
            sell_price = prev_close * (1 + sell_t)
            if price >= sell_price:
                qty = trade_qty
                short_pos = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'A_SHORT', 'price': price, 'qty': qty, 'pnl': 0,
                    'date': bar['date'][:10],
                })
        
        # 计算当前权益（现金 + 多仓市值 - 空仓市值）
        equity = cash
        if long_pos['active']:
            equity += long_pos['qty'] * price
        if short_pos['active']:
            equity -= short_pos['qty'] * price  # 空仓是负债
        
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
    
    # 计算最终统计
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    return {
        'total_pnl': round(cash, 2),
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'trade_log': trade_log[:20],  # 前20笔
    }

# ===================== 参数优化扫描 =====================
def param_sweep_v24(data):
    """扫描V2.4的最优参数"""
    best_result = None
    best_pnl = float('-inf')
    
    buy_t_range = [0.03, 0.05, 0.08, 0.10]
    sell_t_range = [0.08, 0.10, 0.12, 0.15]
    
    results = []
    
    for buy_t in buy_t_range:
        for sell_t in sell_t_range:
            params = {
                'buy_t': buy_t,
                'sell_t': sell_t,
                'b_offset': 0.05,
                'a_offset': -0.01,
                'stop_loss_pct': 0.05,
                'trade_qty': 1000,
            }
            
            result = backtest_v24_zero_beta(data, params)
            result['params'] = params
            results.append(result)
            
            if result['total_pnl'] > best_pnl:
                best_pnl = result['total_pnl']
                best_result = result
    
    results.sort(key=lambda x: x['total_pnl'], reverse=True)
    return results, best_result

# ===================== 主函数 =====================
def main():
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日")
    
    # 1. 基准测试：V2.4默认参数
    print("\n" + "="*70)
    print("  V2.4 Zero-Beta 基准测试（底仓=0，允许融券卖空）")
    print("="*70)
    
    base_params = {
        'buy_t': 0.05,
        'sell_t': 0.12,
        'b_offset': 0.05,
        'a_offset': -0.01,
        'stop_loss_pct': 0.05,
        'trade_qty': 1000,
    }
    
    base_result = backtest_v24_zero_beta(data, base_params)
    
    print(f"  盈亏: ${base_result['total_pnl']:,.2f}")
    print(f"  交易: {base_result['total_trades']}笔 (胜率={base_result['win_rate']:.1f}%)")
    print(f"  最大回撤: {base_result['max_drawdown']:.2f}%")
    print(f"  多仓交易: {sum(1 for t in base_result['trade_log'] if 'B_' in t['type'])}笔")
    print(f"  空仓交易: {sum(1 for t in base_result['trade_log'] if 'A_' in t['type'])}笔")
    
    # 2. 参数扫描
    print("\n" + "="*70)
    print("  V2.4 参数扫描（寻找最优参数）")
    print("="*70)
    
    results, best = param_sweep_v24(data)
    
    print(f"  扫描完成，共{len(results)}个组合")
    print(f"\n  Top 5:")
    print(f"  {'buy_t':<8} {'sell_t':<8} {'盈亏':<12} {'交易数':<8} {'胜率':<8} {'回撤':<10}")
    print("  " + "-"*70)
    
    for r in results[:5]:
        print(f"  {r['params']['buy_t']:>7.0%} {r['params']['sell_t']:>7.0%} "
              f"${r['total_pnl']:>10,.2f} {r['total_trades']:>8} "
              f"{r['win_rate']:>7.1f}% {r['max_drawdown']:>9.2f}%")
    
    # 3. 对比V2原版
    print("\n" + "="*70)
    print("  对比总结")
    print("="*70)
    print(f"  V2原版(底仓8884股): $2,115 (胜率44.4%, 回撤-54.59%)")
    print(f"  V2.4 Zero-Beta:    ${base_result['total_pnl']:,.2f} "
          f"(胜率{base_result['win_rate']:.1f}%, 回撤{base_result['max_drawdown']:.2f}%)")
    print(f"  V2.4 最优参数:    ${best['total_pnl']:,.2f} "
          f"(胜率{best['win_rate']:.1f}%, 回撤{best['max_drawdown']:.2f}%)")
    
    # 4. 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'v24_base': base_result,
        'v24_best': best,
        'param_sweep_top10': results[:10],
        'comparison': {
            'v2_original_pnl': 2115,
            'v2_original_win_rate': 44.4,
            'v2_original_max_dd': -54.59,
        }
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v24_zero_beta_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    main()