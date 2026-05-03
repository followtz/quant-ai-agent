# -*- coding: utf-8 -*-
"""
每日盘后自动数据下载脚本
收盘后自动下载当日分钟级数据和历史数据补全
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import time
import json

# UTF-8编码设置
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from futu import OpenQuoteContext, RET_OK, KLType, AuType
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    print("[ERROR] Futu API not installed")
    sys.exit(1)

# 配置
FUTU_HOST = '127.0.0.1'
FUTU_PORT = 11111
DATA_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司\02_回测数据\history")
LOG_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司\03_实盘与监测\logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 已实盘标的 + 备选标的
ALL_TICKERS = [
    # 已实盘
    ('US.BTDR', 'Bitdeer', '实盘'),
    ('HK.02598', 'LianLian Digital', '实盘'),
    # 备选标的
    ('US.CLSK', 'CleanSpark', '备选'),
    ('US.MARA', 'Marathon Digital', '备选'),
    ('US.RIOT', 'Riot Platforms', '备选'),
    ('US.HUT', 'Hut 8 Mining', '备选'),
    ('US.CIFR', 'Cipher Mining', '备选'),
    ('US.WULF', 'TeraWulf', '备选'),
    ('US.COIN', 'Coinbase', '备选'),
    ('US.MSTR', 'MicroStrategy', '备选'),
    ('US.CAN', 'Canaan', '备选'),
]

def download_today_kline(quote_ctx, code, name):
    """下载今日分钟数据"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    ret_code, ret_msg, data = quote_ctx.request_history_kline(
        code,
        start=today_str,
        end=today_str,
        ktype=KLType.K_1M,
        autype=AuType.QFQ
    )
    
    if ret_code != RET_OK or data is None or data.empty:
        return None
    
    return data

def save_daily_data(data, code):
    """保存每日数据"""
    if data is None or data.empty:
        return None
    
    date_str = datetime.now().strftime('%Y%m%d')
    filename = f"{code.replace('.', '_')}_1MIN_{date_str}.csv"
    filepath = DATA_DIR / filename
    
    data.to_csv(filepath, index=False, encoding='utf-8-sig')
    return filepath

def main():
    print("=" * 60)
    print(f"Daily Data Download - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    
    # 检查是否在交易时段后
    now = datetime.now()
    hour = now.hour
    
    # 美股收盘后 (北京时间 05:00 后) 或 手动运行
    if hour < 5:
        print("[INFO] Not yet US market close time (after 05:00 Beijing)")
        print("[INFO] Running anyway for manual trigger...")
    
    quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
    
    results = {'success': [], 'failed': []}
    
    try:
        for code, name, status in ALL_TICKERS:
            print(f"\n[INFO] Downloading {code} ({name}) - {status}")
            
            # 下载今日分钟数据
            data = download_today_kline(quote_ctx, code, name)
            
            if data is not None and len(data) > 0:
                saved = save_daily_data(data, code)
                if saved:
                    print(f"[OK] Saved {len(data)} rows to {saved}")
                    results['success'].append((code, len(data)))
            else:
                print(f"[WARN] No data for {code} (market closed or no trading)")
                results['failed'].append(code)
            
            time.sleep(0.3)  # 避免限速
            
    finally:
        quote_ctx.close()
    
    # 写入日志
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'success_count': len(results['success']),
        'failed_count': len(results['failed']),
        'details': results
    }
    
    log_file = LOG_DIR / f"daily_download_{datetime.now().strftime('%Y%m%d')}.json"
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"[OK] Success: {len(results['success'])} tickers")
    print(f"[FAIL] Failed: {len(results['failed'])} tickers")
    print(f"[INFO] Log saved to: {log_file}")
    
    return results

if __name__ == '__main__':
    main()
