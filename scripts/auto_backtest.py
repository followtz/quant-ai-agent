#!/usr/bin/env python3
"""
自动化回测 v1.0
使用 backtrader + Futu OpenD 数据，零LLM消耗

用法:
  python auto_backtest.py --symbol US.BTDR --days 90
  python auto_backtest.py --symbol HK.09611 --days 180 --strategy LianLian_V4
"""
import argparse, json, sys
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE))

def fetch_history(symbol: str, days: int):
    """从Futu OpenD获取历史数据"""
    from futu import OpenQuoteContext, KLType, AuType
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    ret, data = ctx.get_history_kline(symbol, start=(
        datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),
        ktype=KLType.K_DAY, autype=AuType.QFQ)
    ctx.close()
    if ret != 0 or data is None:
        return None
    return data.to_dict('records') if hasattr(data, 'to_dict') else data

def run_backtest(symbol: str, days: int, strategy_name: str):
    """使用 backtrader 回测"""
    import backtrader as bt
    import pandas as pd

    # 获取数据
    raw = fetch_history(symbol, days)
    if raw is None:
        return {"status": "error", "error": f"{symbol} 数据获取失败"}

    # 转换为DataFrame
    df = pd.DataFrame(raw)
    df['date'] = pd.to_datetime(df['time_key'])
    df.set_index('date', inplace=True)

    # 创建 Cerebro 引擎
    cerebro = bt.Cerebro()
    
    # 添加数据
    data = bt.feeds.PandasData(dataname=df)
    cerebro.adddata(data)

    # 添加策略
    from strategies.active.strategy_template import BaseStrategy
    cerebro.addstrategy(BaseStrategy)

    # 设置初始资金
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.001)  # 0.1%

    # 运行回测
    initial = cerebro.broker.getvalue()
    results = cerebro.run()
    final = cerebro.broker.getvalue()

    return {
        "status": "ok",
        "symbol": symbol,
        "days": days,
        "strategy": strategy_name,
        "initial_capital": initial,
        "final_capital": final,
        "return_pct": round((final - initial) / initial * 100, 2),
        "data_points": len(df),
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='自动化回测')
    parser.add_argument('--symbol', required=True, help='标的代码 e.g. US.BTDR')
    parser.add_argument('--days', type=int, default=90, help='回测天数')
    parser.add_argument('--strategy', default='BaseStrategy', help='策略名')
    args = parser.parse_args()

    result = run_backtest(args.symbol, args.days, args.strategy)
    
    # 保存结果
    out = WORKSPACE / "data" / "backtest_results" / f"{args.symbol}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, 'w') as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
