# -*- coding: utf-8 -*-
"""
V2.7 低波动标的模拟验证

目标：验证V2.7趋势跟随策略在低波动(<30%)标的上的表现

方法：
1. 用几何布朗运动(GBM)生成模拟价格序列
2. 参数：mu=0.0005(年化约12%), sigma=0.25(波动率25%)
3. 运行V2.7策略回测
4. 对比BTDR(93.4%波动率)的结果

预期：
- 回撤<-20%(vs BTDR的-56.86%)
- 盈亏保持合理水平
- 胜率提升
"""
import sys, json
from datetime import datetime, timedelta
import random
import math

WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)

# ===================== 模拟数据生成 =====================
def generate_gbm_prices(n_days=120, S0=100, mu=0.0005, sigma=0.25, seed=42):
    """
    用几何布朗运动(GBM)生成模拟价格
    dS = mu*S*dt + sigma*S*dW
    
    参数：
    - n_days: 交易日数
    - S0: 初始价格
    - mu: 日收益率均值(0.0005≈年化12%)
    - sigma: 波动率(0.25=25%, 0.934=93.4% BTDR)
    - seed: 随机种子
    """
    random.seed(seed)
    
    prices = [S0]
    data = []
    base_date = datetime(2026, 1, 1)
    
    for i in range(1, n_days+1):
        # GBM: S_t = S_{t-1} * exp((mu - sigma^2/2)*dt + sigma*sqrt(dt)*Z)
        dt = 1.0 / 252  # 交易日
        Z = random.gauss(0, 1)
        drift = (mu - 0.5 * sigma**2) * dt
        diffusion = sigma * math.sqrt(dt) * Z
        St = prices[-1] * math.exp(drift + diffusion)
        
        prices.append(St)
        
        # 构造OHLC数据
        daily_vol = sigma * math.sqrt(1.0/252)
        open_price = prices[-2]
        close_price = St
        high_price = max(open_price, close_price) * (1 + abs(random.gauss(0, daily_vol * 0.5)))
        low_price = min(open_price, close_price) * (1 - abs(random.gauss(0, daily_vol * 0.5)))
        
        date = (base_date + timedelta(days=i)).strftime('%Y-%m-%d')
        
        data.append({
            'date': date,
            'open': round(open_price, 2),
            'high': round(high_price, 2),
            'low': round(low_price, 2),
            'close': round(close_price, 2),
            'volume': random.randint(1000000, 5000000),
        })
    
    return data

# ===================== V2.7 BTDR趋势跟随策略（复制） =====================
def backtest_v27_strategy(data, params=None):
    """
    V2.7 回测引擎 - 低波动标的适配版
    
    策略规则：
    1. 底仓（参数可调）
    2. 突破前N日高点 → 加仓
    3. 跌破前N日低点 → 减仓
    4. 移动止盈：从最高价回撤X%
    """
    # 参数
    BASE = params or {}
    base_shares = BASE.get('base_shares', 6000)
    max_shares = BASE.get('max_shares', 11000)
    min_shares = BASE.get('min_shares', base_shares)
    breakout_days = BASE.get('breakout_days', 5)
    trailing_stop_pct = BASE.get('trailing_stop_pct', 0.03)
    position_size = BASE.get('position_size', 1000)
    stop_loss_pct = BASE.get('stop_loss_pct', 0.05)
    
    # 持仓状态
    shares = base_shares
    peak_price = data[0]['close']
    entry_price = data[0]['close']
    cash = 0.0
    
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
        
        # 更新最高价
        if price > peak_price:
            peak_price = price
        
        # 权益计算
        equity = shares * price + cash
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
        
        # =============== 策略逻辑 ===============
        
        # 1. 突破买入
        if price > prev_high and shares < max_shares:
            qty = min(position_size, max_shares - shares)
            qty = max(100, int(qty / 100) * 100)
            shares += qty
            cash -= qty * price
            entry_price = price
            trade_log.append({
                'type': 'BUY_BREAKOUT',
                'price': price,
                'qty': qty,
                'shares': shares,
                'date': bar['date'],
            })
        
        # 2. 破位卖出
        elif price < prev_low and shares > min_shares:
            qty = min(position_size, shares - min_shares)
            qty = max(100, int(qty / 100) * 100)
            shares -= qty
            cash += qty * price
            total_trades += 1
            pnl = qty * (price - entry_price)
            if pnl >= 0: wins += 1
            else: losses += 1
            trade_log.append({
                'type': 'SELL_BREAKDOWN',
                'price': price,
                'qty': qty,
                'pnl': round(pnl, 2),
                'shares': shares,
                'date': bar['date'],
            })
            entry_price = price
        
        # 3. 移动止盈
        elif peak_price > 0 and shares > base_shares:
            trailing_sell = peak_price * (1 - trailing_stop_pct)
            if price <= trailing_sell:
                qty = shares - base_shares
                qty = max(100, int(qty / 100) * 100)
                shares -= qty
                cash += qty * price
                total_trades += 1
                pnl = qty * (price - entry_price)
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'SELL_TRAILING',
                    'price': price,
                    'qty': qty,
                    'pnl': round(pnl, 2),
                    'shares': shares,
                    'date': bar['date'],
                    'peak': round(peak_price, 2),
                })
                peak_price = price
                entry_price = price
        
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
        'trade_log': trade_log[:20],
    }

# ===================== 对比测试 =====================
def compare_volatility():
    """对比不同波动率下的策略表现"""
    results = []
    
    # 测试不同波动率
    volatilities = [0.15, 0.20, 0.25, 0.30, 0.50, 0.934]  # 最后一个是BTDR
    labels = ['15% (很低)', '20% (低)', '25% (中低)', '30% (中)', '50% (高)', '93.4% (BTDR)']
    
    for vol, label in zip(volatilities, labels):
        print(f"\n  生成波动率 {label} 的模拟数据...")
        data = generate_gbm_prices(n_days=120, S0=100, sigma=vol, seed=42)
        
        # 参数：底仓随波动率调整（波动率高→底仓低）
        base_shares = 6000 if vol <= 0.30 else 4000
        
        params = {
            'base_shares': base_shares,
            'max_shares': 11000,
            'min_shares': base_shares,
            'breakout_days': 5,
            'trailing_stop_pct': 0.03,
            'position_size': 1000,
            'stop_loss_pct': 0.05,
        }
        
        result = backtest_v27_strategy(data, params)
        result['volatility'] = vol
        result['label'] = label
        result['params'] = params
        results.append(result)
        
        print(f"    盈亏: ${result['total_pnl']:,.2f}, 胜率: {result['win_rate']:.1f}%, 回撤: {result['max_drawdown']:.2f}%")
    
    return results

# ===================== 主函数 =====================
def main():
    print("="*70)
    print("  V2.7 低波动标的验证 - 波动率对比测试")
    print("="*70)
    print("  策略: V2.7趋势跟随（突破前高买入，移动止盈出场）")
    print("  目标: 验证低波动(<30%)标的能否降低回撤")
    
    results = compare_volatility()
    
    # 排序：按回撤（越小越好）
    results.sort(key=lambda x: x['max_drawdown'])
    
    print("\n" + "="*70)
    print("  波动率对比结果（按回撤排序）")
    print("="*70)
    print(f"  {'波动率':<15} {'底仓':<8} {'盈亏':<12} {'交易':<8} {'胜率':<8} {'回撤':<10}")
    print("  " + "-"*70)
    
    for r in results:
        print(f"  {r['label']:<15} {r['params']['base_shares']:>7} "
              f"${r['total_pnl']:>10,.2f} {r['total_trades']:>8} "
              f"{r['win_rate']:>7.1f}% {r['max_drawdown']:>9.2f}%")
    
    # 关键发现
    print("\n" + "="*70)
    print("  关键发现")
    print("="*70)
    
    low_vol = [r for r in results if r['volatility'] <= 0.30]
    btcr_result = [r for r in results if r['volatility'] == 0.934][0]
    
    if low_vol:
        avg_dd = sum(r['max_drawdown'] for r in low_vol) / len(low_vol)
        avg_pnl = sum(r['total_pnl'] for r in low_vol) / len(low_vol)
        avg_wr = sum(r['win_rate'] for r in low_vol) / len(low_vol)
        
        print(f"  低波动(<30%)平均回撤: {avg_dd:.2f}%")
        print(f"  低波动(<30%)平均盈亏: ${avg_pnl:,.2f}")
        print(f"  低波动(<30%)平均胜率: {avg_wr:.1f}%")
        print(f"\n  BTDR(93.4%)回撤: {btcr_result['max_drawdown']:.2f}%")
        print(f"  BTDR(93.4%)盈亏: ${btcr_result['total_pnl']:,.2f}")
        print(f"\n  回撤改善: {abs(btcr_result['max_drawdown']) - abs(avg_dd):.2f}%")
        
        if avg_dd > -20:
            print(f"\n  [成功] 低波动标的回撤降至-20%以下！")
        else:
            print(f"\n  [部分成功] 回撤从{btcr_result['max_drawdown']:.2f}%降至{avg_dd:.2f}%")
            print(f"  但仍需继续优化")
    
    # 推荐标的
    print("\n" + "="*70)
    print("  推荐标的（基于波动率）")
    print("="*70)
    print(f"  美股推荐:")
    print(f"    1. MSFT (微软) - 波动率~25%, 趋势强")
    print(f"    2. COST (好市多) - 波动率~22%, 趋势强")
    print(f"    3. BRK.B (伯克希尔) - 波动率~20%, 趋势中")
    print(f"\n  港股推荐:")
    print(f"    1. 00700 (腾讯) - 波动率~35%, 趋势强 (稍高但可接受)")
    print(f"    2. 00005 (汇丰) - 波动率~20%, 趋势弱")
    print(f"\n  建议: 优先测试 MSFT 或 COST")
    
    # 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'volatility_comparison': results,
        'summary': {
            'btcr_volatility': 0.934,
            'btcr_drawdown': btcr_result['max_drawdown'],
            'low_vol_avg_drawdown': avg_dd if low_vol else None,
            'improvement': abs(btcr_result['max_drawdown']) - abs(avg_dd) if low_vol else None,
        },
        'recommendations': {
            'us_stocks': ['MSFT', 'COST', 'BRK.B'],
            'hk_stocks': ['00700', '00005'],
            'priority': 'MSFT' if low_vol else None,
        }
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v27_low_volatility_test.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    main()