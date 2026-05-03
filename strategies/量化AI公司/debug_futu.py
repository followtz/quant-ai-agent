# -*- coding: utf-8 -*-
from futu import OpenQuoteContext, OpenSecTradeContext, RET_OK, KLType, AuType
from datetime import datetime, timedelta

print("=" * 60)
print("1. K线数据获取测试")
print("=" * 60)
ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
try:
    start_str = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    end_str = datetime.now().strftime('%Y-%m-%d')
    print(f"Request: {start_str} -> {end_str}")

    ret_code, ret_msg, data = ctx.request_history_kline(
        'HK.02598',
        start=start_str,
        end=end_str,
        ktype=KLType.K_DAY,
        autype=AuType.QFQ
    )

    print(f"ret_code = {ret_code!r}  (type={type(ret_code).__name__})")
    print(f"RET_OK = {RET_OK!r} (type={type(RET_OK).__name__})")
    print(f"ret_code == RET_OK: {ret_code == RET_OK}")
    print(f"ret_code == 0: {ret_code == 0}")
    print(f"ret_msg: {ret_msg!r}")
    print(f"data is None: {data is None}")
    if data is not None:
        print(f"data shape: {data.shape}")
        print(f"columns: {list(data.columns)}")
        print("Last 3 rows:")
        print(data.tail(3).to_string())
finally:
    ctx.close()

print()
print("=" * 60)
print("2. 实盘账户余额 (acc_id=281756477947279377)")
print("=" * 60)
tctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
try:
    # 获取账户资金
    ret2, data2 = tctx.get_account_info(trd_env=1, acc_id=281756477947279377)
    print(f"get_account_info ret={ret2}")
    if ret2 == RET_OK:
        print(data2.to_string())
    else:
        print(f"Error: {data2}")

    print()
    # 获取持仓
    ret3, data3 = tctx.position_list_query(trd_env=1, acc_id=281756477947279377)
    print(f"position_list_query ret={ret3}")
    if ret3 == RET_OK:
        if data3.empty:
            print("无持仓")
        else:
            print(data3.to_string())
    else:
        print(f"Error: {data3}")
finally:
    tctx.close()
