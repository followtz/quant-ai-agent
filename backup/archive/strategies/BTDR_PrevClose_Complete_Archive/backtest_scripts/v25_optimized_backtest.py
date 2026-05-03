# -*- coding: utf-8 -*-
"""
V2.5 优化版 - 基于V2原版降低回撤

核心改进（相比V2原版）：
1. 底仓=5000股（降低市场风险，原版8884股）
2. B买入：连续3天跌>10%才买入（避免接飞刀）
3. B卖出：移动止盈（从最高价回撤3%就卖）
4. A卖空：只在+15%亢奋时才卖空（小仓位1000股）
5. A买回：移动止损（从最低价反弹3%就买回）
6. 统一止损：5%

目标：保持盈利，大幅降低回撤（-54% → -30%以下）
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

# ===================== 辅助函数 =====================
def check_consecutive_down(data, i, days=3, min_drop=0.10):
    """
    检查前days天是否连续下跌，且累计跌幅>min_drop
    返回：True/False
    """
    if i < days:
        return False
    
    total_drop = 0
    for j in range(i-days, i):
        drop = (data[j+1]['close'] - data[j]['close']) / data[j]['close']
        if drop > 0:  # 有上涨，不算连续下跌
            return False
        total_drop += drop
    
    return abs(total_drop) >= min_drop

def check_extreme_up(data, i, min_gain=0.15):
    """
    检查前1天是否大涨>min_gain（亢奋状态）
    """
    if i < 1:
        return False
    
    gain = (data[i]['close'] - data[i-1]['close']) / data[i-1]['close']
    return gain >= min_gain

# ===================== V2.5 回测引擎 =====================
def backtest_v25_optimized(data, params=None):
    """
    V2.5 回测引擎
    - 底仓5000股
    - 改进入场：连续3天跌>10%才买
    - 改进出场：移动止盈（从最高价回撤3%）
    - A交易：+15%亢奋才卖空，小仓位1000股
    """
    # 参数
    BASE = params or {}
    base_shares = BASE.get('base_shares', 5000)  # 降低底仓
    trade_qty = BASE.get('trade_qty', 1000)
    stop_loss_pct = BASE.get('stop_loss_pct', 0.05)
    trailing_stop_pct = BASE.get('trailing_stop_pct', 0.03)  # 移动止盈
    buy_consecutive_days = BASE.get('buy_consecutive_days', 3)
    buy_min_drop = BASE.get('buy_min_drop', 0.10)
    sell_extreme_up = BASE.get('sell_extreme_up', 0.15)
    
    # 持仓状态
    shares = base_shares
    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0, 'highest': 0}
    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0, 'lowest': 0}
    
    # 统计
    cash = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_equity = base_shares * data[0]['close']
    trade_log = []
    
    for i, bar in enumerate(data):
        if i == 0:
            continue
        
        price = bar['close']
        prev_close = data[i-1]['close']
        
        # 权益计算
        equity = shares * price + cash
        if turbo_b['active']:
            equity += turbo_b['qty'] * price
        if turbo_a['active']:
            equity -= turbo_a['qty'] * price  # 空仓是负债
        
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
        
        # =============== 涡轮B检查（多仓） ===============
        if turbo_b['active']:
            turbo_b['days'] += 1
            entry = turbo_b['entry']
            qty = turbo_b['qty']
            
            # 更新最高价
            if price > turbo_b['highest']:
                turbo_b['highest'] = price
            
            # 止损
            if price <= entry * (1 - stop_loss_pct):
                pnl = (price - entry) * qty
                cash += pnl
                shares += qty
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_STOP', 'price': price, 'qty': qty,
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0, 'highest': 0}
                continue
            
            # 移动止盈（从最高价回撤3%）
            if turbo_b['highest'] > 0:
                sell_price = turbo_b['highest'] * (1 - trailing_stop_pct)
                if price <= sell_price:
                    pnl = (price - entry) * qty
                    cash += pnl
                    shares += qty
                    total_trades += 1
                    if pnl >= 0: wins += 1
                    else: losses += 1
                    trade_log.append({
                        'type': 'B_TRAILING', 'price': price, 'qty': qty,
                        'pnl': round(pnl, 2), 'date': bar['date'][:10],
                        'highest': round(turbo_b['highest'], 2),
                    })
                    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0, 'highest': 0}
        else:
            # 检查B买入信号（改进版：连续3天跌>10%）
            if price <= prev_close * 0.95 and shares < 11000:  # 原V2的buy_t=5%
                # 额外检查：是否连续下跌
                if check_consecutive_down(data, i, days=buy_consecutive_days, min_drop=buy_min_drop):
                    qty = min(int(trade_qty / 100) * 100, 11000 - shares)
                    qty = max(100, qty)
                    shares -= qty
                    turbo_b = {
                        'active': True, 'entry': price, 'qty': qty,
                        'prev_close': prev_close, 'days': 0, 'highest': price,
                    }
                    trade_log.append({
                        'type': 'B_BUY_V25', 'price': price, 'qty': qty, 'pnl': 0,
                        'date': bar['date'][:10], 'reason': f'consecutive_{buy_consecutive_days}d_drop',
                    })
        
        # =============== 涡轮A检查（空仓） ===============
        if turbo_a['active']:
            turbo_a['days'] += 1
            entry = turbo_a['entry']
            qty = turbo_a['qty']
            
            # 更新最低价
            if price < turbo_a['lowest'] or turbo_a['lowest'] == 0:
                turbo_a['lowest'] = price
            
            # 止损
            if price >= entry * (1 + stop_loss_pct):
                pnl = (entry - price) * qty
                cash += pnl
                shares += qty
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_STOP', 'price': price, 'qty': qty,
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0, 'lowest': 0}
                continue
            
            # 移动止损（从最低价反弹3%）
            if turbo_a['lowest'] > 0:
                buyback_price = turbo_a['lowest'] * (1 + trailing_stop_pct)
                if price >= buyback_price:
                    pnl = (entry - price) * qty
                    cash += pnl
                    shares += qty
                    total_trades += 1
                    if pnl >= 0: wins += 1
                    else: losses += 1
                    trade_log.append({
                        'type': 'A_TRAILING', 'price': price, 'qty': qty,
                        'pnl': round(pnl, 2), 'date': bar['date'][:10],
                        'lowest': round(turbo_a['lowest'], 2),
                    })
                    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0, 'lowest': 0}
        else:
            # 检查A卖出信号（改进版：+15%亢奋才卖空）
            if price >= prev_close * (1 + sell_extreme_up) and shares > 7000:
                # 额外检查：是否极端上涨
                if check_extreme_up(data, i, min_gain=sell_extreme_up):
                    qty = min(int(trade_qty / 100) * 100, shares - 7000)
                    qty = max(100, qty)
                    shares -= qty
                    turbo_a = {
                        'active': True, 'entry': price, 'qty': qty,
                        'prev_close': prev_close, 'days': 0, 'lowest': price,
                    }
                    trade_log.append({
                        'type': 'A_SHORT_V25', 'price': price, 'qty': qty, 'pnl': 0,
                        'date': bar['date'][:10], 'reason': f'extreme_up_{sell_extreme_up:.0%}',
                    })
    
    # 计算最终盈亏
    final_shares = shares
    if turbo_b['active']:
        final_shares += turbo_b['qty']
    if turbo_a['active']:
        final_shares -= turbo_a['qty']
    
    total_pnl = cash + (final_shares - base_shares) * data[-1]['close']
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    return {
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'final_shares': final_shares,
        'trade_log': trade_log[:30],
    }

# ===================== 参数扫描 =====================
def param_sweep_v25(data):
    """扫描V2.5的关键参数"""
    results = []
    
    # 扫描范围（重点：降低回撤）
    base_shares_range = [3000, 5000, 7000]
    trailing_stop_range = [0.02, 0.03, 0.05]
    buy_drop_range = [0.08, 0.10, 0.12]
    sell_up_range = [0.12, 0.15, 0.18]
    
    for base_shares in base_shares_range:
        for trailing_stop in trailing_stop_range:
            for buy_drop in buy_drop_range:
                for sell_up in sell_up_range:
                    params = {
                        'base_shares': base_shares,
                        'trade_qty': 1000,
                        'stop_loss_pct': 0.05,
                        'trailing_stop_pct': trailing_stop,
                        'buy_consecutive_days': 3,
                        'buy_min_drop': buy_drop,
                        'sell_extreme_up': sell_up,
                    }
                    
                    result = backtest_v25_optimized(data, params)
                    result['params'] = params
                    results.append(result)
    
    # 排序：先按回撤（越小越好），再按盈亏（越大越好）
    results.sort(key=lambda x: (x['max_drawdown'], -x['total_pnl']))
    return results

# ===================== 主函数 =====================
def main():
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日")
    
    # 1. V2.5基准测试
    print("\n" + "="*70)
    print("  V2.5 优化版基准测试")
    print("="*70)
    print("  配置: 底仓5000股，移动止盈3%，连续3天跌10%才买")
    
    base_params = {
        'base_shares': 5000,
        'trade_qty': 1000,
        'stop_loss_pct': 0.05,
        'trailing_stop_pct': 0.03,
        'buy_consecutive_days': 3,
        'buy_min_drop': 0.10,
        'sell_extreme_up': 0.15,
    }
    
    base_result = backtest_v25_optimized(data, base_params)
    
    print(f"\n  V2.5 结果:")
    print(f"  盈亏: ${base_result['total_pnl']:,.2f}")
    print(f"  交易: {base_result['total_trades']}笔 (胜率={base_result['win_rate']:.1f}%)")
    print(f"  最大回撤: {base_result['max_drawdown']:.2f}%")
    print(f"  最终持仓: {base_result['final_shares']}股")
    
    # 2. 参数扫描
    print("\n" + "="*70)
    print("  V2.5 参数扫描（寻找最优参数组合）")
    print("="*70)
    
    results = param_sweep_v25(data)
    
    print(f"  扫描完成，共{len(results)}个组合")
    print(f"\n  Top 10 (按回撤排序):")
    print(f"  {'底仓':<8} {'止盈':<8} {'买入跌':<8} {'卖出涨':<8} {'盈亏':<12} {'交易':<8} {'胜率':<8} {'回撤':<10}")
    print("  " + "-"*70)
    
    for r in results[:10]:
        print(f"  {r['params']['base_shares']:>7} {r['params']['trailing_stop_pct']:>7.0%} "
              f"{r['params']['buy_min_drop']:>7.0%} {r['params']['sell_extreme_up']:>7.0%} "
              f"${r['total_pnl']:>10,.2f} {r['total_trades']:>8} "
              f"{r['win_rate']:>7.1f}% {r['max_drawdown']:>9.2f}%")
    
    # 3. 对比V2原版和V2.5最优
    best = results[0]
    
    print("\n" + "="*70)
    print("  对比总结")
    print("="*70)
    print(f"  V2原版(底仓8884股): $2,115 (胜率44.4%, 回撤-54.59%)")
    print(f"  V2.5基准(底仓5000股): ${base_result['total_pnl']:,.2f} "
          f"(胜率{base_result['win_rate']:.1f}%, 回撤{base_result['max_drawdown']:.2f}%)")
    print(f"  V2.5最优(底仓{best['params']['base_shares']}股): ${best['total_pnl']:,.2f} "
          f"(胜率{best['win_rate']:.1f}%, 回撤{best['max_drawdown']:.2f}%)")
    
    improvement_dd = -54.59 - best['max_drawdown']  # 回撤改善（正数=变好）
    improvement_pnl = best['total_pnl'] - 2115
    
    print(f"\n  回撤改善: {improvement_dd:.2f}% (目标: <-30%)")
    print(f"  盈亏变化: ${improvement_pnl:,.2f}")
    
    if best['max_drawdown'] < -30:
        print(f"\n  [成功] 回撤降至-30%以下！")
    else:
        print(f"\n  [警告] 回撤仍高于-30%，需继续优化")
    
    # 4. 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'v25_base': base_result,
        'v25_best': best,
        'param_sweep_top20': results[:20],
        'comparison': {
            'v2_original': {'pnl': 2115, 'win_rate': 44.4, 'max_dd': -54.59},
            'improvement_dd': round(improvement_dd, 2),
            'improvement_pnl': round(improvement_pnl, 2),
        }
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v25_optimized_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    main()