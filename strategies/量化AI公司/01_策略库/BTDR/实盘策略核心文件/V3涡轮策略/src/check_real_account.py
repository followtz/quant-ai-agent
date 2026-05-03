# -*- coding: utf-8 -*-
"""查询实盘账户 - 正确方法：先解锁再查询"""
import sys
sys.path.insert(0, r'C:\Users\Administrator\AppData\Local\Programs\FutuOpenD')
from futu import OpenUSTradeContext, RET_OK, TrdEnv
import time

trd = OpenUSTradeContext('127.0.0.1', 11111)
time.sleep(1)

# Step 1: 解锁
print("Step 1: Unlocking...")
ret, result = trd.unlock_trade(password='100711', is_unlock=True)
print(f"  unlock ret: {ret}, result: {result}")

# Step 2: 查账户列表
print("\nStep 2: Account list after unlock...")
ret, acc_list = trd.get_acc_list()
real_acc_id = None
if ret == RET_OK:
    for _, row in acc_list.iterrows():
        acc_id = row['acc_id']
        trd_env = row['trd_env']
        status = row['acc_status']
        print(f"  {trd_env} account {acc_id}: {status}")
        if trd_env == 'REAL':
            real_acc_id = acc_id

# Step 3: 查询实盘资金
if real_acc_id:
    print(f"\nStep 3: Real account funds (acc_id={real_acc_id})...")
    ret, funds = trd.accinfo_query(trd_env=TrdEnv.REAL)
    if ret == RET_OK:
        key_fields = ['power', 'total_assets', 'cash', 'us_cash', 'market_val', 
                      'long_mv', 'short_mv', 'available_funds', 'unrealized_pl',
                      'realized_pl', 'maintenance_margin', 'initial_margin']
        for f in key_fields:
            if f in funds.columns:
                print(f"  {f}: {funds.iloc[0][f]}")
        
        # Save all fields
        all_info = funds.iloc[0].to_dict()
        import json
        with open(r'C:\Trading\data\real_account_info.json', 'w', encoding='utf-8') as fh:
            json.dump(all_info, fh, ensure_ascii=False, indent=2)
        print("\n  Saved to C:/Trading/data/real_account_info.json")
    else:
        print(f"  Error: {funds}")

    # Step 4: 查询实盘持仓
    print(f"\nStep 4: Real account positions...")
    ret, pos = trd.position_list_query(trd_env=TrdEnv.REAL)
    if ret == RET_OK:
        if len(pos) > 0:
            for _, row in pos.iterrows():
                print(f"  {row.get('code', 'N/A')}: qty={row.get('qty', 'N/A')}, "
                      f"cost={row.get('cost_price', 'N/A')}, mv={row.get('market_val', 'N/A')}, "
                      f"pl={row.get('unrealized_pl', 'N/A')}, pl_ratio={row.get('pl_ratio', 'N/A')}")
        else:
            print("  No positions")
    else:
        print(f"  Error: {pos}")
    
    # Step 5: 计算买入能力
    print(f"\nStep 5: Buy capacity...")
    if ret == RET_OK and len(funds) > 0:
        power = float(funds.iloc[0].get('power', 0))
        total_assets = float(funds.iloc[0].get('total_assets', 0))
        cash = float(funds.iloc[0].get('us_cash', 0))
        
        # 获取当前BTDR价格
        from futu import OpenQuoteContext
        quote = OpenQuoteContext('127.0.0.1', 11111)
        time.sleep(0.5)
        ret2, q = quote.get_stock_quote(["US.BTDR"])
        if ret2 == RET_OK and len(q) > 0:
            cur_price = float(q['last'].iloc[0])
            print(f"  Current BTDR price: ${cur_price:.2f}")
            print(f"  Buying power: ${power:,.2f}")
            print(f"  Max shares can buy: {int(power / cur_price):,}")
            print(f"  With 1000 shares: ${cur_price * 1000:,.2f} needed")
            print(f"  With 2000 shares: ${cur_price * 2000:,.2f} needed")
        quote.close()
else:
    print("No real account found!")

trd.close()
