# -*- coding: utf-8 -*-
"""
新标的历史数据采集脚本
从富途OpenD下载CLSK/MARA/RIOT等标的的6个月分钟级K线数据
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import time

# UTF-8编码设置
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from futu import OpenQuoteContext, RET_OK, KLType, AuType
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    print("[ERROR] Futu API not installed. Run: pip install futu-api")
    sys.exit(1)

# 配置
FUTU_HOST = '127.0.0.1'
FUTU_PORT = 11111
DATA_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司\02_回测数据\history")
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 新标的列表 (美股比特币矿商 + 相关股)
NEW_TICKERS = [
    ('US.CLSK', 'CleanSpark', '比特币矿商'),
    ('US.MARA', 'Marathon Digital', '比特币矿商'),
    ('US.RIOT', 'Riot Platforms', '比特币矿商'),
    ('US.HUT', 'Hut 8 Mining', '比特币矿商'),
    ('US.CIFR', 'Cipher Mining', '比特币矿商'),
    ('US.WULF', 'TeraWulf', '比特币矿商'),
    ('US.COIN', 'Coinbase', '加密交易所'),
    ('US.MSTR', 'MicroStrategy', '比特币持有者'),
    ('US.CAN', 'Canaan', '矿机制造商'),
]

def download_kline(quote_ctx, code, name, ktype=KLType.K_DAY, days=180):
    """下载K线数据"""
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    start_str = start_date.strftime('%Y-%m-%d')
    end_str = end_date.strftime('%Y-%m-%d')
    
    print(f"[INFO] Downloading {code} ({name}) - {ktype} - {start_str} to {end_str}")
    
    ret_code, ret_msg, data = quote_ctx.request_history_kline(
        code,
        start=start_str,
        end=end_str,
        ktype=ktype,
        autype=AuType.QFQ
    )
    
    if ret_code != RET_OK:
        print(f"[ERROR] Failed to download {code}: {ret_msg}")
        return None
    
    # 富途OpenD v10.x API: 数据在ret_msg中返回
    if hasattr(ret_msg, 'shape') and ret_msg is not None:
        print(f"[OK] Downloaded {len(ret_msg)} rows for {code}")
        return ret_msg
    
    if data is not None and hasattr(data, 'shape'):
        print(f"[OK] Downloaded {len(data)} rows for {code}")
        return data
    
    print(f"[WARN] No data for {code}")
    return None

def save_data(data, code, ktype_name):
    """保存数据到CSV"""
    if data is None:
        return None
    if isinstance(data, bytes):
        print(f"[WARN] Data is bytes, cannot save")
        return None
    if not hasattr(data, 'shape'):
        print(f"[WARN] Data is not DataFrame")
        return None
    if len(data) == 0:
        return None
    
    # 文件名: CODE_KTYPE_YYYYMMDD.csv
    date_str = datetime.now().strftime('%Y%m%d')
    filename = f"{code.replace('.', '_')}_{ktype_name}_{date_str}.csv"
    filepath = DATA_DIR / filename
    
    data.to_csv(filepath, index=False, encoding='utf-8-sig')
    print(f"[OK] Saved to {filepath}")
    return filepath

def main():
    print("=" * 60)
    print("New Tickers History Data Download")
    print("=" * 60)
    print(f"Target directory: {DATA_DIR}")
    print(f"Tickers: {len(NEW_TICKERS)}")
    print()
    
    # 连接富途OpenD
    quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
    
    results = {
        'success': [],
        'failed': [],
        'empty': []
    }
    
    try:
        for code, name, sector in NEW_TICKERS:
            print(f"\n{'='*50}")
            print(f"Processing: {code} - {name} ({sector})")
            print(f"{'='*50}")
            
            # 下载日线数据
            daily_data = download_kline(quote_ctx, code, name, KLType.K_DAY, days=180)
            if daily_data is not None:
                saved = save_data(daily_data, code, 'DAILY')
                if saved:
                    results['success'].append((code, 'DAILY', len(daily_data)))
            else:
                results['failed'].append((code, 'DAILY'))
            
            time.sleep(0.5)  # 避免API限速
            
            # 下载分钟数据 (K_1M支持最大30天)
            min_data = download_kline(quote_ctx, code, name, KLType.K_1M, days=30)
            if min_data is not None:
                saved = save_data(min_data, code, '1MIN')
                if saved:
                    results['success'].append((code, '1MIN', len(min_data)))
            else:
                results['empty'].append((code, '1MIN'))
            
            time.sleep(0.5)
            
    finally:
        quote_ctx.close()
    
    # 汇总报告
    print("\n" + "=" * 60)
    print("DOWNLOAD SUMMARY")
    print("=" * 60)
    print(f"[OK] Success: {len(results['success'])} datasets")
    for code, ktype, rows in results['success']:
        print(f"  - {code} {ktype}: {rows} rows")
    
    if results['failed']:
        print(f"[FAIL] Failed: {len(results['failed'])}")
        for code, ktype in results['failed']:
            print(f"  - {code} {ktype}")
    
    if results['empty']:
        print(f"[EMPTY] No data: {len(results['empty'])}")
        for code, ktype in results['empty']:
            print(f"  - {code} {ktype}")
    
    print("\n[INFO] Data directory:", DATA_DIR)
    return results

if __name__ == '__main__':
    main()
