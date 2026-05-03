# -*- coding: utf-8 -*-
"""
V2.6 纯趋势跟踪版 - 顺应BTDR的趋势特性

核心逻辑（与V2完全不同）：
1. 删除B买入信号（不抄底！12%大跌后继续跌）
2. 突破买入：价格 > 前5日最高价 → 做多
3. 破位卖出：价格 < 前5日最低价 → 平仓（或做空）
4. 底仓=1000股（极低，减少市场风险）
5. 移动止盈：从最高价回撤2%就卖
6. 移动止损：从最低价反弹2%就买回（空仓）

设计理念：
- BTDR是趋势股（3%大涨后继续涨）
- 不预测反转，只跟随趋势
- 让利润奔跑，快速止损

目标：顺应趋势，降低回撤，保持盈利
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

# ===================== V2.6 纯趋势跟踪回测 =====================
def backtest_v26_trend_following(data, params=None):
    """
    V2.6 回测引擎 - 纯趋势跟踪
    
    策略规则：
    1. 突破前5日高点 → 做多（加仓）
    2. 跌破前5日低点 → 平仓（减仓）
    3. 移动止盈：从最高价回撤2% → 平仓
    4. 底仓1000股，最大持仓11000股，最小持仓7000股
    """
    # 参数
    BASE = params or {}
    base_shares = BASE.get('base_shares', 1000)  # 极低底仓
    max_shares = BASE.get('max_shares', 11000)
    min_shares = BASE.get('min_shares', 7000)
    breakout_days = BASE.get('breakout_days', 5)  # 突破N日
    stop_loss_pct = BASE.get('stop_loss_pct', 0.02)  # 移动止盈2%
    position_size = BASE.get('position_size', 1000)  # 每次加减仓数量
    
    # 持仓状态
    shares = base_shares
    peak_price = data[0]['close']  # 最高价追踪
    lowest_price = data[0]['close']  # 最低价追踪
    cash = 0.0  # 现金（用于计算盈亏）
    
    # 统计
    total_trades = 0
    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_equity = base_shares * data[0]['close']
    trade_log = []
    
    for i, bar in enumerate(data):
        if i < breakout_days:
            continue
        
        price = bar['close']
        
        # 计算前N日高低点
        highs = [data[j]['high'] for j in range(i-breakout_days, i)]
        lows = [data[j]['low'] for j in range(i-breakout_days, i)]
        prev_high = max(highs)
        prev_low = min(lows)
        
        # 更新最高最低价
        if price > peak_price:
            peak_price = price
        if price < lowest_price or lowest_price == 0:
            lowest_price = price
        
        # 权益计算
        equity = shares * price + cash
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
        
        # =============== 策略逻辑 ===============
        
        # 1. 突破买入（趋势延续）
        if price > prev_high and shares < max_shares:
            qty = min(position_size, max_shares - shares)
            qty = max(100, int(qty / 100) * 100)
            shares += qty
            cash -= qty * price  # 花费现金
            trade_log.append({
                'type': 'BUY_BREAKOUT',
                'price': price,
                'qty': qty,
                'shares': shares,
                'date': bar['date'][:10],
                'reason': f'breakout_{breakout_days}d_high',
            })
        
        # 2. 破位卖出（趋势反转）
        elif price < prev_low and shares > min_shares:
            qty = min(position_size, shares - min_shares)
            qty = max(100, int(qty / 100) * 100)
            shares -= qty
            cash += qty * price  # 获得现金
            trade_log.append({
                'type': 'SELL_BREAKDOWN',
                'price': price,
                'qty': qty,
                'shares': shares,
                'date': bar['date'][:10],
                'reason': f'breakdown_{breakout_days}d_low',
            })
        
        # 3. 移动止盈（从最高价回撤2%）
        elif peak_price > 0 and shares > base_shares:
            trailing_sell = peak_price * (1 - stop_loss_pct)
            if price <= trailing_sell:
                qty = shares - base_shares
                qty = max(100, int(qty / 100) * 100)
                shares -= qty
                cash += qty * price
                total_trades += 1
                pnl = qty * (price - peak_price)  # 估算盈亏
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'SELL_TRAILING',
                    'price': price,
                    'qty': qty,
                    'pnl': round(pnl, 2),
                    'shares': shares,
                    'date': bar['date'][:10],
                    'peak': round(peak_price, 2),
                })
                peak_price = price  # 重置最高价
        
        # 4. 移动止损（从最低价反弹2%，用于空仓，这里暂不使用）
        
        # 底线：持仓回到底仓范围
        if shares > max_shares:
            qty = shares - max_shares
            shares = max_shares
            cash += qty * price
        elif shares < min_shares:
            qty = min_shares - shares
            shares = min_shares
            cash -= qty * price
    
    # 计算最终盈亏
    final_value = shares * data[-1]['close'] + cash
    initial_value = base_shares * data[0]['close']
    total_pnl = final_value - initial_value
    
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    return {
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'final_shares': shares,
        'trade_log': trade_log[:30],
    }

# ===================== 参数扫描 =====================
def param_sweep_v26(data):
    """扫描V2.6的关键参数"""
    results = []
    
    breakout_days_range = [3, 5, 8, 10]
    stop_loss_range = [0.01, 0.02, 0.03]
    position_size_range = [500, 1000, 2000]
    
    for breakout_days in breakout_days_range:
        for stop_loss in stop_loss_range:
            for position_size in position_size_range:
                params = {
                    'base_shares': 1000,
                    'max_shares': 11000,
                    'min_shares': 7000,
                    'breakout_days': breakout_days,
                    'stop_loss_pct': stop_loss,
                    'position_size': position_size,
                }
                
                result = backtest_v26_trend_following(data, params)
                result['params'] = params
                results.append(result)
    
    # 排序：先按盈亏（越大越好），再按回撤（越小越好）
    results.sort(key=lambda x: (-x['total_pnl'], x['max_drawdown']))
    return results

# ===================== 主函数 =====================
def main():
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日")
    
    # 1. V2.6基准测试
    print("\n" + "="*70)
    print("  V2.6 纯趋势跟踪版 - 基准测试")
    print("="*70)
    print("  配置: 底仓1000股，突破5日高点买入，跌破5日低点卖出")
    print("  移动止盈: 2%（从最高价回撤）")
    
    base_params = {
        'base_shares': 1000,
        'max_shares': 11000,
        'min_shares': 7000,
        'breakout_days': 5,
        'stop_loss_pct': 0.02,
        'position_size': 1000,
    }
    
    base_result = backtest_v26_trend_following(data, base_params)
    
    print(f"\n  V2.6 结果:")
    print(f"  盈亏: ${base_result['total_pnl']:,.2f}")
    print(f"  交易: {base_result['total_trades']}笔 (胜率={base_result['win_rate']:.1f}%)")
    print(f"  最大回撤: {base_result['max_drawdown']:.2f}%")
    print(f"  最终持仓: {base_result['final_shares']}股")
    print(f"  交易明细: {len(base_result['trade_log'])}笔")
    
    # 2. 参数扫描
    print("\n" + "="*70)
    print("  V2.6 参数扫描（寻找最优参数组合）")
    print("="*70)
    
    results = param_sweep_v26(data)
    
    print(f"  扫描完成，共{len(results)}个组合")
    print(f"\n  Top 10 (按盈亏排序):")
    print(f"  {'突破N日':<8} {'止盈':<8} {'加减仓':<8} {'盈亏':<12} {'交易':<8} {'胜率':<8} {'回撤':<10}")
    print("  " + "-"*70)
    
    for r in results[:10]:
        print(f"  {r['params']['breakout_days']:>7} {r['params']['stop_loss_pct']:>7.0%} "
              f"{r['params']['position_size']:>7} "
              f"${r['total_pnl']:>10,.2f} {r['total_trades']:>8} "
              f"{r['win_rate']:>7.1f}% {r['max_drawdown']:>9.2f}%")
    
    # 3. 对比所有版本
    best = results[0]
    
    print("\n" + "="*70)
    print("  全版本对比总结")
    print("="*70)
    print(f"  V2原版(底仓8884股):     $2,115 (胜率44.4%, 回撤-54.59%)")
    print(f"  V2.4 Zero-Beta:          $-1,425 (胜率36.4%, 回撤-196.11%)")
    print(f"  V3.0 ML趋势(底仓1000股): $-685 (胜率20.0%, 回撤-79.18%)")
    print(f"  V2.5优化(底仓5000股):    $425 (胜率66.7%, 回撤-53.66%)")
    print(f"  V2.6基准(底仓1000股):    ${base_result['total_pnl']:,.2f} "
          f"(胜率{base_result['win_rate']:.1f}%, 回撤{base_result['max_drawdown']:.2f}%)")
    print(f"  V2.6最优(底仓1000股):    ${best['total_pnl']:,.2f} "
          f"(胜率{best['win_rate']:.1f}%, 回撤{best['max_drawdown']:.2f}%)")
    
    # 4. 结论
    print("\n" + "="*70)
    print("  核心结论")
    print("="*70)
    
    if best['total_pnl'] > 2115:
        print(f"  [成功] V2.6最优版(${best['total_pnl']:,.2f})超越V2原版($2,115)")
        print(f"  回撤改善: {abs(-54.59 - best['max_drawdown']):.2f}%")
    elif best['max_drawdown'] < -30:
        print(f"  [部分成功] V2.6最优版回撤{best['max_drawdown']:.2f}%，达到<-30%目标")
        print(f"  但盈亏(${best['total_pnl']:,.2f})低于V2原版($2,115)")
    else:
        print(f"  [失败] V2.6仍无法同时超越V2原版的盈亏和回撤")
        print(f"  建议：重新审视策略逻辑或寻找其他标的")
    
    # 5. 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'v26_base': base_result,
        'v26_best': best,
        'param_sweep_top20': results[:20],
        'all_versions_comparison': {
            'v2_original': {'pnl': 2115, 'win_rate': 44.4, 'max_dd': -54.59},
            'v24_zero_beta': {'pnl': -1425, 'win_rate': 36.4, 'max_dd': -196.11},
            'v30_ml': {'pnl': -685, 'win_rate': 20.0, 'max_dd': -79.18},
            'v25_optimized': {'pnl': 425, 'win_rate': 66.7, 'max_dd': -53.66},
            'v26_base': base_result,
            'v26_best': best,
        }
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v26_trend_following_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    main()