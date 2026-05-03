# -*- coding: utf-8 -*-
from futu import OpenSecTradeContext, RET_OK, TrdEnv

print("=== 实盘账户详情 ===")
tctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
try:
    # 正确参数 - 用TrdEnv.REAL
    ret1, data1 = tctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=281756477947279377)
    print(f"accinfo_query ret={ret1}")
    if ret1 == RET_OK:
        print("账户资金:")
        print(data1.to_string())
    else:
        print(f"Error: {data1}")

    print()
    # 获取持仓
    ret2, data2 = tctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=281756477947279377)
    print(f"position_list_query ret={ret2}")
    if ret2 == RET_OK:
        if data2.empty:
            print("无持仓")
        else:
            print("持仓:")
            print(data2.to_string())
    else:
        print(f"Error: {data2}")

finally:
    tctx.close()
