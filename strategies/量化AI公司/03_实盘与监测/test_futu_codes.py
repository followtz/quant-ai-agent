# -*- coding: utf-8 -*-
"""测试富途API美股代码格式"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from futu import OpenQuoteContext, RET_OK, KLType, AuType
from datetime import datetime, timedelta

FUTU_HOST = '127.0.0.1'
FUTU_PORT = 11111

# 测试不同代码格式
TEST_CODES = [
    'US.BTDR',      # 已知可用的美股
    'US.CLSK',      # 测试新标的
    'US.MARA',
    'US.RIOT',
    'US.COIN',
]

quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)

try:
    print("=" * 60)
    print("Testing Futu API US Stock Codes")
    print("=" * 60)
    
    for code in TEST_CODES:
        print(f"\nTesting: {code}")
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        ret_code, ret_msg, data = quote_ctx.request_history_kline(
            code,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            ktype=KLType.K_DAY,
            autype=AuType.QFQ
        )
        
        print(f"  ret_code: {ret_code}")
        print(f"  ret_msg: {ret_msg[:100] if isinstance(ret_msg, str) else ret_msg}")
        
        if ret_code == RET_OK:
            if hasattr(data, 'shape'):
                print(f"  data shape: {data.shape}")
                print(f"  columns: {list(data.columns) if hasattr(data, 'columns') else 'N/A'}")
                if len(data) > 0:
                    print(f"  last row: {data.iloc[-1].to_dict()}")
            else:
                print(f"  data type: {type(data)}")
                print(f"  data: {data[:200] if isinstance(data, (str, bytes)) else data}")
        else:
            print(f"  [FAIL] Error code: {ret_code}")

finally:
    quote_ctx.close()
    print("\n[OK] Connection closed")
