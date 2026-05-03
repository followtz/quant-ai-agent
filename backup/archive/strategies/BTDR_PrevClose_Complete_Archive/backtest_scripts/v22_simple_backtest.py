# -*- coding: utf-8 -*-
"""
BTDR PrevClose V2.2 简化版 - 基于EDA规则的策略优化
不依赖复杂机器学习，直接用EDA发现的统计规律

核心改进：
1. 状态检测：用简单规则 (volatility + recent returns)
2. 状态依赖参数
3. 趋势过滤器：12%大跌后不买入
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
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': float(row.get('volume', 0)),
                })
            except (ValueError, KeyError):
                continue
    return data

# ===================== 简单状态检测 (基于EDA发现的3个状态) =====================
def detect_regime(data_history, current_idx, window=20):
    """
    简单规则检测市场状态
    
    根据EDA结果：
    - State 0 (恐慌反弹): 高波动 + 近期大跌 → 均值回归有效
    - State 1 (亢奋回调): 中等波动 + 近期大涨 → 会回调
    - State 2 (趋势上涨): 低波动 + 持续上涨 → 趋势延续
    
    返回: (state_code, state_name, params)
    """
    if current_idx < window:
        return 1, 'EUPHORIA', None  # 默认亢奋状态
    
    # 取最近window天的数据
    recent = data_history[max(0, current_idx - window):current_idx]
    
    # 计算特征
    returns = []
    for i in range(1, len(recent)):
        ret = (recent[i]['close'] - recent[i-1]['close']) / recent[i-1]['close']
        returns.append(ret)
    
    if not returns:
        return 1, 'EUPHORIA', None
    
    # 波动率
    avg_ret = sum(returns) / len(returns)
    volatility = (sum((r - avg_ret)**2 for r in returns) / len(returns)) ** 0.5
    
    # 近期趋势 (最近5天)
    recent_5 = returns[-5:] if len(returns) >= 5 else returns
    trend = sum(recent_5) / len(recent_5)
    
    # 规则分类
    if volatility > 0.05:  # 高波动
        if trend < -0.02:  # 近期大跌
            state = 0  # 恐慌反弹
            name = 'PANIC_BOUNCE'
            params = {
                'buy_t': 0.08,      # 等跌8%再买
                'sell_t': 0.10,    # 涨10%卖
                'pos_scale': 1.2,   # 加大仓位
                'note': 'EDA: 恐慌后均值回归有效'
            }
        else:
            state = 1  # 亢奋回调
            name = 'EUPHORIA'
            params = {
                'buy_t': 0.03,
                'sell_t': 0.08,
                'pos_scale': 0.8,
                'note': 'EDA: 涨多了会回调'
            }
    else:  # 低波动
        if trend > 0.01:  # 持续上涨
            state = 2  # 趋势
            name = 'TREND'
            params = {
                'buy_t': 0.15,      # 等跌15%才买（趋势中不轻易抄底）
                'sell_t': 0.15,     # 涨15%才卖（让利润奔跑）
                'pos_scale': 0.5,   # 降低仓位（趋势中不逆势）
                'note': 'EDA: 趋势是你的朋友'
            }
        else:
            state = 1
            name = 'EUPHORIA'
            params = {
                'buy_t': 0.05,
                'sell_t': 0.10,
                'pos_scale': 1.0,
                'note': '默认: 亢奋回调'
            }
    
    return state, name, params

# ===================== 趋势过滤器 (12%规则) =====================
def is_crash_continuation(data_history, current_idx):
    """
    检测是否处于"暴跌延续"模式
    基于EDA发现: 12%大跌后继续跌 (t=-6.16)
    """
    if current_idx < 10:
        return False
    
    # 检查最近10天的最大跌幅
    recent_10 = data_history[max(0, current_idx-10):current_idx]
    max_drop = 0
    for i in range(1, len(recent_10)):
        drop = (recent_10[i]['close'] - recent_10[i-1]['close']) / recent_10[i-1]['close']
        if drop < max_drop:
            max_drop = drop
    
    # 如果最近10天有超过-10%的跌幅，认为是暴跌模式
    return max_drop < -0.10

# ===================== V2.2 回测引擎 =====================
def run_v22_backtest(data, base_params, use_regime=True, use_trend_filter=True):
    shares = base_params['base_shares']
    total_pnl = 0.0
    total_trades = 0
    wins = 0; losses = 0
    max_drawdown = 0.0
    peak_equity = 0.0
    stop_count = 0; filter_count = 0
    
    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    
    trade_log = []
    regime_log = []
    
    for i, bar in enumerate(data):
        price = bar['close']
        prev_close = data[i-1]['close'] if i > 0 else price
        
        # 权益计算
        equity = shares * price
        if equity > peak_equity: peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown: max_drawdown = dd
        
        # 状态检测
        if use_regime and i >= 20:
            state, state_name, regime_params = detect_regime(data, i, window=20)
        else:
            state, state_name, regime_params = 1, 'EUPHORIA', None
        
        regime_log.append({
            'date': bar['date'][:10],
            'regime': state,
            'regime_name': state_name,
        })
        
        # 获取参数
        if use_regime and regime_params:
            sell_t = regime_params['sell_t']
            buy_t = regime_params['buy_t']
            pos_scale = regime_params['pos_scale']
        else:
            sell_t = base_params['sell_t']
            buy_t = base_params['buy_t']
            pos_scale = 1.0
        
        # =============== 涡轮A检查 ===============
        if turbo_a['active']:
            turbo_a['days'] += 1
            entry = turbo_a['entry']
            buyback = turbo_a['prev_close'] * (1 + base_params['a_offset'])
            
            # 止损检查
            stop_price = entry * (1 + base_params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_a['qty']
                total_pnl += pnl
                shares += turbo_a['qty']
                total_trades += 1
                stop_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_STOP', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': state_name
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 正常买回
            if price <= buyback:
                pnl = (entry - price) * turbo_a['qty']
                total_pnl += pnl
                shares += turbo_a['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_BACK', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': state_name
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查卖出信号
            sell_trigger = prev_close * (1 + sell_t)
            if price >= sell_trigger and shares > base_params['pos_min']:
                qty = min(int(base_params['trade_qty'] * pos_scale / 100) * 100,
                          shares - base_params['pos_min'])
                qty = max(100, qty)
                shares -= qty
                turbo_a = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'A_SELL', 'price': price, 'qty': qty, 'pnl': 0,
                    'date': bar['date'][:10], 'regime': state_name,
                    'note': f'sell_t={sell_t:.0%}'
                })
        
        # =============== 涡轮B检查 ===============
        if turbo_b['active']:
            turbo_b['days'] += 1
            entry = turbo_b['entry']
            sellback = turbo_b['prev_close'] * (1 + base_params['b_offset'])
            
            # 止损检查
            stop_price = entry * (1 - base_params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl
                shares -= turbo_b['qty']
                total_trades += 1
                stop_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_STOP', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': state_name
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 正常卖出
            if price >= sellback:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl
                shares -= turbo_b['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_SELL', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': state_name
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查买入信号
            buy_trigger = prev_close * (1 - buy_t)
            if price <= buy_trigger and shares < base_params['pos_max']:
                # 趋势过滤器检查
                if use_trend_filter and is_crash_continuation(data, i):
                    filter_count += 1
                    continue
                
                qty = min(int(base_params['trade_qty'] * pos_scale / 100) * 100,
                          base_params['pos_max'] - shares)
                qty = max(100, qty)
                shares += qty
                turbo_b = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'B_BUY', 'price': price, 'qty': qty, 'pnl': 0,
                    'date': bar['date'][:10], 'regime': state_name,
                    'note': f'buy_t={buy_t:.0%}'
                })
    
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    return {
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'final_shares': shares,
        'stop_count': stop_count,
        'filter_count': filter_count,
        'trade_log': trade_log[:20],  # 只保留前20条
        'regime_log': regime_log,
    }


def main():
    # 加载数据
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日 ({data[0]['date'][:10]} ~ {data[-1]['date'][:10]})")
    
    # V2基础参数
    V2_BASE = {
        'sell_t': 0.12, 'a_offset': -0.01, 'buy_t': 0.05, 'b_offset': 0.05,
        'trade_qty': 1000, 'pos_min': 7000, 'pos_max': 11000,
        'base_shares': 8894, 'stop_loss_pct': 0.05,
    }
    
    print("\n" + "="*70)
    print("  对比: V2原版 vs V2.2状态依赖策略")
    print("="*70)
    
    # V2原版回测
    print("\n[V2 原版] 无状态检测, 无趋势过滤")
    v2_result = run_v22_backtest(data, V2_BASE, use_regime=False, use_trend_filter=False)
    print(f"  盈亏=${v2_result['total_pnl']:,.2f} 交易={v2_result['total_trades']} "
          f"胜率={v2_result['win_rate']:.1f}% 回撤={v2_result['max_drawdown']:.2f}% "
          f"止损={v2_result['stop_count']}")
    
    # V2.2 完全版
    print("\n[V2.2 完全版] 状态检测 + 趋势过滤")
    v22_result = run_v22_backtest(data, V2_BASE, use_regime=True, use_trend_filter=True)
    print(f"  盈亏=${v22_result['total_pnl']:,.2f} 交易={v22_result['total_trades']} "
          f"胜率={v22_result['win_rate']:.1f}% 回撤={v22_result['max_drawdown']:.2f}% "
          f"止损={v22_result['stop_count']} 过滤={v22_result['filter_count']}")
    
    # 只用状态检测
    print("\n[V2.2 仅状态检测]")
    v22r_result = run_v22_backtest(data, V2_BASE, use_regime=True, use_trend_filter=False)
    print(f"  盈亏=${v22r_result['total_pnl']:,.2f} 交易={v22r_result['total_trades']} "
          f"胜率={v22r_result['win_rate']:.1f}% 回撤={v22r_result['max_drawdown']:.2f}%")
    
    # 只用趋势过滤
    print("\n[V2.2 仅趋势过滤]")
    v22t_result = run_v22_backtest(data, V2_BASE, use_regime=False, use_trend_filter=True)
    print(f"  盈亏=${v22t_result['total_pnl']:,.2f} 交易={v22t_result['total_trades']} "
          f"胜率={v22t_result['win_rate']:.1f}% 回撤={v22t_result['max_drawdown']:.2f}%")
    
    # 打印部分交易日志
    print("\n" + "="*70)
    print("  V2.2 交易明细 (前10笔)")
    print("="*70)
    for t in v22_result['trade_log'][:10]:
        print(f"  {t['date']} {t['type']:8s} @${t['price']:.2f} qty={t['qty']} "
              f"pnl={t['pnl']:>8.2f} [{t.get('regime','?')}] {t.get('note','')}")
    
    # 统计状态分布
    regime_counts = {}
    for r in v22_result['regime_log']:
        name = r['regime_name']
        regime_counts[name] = regime_counts.get(name, 0) + 1
    
    print("\n" + "="*70)
    print("  市场状态分布")
    print("="*70)
    for name, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
        print(f"  {name}: {count}天 ({count/len(v22_result['regime_log'])*100:.1f}%)")
    
    # 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'data_range': {'start': data[0]['date'], 'end': data[-1]['date'], 'bars': len(data)},
        'v2_baseline': {k: v for k, v in v2_result.items() if k not in ('trade_log','regime_log')},
        'v22_full': {k: v for k, v in v22_result.items() if k not in ('trade_log','regime_log')},
        'v22_regime_only': {k: v for k, v in v22r_result.items() if k not in ('trade_log','regime_log')},
        'v22_filter_only': {k: v for k, v in v22t_result.items() if k not in ('trade_log','regime_log')},
        'regime_distribution': regime_counts,
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v22_simple_backtest_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")


if __name__ == '__main__':
    main()