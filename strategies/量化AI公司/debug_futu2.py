# -*- coding: utf-8 -*-
from futu import OpenQuoteContext, OpenSecTradeContext, RET_OK, KLType, AuType
from datetime import datetime, timedelta

print("=== 1. K线数据 - 检查ret_code vs data ===")
ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
try:
    start_str = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    end_str = datetime.now().strftime('%Y-%m-%d')
    ret_code, ret_msg, data = ctx.request_history_kline(
        'HK.02598', start=start_str, end=end_str,
        ktype=KLType.K_DAY, autype=AuType.QFQ
    )
    print(f"ret={ret_code} RET_OK={RET_OK} data is None={data is None}")
    if data is not None:
        print(f"data shape={data.shape}, last date={data.iloc[-1]['time_key']}")
finally:
    ctx.close()

print()
print("=== 2. 实时行情报价 - 获取当前价格 ===")
ctx2 = OpenQuoteContext(host='127.0.0.1', port=11111)
try:
    ret, data = ctx2.get_stock_quote(['HK.02598'])
    print(f"get_stock_quote ret={ret}")
    if ret == RET_OK:
        print(data.to_string())
finally:
    ctx2.close()

print()
print("=== 3. 交易API可用方法 ===")
tctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
methods = [m for m in dir(tctx) if not m.startswith('_') and callable(getattr(tctx, m))]
for m in sorted(methods):
    print(f"  {m}")
tctx.close()

print()
print("=== 4. 尝试不同账户接口 ===")
tctx2 = OpenSecTradeContext(host='127.0.0.1', port=11111)
try:
    # 账户列表
    ret1, data1 = tctx2.get_acc_list()
    print(f"get_acc_list ret={ret1}")
    if ret1 == RET_OK:
        print(data1[['acc_id', 'trd_env', 'acc_type', 'acc_status']].to_string())

    # 用正确方式获取账户资金 - acc_list_query
    for _, row in data1.iterrows():
        if row['trd_env'] == 'REAL' and row['acc_status'] == 'ACTIVE':
            acc = row['acc_id']
            print(f"\n查询账户 {acc}:")
            ret2, data2 = tctx2.acc_list_query(trd_env=1)
            print(f"acc_list_query ret={ret2}")
            if ret2 == RET_OK:
                print(data2.to_string())
            # 持仓查询
            ret3, data3 = tctx2.position_list_query(trd_env=1, acc_id=acc)
            print(f"position_list_query ret={ret3}")
            if ret3 == RET_OK:
                if data3.empty:
                    print("无持仓")
                else:
                    print(data3.to_string())
finally:
    tctx2.close()
