#!/usr/bin/env python3
"""
盘前简报自动生成器 (非LLM，直接调Futu API)
用法: python3 scripts/market_briefing.py [--hk] [--us]
"""
import argparse, json, sys
from datetime import datetime
from futu import *

def get_briefing(market="HK"):
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    report = {"time": datetime.now().strftime("%Y-%m-%d %H:%M"), "market": market}
    
    # 市场状态
    ret, state = ctx.get_global_state()
    if ret == 0 and state:
        report["status"] = dict(state)
    
    # 账户摘要
    try:
        tctx = OpenSecTradeContext(filter_trdmarket=TrdMarket.HK if market=="HK" else TrdMarket.US,
                                    host='127.0.0.1', port=11111, security_firm=SecurityFirm.FUTUSECURITIES)
        ret2, accs = tctx.get_acc_list()
        if ret2 == 0:
            for _, row in accs.iterrows():
                ret3, pos_data = tctx.get_position_list(acc_id=row["acc_id"])
                if ret3 == 0:
                    positions = []
                    for _, p in pos_data.iterrows():
                        positions.append({"code": p["code"], "qty": p["qty"], "cost": p["cost_price"], 
                                          "market_val": p["market_val"], "pl_ratio": p["pl_ratio"]})
                    report["positions"] = positions
                    report["total_market_val"] = sum(p["market_val"] for p in positions)
        tctx.close()
    except:
        report["trade_unlocked"] = False
    
    ctx.close()
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hk", action="store_true", help="港股")
    parser.add_argument("--us", action="store_true", help="美股")
    args = parser.parse_args()
    
    if args.hk:
        r = get_briefing("HK")
    elif args.us:
        r = get_briefing("US")
    else:
        r = get_briefing("HK")
        r_us = get_briefing("US")
        r.update({"us": r_us})
    
    print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    # 保存到 dashboard
    import os
    out = f"/home/ubuntu/.openclaw/workspace/data/dashboard/briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, "w") as f:
        json.dump(r, f, ensure_ascii=False, default=str)
    print(f"\n简报已保存: {out}")
