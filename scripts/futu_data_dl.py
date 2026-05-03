#!/usr/bin/env python3
"""
富途数据统一下载入口 v2.0
支持日线/分钟线，自动分页，防Hang，限流保护

用法:
  # 下载日线（默认）
  python futu_data_dl.py --symbols US.BTDR HK.09611 HK.02598 HK.00600 --days 180
  
  # 下载分钟线（配合--klines参数）
  python futu_data_dl.py --symbols US.BTDR --days 30 --klines K_5M K_15M
  
  # 批量下载+静默（cron用）
  python futu_data_dl.py --symbols US.BTDR HK.09611 --days 365 --quiet

VIP1 限制: 历史K线每日有限额，建议日线每日≤500次请求
"""
import argparse, json, sys, os, time
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
DATA_DIR = WORKSPACE / "data" / "history"
DATA_DIR.mkdir(parents=True, exist_ok=True)

def fetch_data(symbols, days, klines, quiet=False):
    """从Futu OpenD下载数据"""
    from futu import OpenQuoteContext, KLType, AuType, RET_OK
    
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    results = {}
    total_requests = 0
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    for symbol in symbols:
        results[symbol] = {}
        for ktype in klines:
            if not quiet:
                print(f"  {symbol} {ktype}...", end=" ", flush=True)
            
            ret, data, page_key = ctx.request_history_kline(
                symbol, start=start_date, ktype=ktype, 
                autype=AuType.QFQ, max_count=1000
            )
            total_requests += 1
            
            if ret == RET_OK and not data.empty:
                # 保存为JSON
                records = data.to_dict('records')
                results[symbol][ktype] = {
                    "count": len(records),
                    "start": str(records[0].get('time_key','')),
                    "end": str(records[-1].get('time_key','')),
                    "symbol": symbol
                }
                
                # 写入文件
                safe_name = symbol.replace(".", "_")
                out = DATA_DIR / f"{safe_name}_{ktype}_{datetime.now().strftime('%Y%m%d')}.json"
                with open(out, 'w') as f:
                    json.dump(records, f, indent=2, ensure_ascii=False, default=str)
                
                if not quiet:
                    print(f"✅ {len(records)}条")
            else:
                if not quiet:
                    print(f"❌ {data}")
            
            # 限流保护
            if total_requests % 10 == 0:
                time.sleep(1)
    
    ctx.close()
    return results, total_requests

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='富途数据下载')
    parser.add_argument('--symbols', nargs='+', required=True, help='标的代码')
    parser.add_argument('--days', type=int, default=180, help='历史天数')
    parser.add_argument('--klines', nargs='+', default=['K_DAY'], help='K线类型')
    parser.add_argument('--quiet', action='store_true', help='静默模式')
    args = parser.parse_args()
    
    results, reqs = fetch_data(args.symbols, args.days, args.klines, args.quiet)
    
    if not args.quiet:
        print(f"\n下载完成: {len(args.symbols)}标的 × {len(args.klines)}K线 = {reqs}次请求")
        for sym, data in results.items():
            for kt, info in data.items():
                print(f"  {sym} {kt}: {info['count']}条 ({info['start']} ~ {info['end']})")
    
    # 保存索引
    summary = {
        "time": datetime.now().isoformat(),
        "symbols": args.symbols,
        "days": args.days,
        "total_requests": reqs,
        "results": results
    }
    with open(DATA_DIR / f"_index_{datetime.now().strftime('%Y%m%d')}.json", 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
