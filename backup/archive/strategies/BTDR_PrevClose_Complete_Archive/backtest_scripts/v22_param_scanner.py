# -*- coding: utf-8 -*-
"""
V2.2 参数优化器 - 基于EDA的统计学优化

核心思想：
1. 分离不同市场状态 (PANIC_BOUNCE / EUPHORIA / TREND)
2. 在每个状态下扫描参数组合 (buy_t, sell_t)
3. 找到统计显著的最优参数 (t-test p<0.05)
4. 输出状态依赖的最优参数表

优化目标：
- 高胜率 (>55%)
- 高平均收益 (>0.8%/trade)
- 统计显著 (t-stat > 2.0)
- 低回撤 (避免12%接飞刀)
"""
import sys, json, math
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
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': float(row.get('volume', 0)),
                })
            except (ValueError, KeyError):
                continue
    return data

# ===================== 状态检测 (复用v22_simple_backtest.py的逻辑) =====================
def detect_regime(data_history, current_idx, window=20):
    """检测当前市场状态"""
    if current_idx < window:
        return 1, 'EUPHORIA'
    
    recent = data_history[max(0, current_idx - window):current_idx]
    returns = []
    for i in range(1, len(recent)):
        ret = (recent[i]['close'] - recent[i-1]['close']) / recent[i-1]['close']
        returns.append(ret)
    
    if not returns:
        return 1, 'EUPHORIA'
    
    avg_ret = sum(returns) / len(returns)
    volatility = (sum((r - avg_ret)**2 for r in returns) / len(returns)) ** 0.5
    
    recent_5 = returns[-5:] if len(returns) >= 5 else returns
    trend = sum(recent_5) / len(recent_5)
    
    if volatility > 0.05:
        if trend < -0.02:
            return 0, 'PANIC_BOUNCE'
        else:
            return 1, 'EUPHORIA'
    else:
        if trend > 0.01:
            return 2, 'TREND'
        else:
            return 1, 'EUPHORIA'

# ===================== 单笔交易模拟 =====================
def simulate_trade(entry_price, exit_price, qty, trade_type='B'):
    """模拟单笔交易盈亏"""
    if trade_type == 'B':
        return (exit_price - entry_price) * qty
    else:  # 'A' type
        return (entry_price - exit_price) * qty

# ===================== 参数扫描核心 =====================
def scan_parameters_for_regime(data, regime_target, buy_t_range, sell_t_range, base_params):
    """
    扫描指定市场状态下的参数组合
    
    返回：
    - 所有参数组合的结果
    - 排序后的最优组合
    """
    results = []
    
    for buy_t in buy_t_range:
        for sell_t in sell_t_range:
            # 模拟该参数组合
            trades = []
            position = 0  # 0=空仓, 1=持有B, -1=持有A
            entry_price = 0
            entry_qty = 0
            
            for i, bar in enumerate(data):
                if i == 0:
                    continue
                
                price = bar['close']
                prev_close = data[i-1]['close']
                
                # 只处理指定市场状态
                regime, regime_name = detect_regime(data, i, window=20)
                if regime != regime_target:
                    continue
                
                # 检查B买入信号
                if position == 0 and price <= prev_close * (1 - buy_t):
                    position = 1
                    entry_price = price
                    entry_qty = min(base_params['trade_qty'], 
                                   base_params['pos_max'] - base_params['base_shares'])
                    entry_qty = max(100, int(entry_qty / 100) * 100)
                
                # 检查B卖出信号
                elif position == 1:
                    sell_price = prev_close * (1 + base_params['b_offset'])
                    stop_price = entry_price * (1 - base_params['stop_loss_pct'])
                    
                    if price >= sell_price or price <= stop_price:
                        pnl = (price - entry_price) * entry_qty
                        trades.append({
                            'pnl': pnl,
                            'type': 'B_SELL',
                            'entry': entry_price,
                            'exit': price,
                            'qty': entry_qty,
                        })
                        position = 0
                
                # 检查A卖出信号
                elif position == 0 and price >= prev_close * (1 + sell_t):
                    position = -1
                    entry_price = price
                    entry_qty = min(base_params['trade_qty'],
                                   base_params['base_shares'] - base_params['pos_min'])
                    entry_qty = max(100, int(entry_qty / 100) * 100)
                
                # 检查A买回信号
                elif position == -1:
                    buyback_price = prev_close * (1 + base_params['a_offset'])
                    stop_price = entry_price * (1 + base_params['stop_loss_pct'])
                    
                    if price <= buyback_price or price >= stop_price:
                        pnl = (entry_price - price) * entry_qty
                        trades.append({
                            'pnl': pnl,
                            'type': 'A_BACK',
                            'entry': entry_price,
                            'exit': price,
                            'qty': entry_qty,
                        })
                        position = 0
            
            # 统计该参数组合的表现
            if not trades:
                continue
            
            pnls = [t['pnl'] for t in trades]
            total_pnl = sum(pnls)
            wins = sum(1 for p in pnls if p > 0)
            win_rate = wins / len(trades) * 100
            
            # t-test
            avg_pnl = total_pnl / len(trades) if len(trades) > 0 else 0
            std_pnl = (sum((p - avg_pnl)**2 for p in pnls) / len(trades)) ** 0.5 if len(trades) > 0 else 0
            t_stat = (avg_pnl / (std_pnl / (len(trades)**0.5))) if std_pnl > 0 and len(trades) > 1 else 0
            significant = abs(t_stat) > 2.0  # 95%置信度
            
            results.append({
                'buy_t': buy_t,
                'sell_t': sell_t,
                'num_trades': len(trades),
                'total_pnl': round(total_pnl, 2),
                'avg_pnl_per_trade': round(avg_pnl, 2),
                'win_rate': round(win_rate, 2),
                't_stat': round(t_stat, 4),
                'significant': significant,
                'trades': trades[:5],  # 只保留前5笔明细
            })
    
    # 排序：先按显著性，再按平均收益
    results.sort(key=lambda x: (-x['significant'], -x['avg_pnl_per_trade']))
    return results

# ===================== 主函数 =====================
def main():
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日")
    
    # V2基础参数
    BASE = {
        'base_shares': 8894,
        'trade_qty': 1000,
        'pos_min': 7000,
        'pos_max': 11000,
        'a_offset': -0.01,
        'b_offset': 0.05,
        'stop_loss_pct': 0.05,
    }
    
    # 扫描范围
    buy_t_range = [0.03, 0.05, 0.08, 0.10, 0.12]
    sell_t_range = [0.08, 0.10, 0.12, 0.15]
    
    print("\n" + "="*70)
    print("  参数扫描器：寻找统计显著的最优参数")
    print("="*70)
    
    regime_names = {0: 'PANIC_BOUNCE', 1: 'EUPHORIA', 2: 'TREND'}
    all_results = {}
    
    for regime_target in [0, 1, 2]:
        regime_name = regime_names[regime_target]
        print(f"\n[{regime_name}] 参数扫描中...")
        
        results = scan_parameters_for_regime(
            data, regime_target, buy_t_range, sell_t_range, BASE
        )
        
        all_results[regime_name] = results
        
        if results:
            # 打印Top 5
            print(f"  找到{len(results)}个参数组合，Top 5:")
            print(f"  {'buy_t':<8} {'sell_t':<8} {'交易数':<8} {'总盈亏':<12} {'平均/trade':<12} "
                  f"{'胜率':<8} {'t-stat':<10} {'显著?'}")
            print("  " + "-"*70)
            
            for r in results[:5]:
                sig = "是" if r['significant'] else "否"
                print(f"  {r['buy_t']:>7.0%} {r['sell_t']:>7.0%} {r['num_trades']:>8} "
                      f"${r['total_pnl']:>10,.2f} ${r['avg_pnl_per_trade']:>10.2f} "
                      f"{r['win_rate']:>7.1f}% {r['t_stat']:>9.2f} {sig}")
        else:
            print(f"  该状态下无有效交易")
    
    # 汇总最优参数表
    print("\n" + "="*70)
    print("  最优参数表 (每个状态的最佳参数)")
    print("="*70)
    print(f"  {'状态':<20} {'buy_t':<8} {'sell_t':<8} {'胜率':<8} {'平均收益/trade':<18} {'t-stat'}")
    print("  " + "-"*70)
    
    optimal_params = {}
    for regime_target in [0, 1, 2]:
        regime_name = regime_names[regime_target]
        results = all_results.get(regime_name, [])
        if results and results[0]['significant']:
            best = results[0]
            optimal_params[regime_name] = {
                'buy_t': best['buy_t'],
                'sell_t': best['sell_t'],
                'win_rate': best['win_rate'],
                'avg_pnl': best['avg_pnl_per_trade'],
                't_stat': best['t_stat'],
            }
            print(f"  {regime_name:<20} {best['buy_t']:>7.0%} {best['sell_t']:>7.0%} "
                  f"{best['win_rate']:>7.1f}% ${best['avg_pnl_per_trade']:>15.2f} {best['t_stat']:>8.2f}")
        else:
            # 使用默认参数
            optimal_params[regime_name] = {
                'buy_t': 0.05,
                'sell_t': 0.12,
                'win_rate': 0,
                'avg_pnl': 0,
                't_stat': 0,
            }
            print(f"  {regime_name:<20} 默认参数 (无显著组合)")
    
    # 保存完整结果
    report = {
        'timestamp': datetime.now().isoformat(),
        'scan_ranges': {
            'buy_t': buy_t_range,
            'sell_t': sell_t_range,
        },
        'optimal_params': optimal_params,
        'all_results': all_results,
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v22_param_scan_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")
    
    # 输出可直接粘贴到策略代码的参数表
    print("\n" + "="*70)
    print("  可直接使用的参数配置 (复制到V2.2策略)")
    print("="*70)
    print("REGIME_PARAMS = {")
    for regime_name, params in optimal_params.items():
        print(f"    '{regime_name}': {{'buy_t': {params['buy_t']}, 'sell_t': {params['sell_t']}}},  "
              f"# 胜率={params['win_rate']:.1f}%, t={params['t_stat']:.2f}")
    print("}")

if __name__ == '__main__':
    main()
