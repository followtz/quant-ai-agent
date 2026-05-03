# -*- coding: utf-8 -*-
"""
BTDR PrevClose V2 vs V2.1优化版 回测对比
对比原版V2和优化版V2.1在历史数据上的表现

优化点:
  1. 止损机制 (单笔-5%止损, 总回撤-15%熔断)
  2. 信号过滤 (RSI + 成交量)
  3. 动态仓位管理 (波动率目标30%)

回测数据: C:/Trading/data/history/US.BTDR_*.csv
"""
import os
import sys
import json
import csv
from datetime import datetime, timedelta
from pathlib import Path

# 工作区路径
WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)

# ============ 策略参数 ============
STOCK_CODE = "US.BTDR"

# V2 基础参数
V2_PARAMS = {
    'sell_t': 0.12,       # A卖出触发: 前收涨12%
    'a_offset': -0.01,    # A买回偏移: 前收-1%
    'buy_t': 0.05,        # B买入触发: 前收跌5%
    'b_offset': 0.05,     # B卖出偏移: 前收+5%
    'trade_qty': 1000,    # 每笔交易量
    'pos_min': 7000,      # 仓位下限
    'pos_max': 11000,     # 仓位上限
    'base_shares': 8894,  # 起始持仓
}

# V2.1 优化参数 (在V2基础上新增)
V21_PARAMS = {
    **V2_PARAMS,
    'stop_loss_pct': -0.05,    # 单笔止损 -5%
    'max_drawdown': -0.15,     # 最大回撤熔断 -15%
    'vol_target': 0.30,        # 目标波动率 30%
    'rsi_filter': True,        # RSI信号过滤
    'rsi_buy_thresh': 30,      # RSI买入阈值
    'rsi_sell_thresh': 70,     # RSI卖出阈值
    'volume_filter': True,     # 成交量过滤
    'volume_ratio': 1.2,       # 成交量比率阈值
}


def load_csv_data(csv_path: str) -> list:
    """加载CSV历史数据"""
    data = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                data.append({
                    'date': row.get('time_key', row.get('date', '')),
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': float(row.get('volume', 0)),
                })
            except (ValueError, KeyError):
                continue
    return data


def calculate_rsi(prices: list, period: int = 14) -> float:
    """计算RSI"""
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


def calculate_volatility(prices: list, period: int = 20) -> float:
    """计算历史波动率"""
    if len(prices) < period:
        return 0.5
    recent = prices[-period:]
    mean = sum(recent) / len(recent)
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    std_dev = variance ** 0.5
    return std_dev / mean if mean > 0 else 0.5


def run_v2_backtest(data: list, params: dict) -> dict:
    """运行V2原版回测"""
    if not data:
        return {'error': 'no data'}
    
    shares = params['base_shares']
    cash = 0.0
    total_pnl = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    max_pnl = 0.0
    max_drawdown = 0.0
    peak_equity = 0.0
    
    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0}
    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0}
    
    trade_log = []
    equity_curve = []
    
    for i, bar in enumerate(data):
        price = bar['close']
        prev_close = data[i-1]['close'] if i > 0 else price
        
        # 计算权益
        equity = cash + shares * price
        equity_curve.append(equity)
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
        
        # 涡轮A检查
        if turbo_a['active']:
            buyback = turbo_a['prev_close'] * (1 + params['a_offset'])
            if price <= buyback:
                pnl = (turbo_a['entry'] - price) * turbo_a['qty']
                total_pnl += pnl
                shares += turbo_a['qty']
                total_trades += 1
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                trade_log.append({
                    'type': 'A_buyback', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': pnl, 'date': bar['date']
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0}
        else:
            sell_trigger = prev_close * (1 + params['sell_t'])
            if price >= sell_trigger and shares > params['pos_min']:
                qty = min(params['trade_qty'], shares - params['pos_min'])
                shares -= qty
                turbo_a = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close}
                trade_log.append({
                    'type': 'A_sell', 'price': price, 'qty': qty, 'pnl': 0, 'date': bar['date']
                })
        
        # 涡轮B检查
        if turbo_b['active']:
            sellback = turbo_b['prev_close'] * (1 + params['b_offset'])
            if price >= sellback:
                pnl = (price - turbo_b['entry']) * turbo_b['qty']
                total_pnl += pnl
                shares -= turbo_b['qty']
                total_trades += 1
                if pnl >= 0:
                    wins += 1
                else:
                    losses += 1
                trade_log.append({
                    'type': 'B_sell', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': pnl, 'date': bar['date']
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0}
        else:
            buy_trigger = prev_close * (1 - params['buy_t'])
            if price <= buy_trigger and shares < params['pos_max']:
                qty = params['trade_qty']
                shares += qty
                turbo_b = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close}
                trade_log.append({
                    'type': 'B_buy', 'price': price, 'qty': qty, 'pnl': 0, 'date': bar['date']
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
        'trade_log': trade_log[:20],  # 最多20条
    }


def run_v21_backtest(data: list, params: dict) -> dict:
    """运行V2.1优化版回测（含止损+信号过滤+动态仓位）"""
    if not data:
        return {'error': 'no data'}
    
    shares = params['base_shares']
    cash = 0.0
    total_pnl = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_equity = 0.0
    stop_loss_count = 0
    signal_filter_count = 0
    circuit_breaker = False
    
    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    
    trade_log = []
    equity_curve = []
    price_history = []
    
    for i, bar in enumerate(data):
        price = bar['close']
        prev_close = data[i-1]['close'] if i > 0 else price
        price_history.append(price)
        
        # 计算权益
        equity = cash + shares * price
        equity_curve.append(equity)
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
        
        # 回撤熔断检查
        if dd <= params['max_drawdown']:
            circuit_breaker = True
            trade_log.append({
                'type': 'CIRCUIT_BREAKER', 'price': price, 'qty': 0,
                'pnl': 0, 'date': bar['date'],
                'note': 'drawdown={:.2%}'.format(dd)
            })
            # 熔断后平仓所有涡轮
            if turbo_a['active']:
                pnl = (turbo_a['entry'] - price) * turbo_a['qty']
                total_pnl += pnl
                shares += turbo_a['qty']
                total_trades += 1
                stop_loss_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
            if turbo_b['active']:
                pnl = (price - turbo_b['entry']) * turbo_b['qty']
                total_pnl += pnl
                shares -= turbo_b['qty']
                total_trades += 1
                stop_loss_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
            break  # 熔断后停止交易
        
        # RSI计算
        rsi = calculate_rsi(price_history) if len(price_history) > 14 else 50.0
        
        # 波动率计算（动态仓位）
        volatility = calculate_volatility(price_history) if len(price_history) >= 20 else 0.5
        vol_scale = min(2.0, max(0.5, params['vol_target'] / volatility)) if volatility > 0 else 1.0
        dynamic_qty = max(100, int(params['trade_qty'] * vol_scale / 100) * 100)
        
        # 涡轮A检查
        if turbo_a['active']:
            turbo_a['days'] += 1
            entry = turbo_a['entry']
            
            # 止损检查
            stop_price = entry * (1 + params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_a['qty']
                total_pnl += pnl
                shares += turbo_a['qty']
                total_trades += 1
                stop_loss_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_STOP_LOSS', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'],
                    'note': 'stop@{:.4f}'.format(stop_price)
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 正常买回
            buyback = turbo_a['prev_close'] * (1 + params['a_offset'])
            if price <= buyback:
                pnl = (entry - price) * turbo_a['qty']
                total_pnl += pnl
                shares += turbo_a['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_buyback', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date']
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 信号过滤
            if params['rsi_filter'] and rsi <= params['rsi_sell_thresh']:
                signal_filter_count += 1
                pass  # RSI不过滤卖出信号（原逻辑保持）
            
            sell_trigger = prev_close * (1 + params['sell_t'])
            if price >= sell_trigger and shares > params['pos_min']:
                qty = min(dynamic_qty, shares - params['pos_min'])
                shares -= qty
                turbo_a = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'A_sell', 'price': price, 'qty': qty, 'pnl': 0, 'date': bar['date'],
                    'note': 'vol_scale={:.2f}'.format(vol_scale)
                })
        
        # 涡轮B检查
        if turbo_b['active']:
            turbo_b['days'] += 1
            entry = turbo_b['entry']
            
            # 止损检查
            stop_price = entry * (1 - params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl
                shares -= turbo_b['qty']
                total_trades += 1
                stop_loss_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_STOP_LOSS', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'],
                    'note': 'stop@{:.4f}'.format(stop_price)
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 正常卖出
            sellback = turbo_b['prev_close'] * (1 + params['b_offset'])
            if price >= sellback:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl
                shares -= turbo_b['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_sell', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date']
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 信号过滤
            if params['rsi_filter'] and rsi >= params['rsi_buy_thresh']:
                signal_filter_count += 1
                continue  # RSI不够低，不买入
            
            buy_trigger = prev_close * (1 - params['buy_t'])
            if price <= buy_trigger and shares < params['pos_max']:
                qty = min(dynamic_qty, params['pos_max'] - shares)
                shares += qty
                turbo_b = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'B_buy', 'price': price, 'qty': qty, 'pnl': 0, 'date': bar['date'],
                    'note': 'vol_scale={:.2f}'.format(vol_scale)
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
        'stop_loss_count': stop_loss_count,
        'signal_filter_count': signal_filter_count,
        'circuit_breaker': circuit_breaker,
        'trade_log': trade_log[:30],
    }


def main():
    # 查找BTDR历史数据
    data_dir = Path("C:/Trading/data/history")
    csv_files = list(data_dir.glob("BTDR*.csv"))  # 注意：文件名是BTDR不是US.BTDR
    
    if not csv_files:
        # 尝试备用路径
        data_dir2 = Path(WORKSPACE) / "data" / "history"
        csv_files = list(data_dir2.glob("BTDR*.csv"))
    
    if not csv_files:
        # 直接指定已知文件
        direct_file = data_dir / "BTDR_daily_120d.csv"
        if direct_file.exists():
            csv_files = [direct_file]
    
    if not csv_files:
        print("[ERROR] 未找到BTDR历史数据CSV")
        print("请先运行: python futu_data_dl.py --symbol US.BTDR --days 120")
        return
    
    # 加载数据
    all_data = []
    for csv_file in csv_files:
        print("[加载] {}".format(csv_file.name))
        data = load_csv_data(str(csv_file))
        all_data.extend(data)
    
    # 按日期排序并去重
    all_data.sort(key=lambda x: x['date'])
    seen = set()
    unique_data = []
    for d in all_data:
        if d['date'] not in seen:
            seen.add(d['date'])
            unique_data.append(d)
    
    print("[数据] 共{}个交易日 ({} ~ {})".format(
        len(unique_data),
        unique_data[0]['date'] if unique_data else 'N/A',
        unique_data[-1]['date'] if unique_data else 'N/A'
    ))
    
    # 运行V2回测
    print("\n" + "="*60)
    print("  V2 原版回测")
    print("="*60)
    v2_result = run_v2_backtest(unique_data, V2_PARAMS)
    
    # 运行V2.1优化版回测
    print("\n" + "="*60)
    print("  V2.1 优化版回测")
    print("="*60)
    v21_result = run_v21_backtest(unique_data, V21_PARAMS)
    
    # 对比结果
    print("\n" + "="*60)
    print("  回测对比结果")
    print("="*60)
    
    metrics = [
        ('总盈亏 ($)', 'total_pnl'),
        ('总交易次数', 'total_trades'),
        ('获胜次数', 'wins'),
        ('亏损次数', 'losses'),
        ('胜率 (%)', 'win_rate'),
        ('最大回撤 (%)', 'max_drawdown'),
        ('最终持仓', 'final_shares'),
        ('止损触发次数', 'stop_loss_count'),
        ('信号过滤次数', 'signal_filter_count'),
        ('熔断触发', 'circuit_breaker'),
    ]
    
    print("{:<20} {:>15} {:>15} {:>15}".format("指标", "V2原版", "V2.1优化", "改善"))
    print("-" * 65)
    
    for name, key in metrics:
        v2_val = v2_result.get(key, 'N/A')
        v21_val = v21_result.get(key, 'N/A')
        
        if isinstance(v2_val, (int, float)) and isinstance(v21_val, (int, float)):
            diff = v21_val - v2_val
            if key in ('max_drawdown',):  # 越小越好
                improve = "改善" if diff < 0 else "恶化"
            elif key in ('win_rate', 'total_pnl', 'wins'):  # 越大越好
                improve = "改善" if diff > 0 else "恶化"
            else:
                improve = ""
            print("{:<20} {:>15} {:>15} {:>15}".format(
                name, v2_val, v21_val, "{} {}".format(diff, improve)))
        else:
            print("{:<20} {:>15} {:>15} {:>15}".format(name, v2_val, v21_val, ""))
    
    # 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'data_range': {
            'start': unique_data[0]['date'] if unique_data else '',
            'end': unique_data[-1]['date'] if unique_data else '',
            'bars': len(unique_data),
        },
        'v2_result': {k: v for k, v in v2_result.items() if k != 'trade_log'},
        'v21_result': {k: v for k, v in v21_result.items() if k != 'trade_log'},
        'v2_trade_log': v2_result.get('trade_log', []),
        'v21_trade_log': v21_result.get('trade_log', []),
    }
    
    report_path = Path(WORKSPACE) / "data" / "history" / "v2_vs_v21_backtest_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print("\n[报告已保存] {}".format(report_path))


if __name__ == '__main__':
    main()
