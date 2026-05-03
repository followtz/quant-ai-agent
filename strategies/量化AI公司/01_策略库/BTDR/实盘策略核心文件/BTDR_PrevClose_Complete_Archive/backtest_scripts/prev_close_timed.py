# -*- coding: utf-8 -*-
"""
PrevClose + 时间限制混合策略回测
涡轮A: 卖出触发 → N天内跌回前日收盘价买回 → 超时强制市价买回
涡轮B: 买入触发 → N天内反弹至前日收盘价卖出 → 超时强制市价卖出
"""
import json, numpy as np, pandas as pd
from pathlib import Path
import warnings; warnings.filterwarnings('ignore')

DATA_DIR = Path("C:/Trading/data")

# ============================================================
# 加载数据
# ============================================================
with open(DATA_DIR / "btdr_daily_360d.json") as f:
    d = json.load(f)
df = pd.DataFrame(d)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
for col in ['open','high','low','close','volume']:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df = df.dropna(subset=['close','open']).reset_index(drop=True)
ps = df['close'].values.astype(float)
ops = df['open'].values.astype(float)
n = len(ps)
bh = round((ps[-1]/ps[0]-1)*100, 2)
print(f"Data: {n} days, BH={bh}%")

# ============================================================
# 回测引擎
# ============================================================
def run_bt_timed(prices, opens_arr, n_bars,
                  sell_t, buy_t, max_wait_A, max_wait_B,
                  comm=0.001, slip=0.0, p0=8894, c0=200000.0):
    pos=p0; cash=c0
    tA=[False,0.0,0.0,0.0,0]  # on, sell_price, prev_close, open, days_wait
    tB=[False,0.0,0.0,0.0,0]
    pA=0.0; pB=0.0; cost=0.0; vol=0.0; nA=0; nB=0
    nA_exp=0; nB_exp=0; trades=0; log=[]
    INF = 99999

    for i in range(n_bars):
        p=float(prices[i])
        if i==0: continue
        prv=float(prices[i-1])

        # ---- Turbo A: Sell High ----
        if not tA[0]:
            if p>=prv*(1+sell_t) and pos>7000:
                q=min(1000,pos-7000); sp=p*(1-slip); val=sp*q
                cash+=val-val*comm; cost+=val*comm; vol+=val; pos-=q; trades+=1
                tA=[True,sp,prv,p,0]
                log.append({'type':'A_sell','day':i,'price':sp,'qty':q,'cond':f'sell>{sell_t*100:.0f}%'})
        else:
            tA[4]+=1; wd=tA[4]
            # Buy back if: price drops to prev_close, OR time expires
            if p<=tA[2]:   # price <= prev_close
                q=min(1000,int(cash/p)); bp=p*(1+slip)
                if q>0:
                    val=bp*q; cash-=val+val*comm; cost+=val*comm; vol+=val; pos+=q
                    pA+=(tA[1]-bp)*q; nA+=1
                    log.append({'type':'A_buy_ok','day':i,'price':bp,'qty':q,
                                'profit':round((tA[1]-bp)*q),'wait':wd,'trigger':'prev_close'})
                tA=[False,0.0,0.0,0.0,0]
            elif wd>max_wait_A and max_wait_A<INF:  # expired
                q=min(1000,int(cash/p)); bp=p*(1+slip)
                if q>0:
                    val=bp*q; cash-=val+val*comm; cost+=val*comm; vol+=val; pos+=q
                    pA+=(tA[1]-bp)*q; nA+=1; nA_exp+=1
                    log.append({'type':'A_buy_exp','day':i,'price':bp,'qty':q,
                                'profit':round((tA[1]-bp)*q),'wait':wd,'trigger':'EXPIRED'})
                tA=[False,0.0,0.0,0.0,0]

        # ---- Turbo B: Buy Low ----
        if not tB[0]:
            if p<=prv*(1-buy_t) and pos<11000:
                q=min(1000,int(cash/p),11000-pos)
                if q>0:
                    bp=p*(1+slip); val=bp*q; cash-=val+val*comm
                    cost+=val*comm; vol+=val; pos+=q; trades+=1
                    tB=[True,bp,prv,p,0]
                    log.append({'type':'B_buy','day':i,'price':bp,'qty':q,'cond':f'buy<{buy_t*100:.0f}%'})
        else:
            tB[4]+=1; wd=tB[4]
            if p>=tB[2]:   # price >= prev_close
                q=min(1000,pos-7000); sp=p*(1-slip)
                if q>0:
                    val=sp*q; cash+=val-val*comm; cost+=val*comm; vol+=val; pos-=q
                    pB+=(sp-tB[1])*q; nB+=1
                    log.append({'type':'B_sell_ok','day':i,'price':sp,'qty':q,
                                'profit':round((sp-tB[1])*q),'wait':wd,'trigger':'prev_close'})
                tB=[False,0.0,0.0,0.0,0]
            elif wd>max_wait_B and max_wait_B<INF:
                q=min(1000,pos-7000); sp=p*(1-slip)
                if q>0:
                    val=sp*q; cash+=val-val*comm; cost+=val*comm; vol+=val; pos-=q
                    pB+=(sp-tB[1])*q; nB+=1; nB_exp+=1
                    log.append({'type':'B_sell_exp','day':i,'price':sp,'qty':q,
                                'profit':round((sp-tB[1])*q),'wait':wd,'trigger':'EXPIRED'})
                tB=[False,0.0,0.0,0.0,0]

    fv=pos*float(prices[-1])+cash; sv=p0*float(prices[0])+c0
    ret=(fv-sv)/sv*100
    bh2=(float(prices[-1])/float(prices[0])-1)*100
    return {
        'ret':round(ret,3),'excess':round(ret-bh2,3),
        'gross':round(pA+pB),'cost':round(cost),
        'net':round(pA+pB-cost),
        'pa':round(pA),'pb':round(pB),
        'na':nA,'nb':nB,
        'nA_exp':nA_exp,'nB_exp':nB_exp,
        'trades':trades,'vol':round(vol),'log':log,
        'final_pos':pos,'bh':round(bh2,2)
    }

# ============================================================
# A+3%基准（无时间限制）
# ============================================================
def run_a3_base(prices, opens_arr, n_bars, sell_t, buy_t, comm=0.001, slip=0.001, p0=8894, c0=200000.0):
    pos=p0; cash=c0; tA=[False,0.0,0.0,0.0]; tB=[False,0.0,0.0,0.0]
    pA=0.0; pB=0.0; cost=0.0; vol=0.0; nA=0; nB=0; trades=0
    for i in range(n_bars):
        p=float(prices[i])
        if i==0: continue
        prv=float(prices[i-1])
        if not tA[0]:
            if p>=prv*(1+sell_t) and pos>7000:
                q=min(1000,pos-7000); sp=p*(1-slip); val=sp*q
                cash+=val-val*comm; cost+=val*comm; vol+=val; pos-=q; trades+=1
                tA=[True,sp,prv,p]
        else:
            bp2=tA[2]*1.03  # A+3%
            if p<=bp2*(1+slip):
                q=min(1000,int(cash/(bp2*(1+slip))))
                if q>0:
                    val2=bp2*(1+slip)*q; cash-=val2+val2*comm
                    cost+=val2*comm; vol+=val2; pos+=q; pA+=(tA[1]-bp2*(1+slip))*q; nA+=1
                tA=[False,0.0,0.0,0.0]
        if not tB[0]:
            if p<=prv*(1-buy_t) and pos<11000:
                q=min(1000,int(cash/p),11000-pos)
                if q>0:
                    bp3=p*(1+slip); val=bp3*q; cash-=val+val*comm
                    cost+=val*comm; vol+=val; pos+=q; trades+=1; tB=[True,bp3,prv,p]
        else:
            sp2=tB[1]*1.02  # Bret2%
            if p>=sp2*(1-slip):
                q=min(1000,pos-7000)
                if q>0:
                    val2=sp2*(1-slip)*q; cash+=val2-val2*comm
                    cost+=val2*comm; vol+=val2; pos-=q; pB+=(sp2*(1-slip)-tB[1])*q; nB+=1
                tB=[False,0.0,0.0,0.0]
    fv=pos*float(prices[-1])+cash; sv=p0*float(prices[0])+c0
    return {'ret':round((fv-sv)/sv*100,3),'gross':round(pA+pB),'cost':round(cost),
            'net':round(pA+pB-cost),'na':nA,'nb':nB,'trades':nA+nB,'pa':round(pA),'pb':round(pB)}

# ============================================================
# PART 1: 全扫描
# ============================================================
print("="*72)
print("PART 1: PrevClose + 时间限制 全面扫描")
print("="*72)

time_limits = [1, 2, 3, 5, 10, 15, 20, 999]
trigger_configs = [(0.03,0.05,"S3%/B5%"), (0.04,0.05,"S4%/B5%"),
                   (0.05,0.05,"S5%/B5%"), (0.10,0.05,"S10%/B5%")]

print()
print(f"{'Trigger':<12} {'A_max':<8} {'B_max':<8} {'Trades':>6} {'Gross':>9} {'Cost':>7} {'Net':>9} {'Excess':>8} {'A_exp':>6} {'B_exp':>6}")
print("-"*80)

all_results = []
for sell_t, buy_t, tname in trigger_configs:
    print(f"\n=== {tname} ===")
    for mA in time_limits:
        for mB in time_limits:
            mALabel = "无限制" if mA==999 else f"{mA}天"
            mBLabel = "无限制" if mB==999 else f"{mB}天"
            r = run_bt_timed(ps, ops, n, sell_t, buy_t, mA, mB, comm=0.001, slip=0.001)
            r['tname']=tname; r['sell_t']=sell_t; r['buy_t']=buy_t
            r['maxA']=mA; r['maxB']=mB
            r['mALabel']=mALabel; r['mBLabel']=mBLabel
            all_results.append(r)
            base_str = "(BASELINE)" if mA==999 and mB==999 else ""
            print(f"  {mALabel:<6}/{mBLabel:<6} {r['trades']:>6} ${r['gross']:>8,.0f} ${r['cost']:>5,.0f} ${r['net']:>8,.0f} {r['excess']:>+7.3f}%  A:{nA_exp:=r['nA_exp']}/{r['na']:>2}  B:{nB_exp:=r['nB_exp']}/{r['nb']:>2}  {base_str}")

# ============================================================
# PART 2: Top 10 排名
# ============================================================
print()
print("="*72)
print("PART 2: Top 10 最佳配置")
print("="*72)

top10 = sorted([r for r in all_results if r['maxA']<=20 and r['maxB']<=20],
                key=lambda x: x['net'], reverse=True)[:10]

print()
print(f"{'#':<3} {'Trigger':<12} {'A_max':<8} {'B_max':<8} {'Trades':>6} {'Gross':>9} {'Net':>9} {'Excess':>8} {'A_exp':>8} {'B_exp':>8}")
print("-"*82)
for i, r in enumerate(top10):
    print(f"#{i+1:<2} {r['tname']:<12} A≤{r['mALabel']:<6} B≤{r['mBLabel']:<6} {r['trades']:>6} ${r['gross']:>8,.0f} ${r['net']:>8,.0f} {r['excess']:>+7.3f}%  A:{r['nA_exp']}/{r['na']}  B:{r['nB_exp']}/{r['nb']}")

# ============================================================
# PART 3: 最佳配置详细成交记录
# ============================================================
best = top10[0]
print()
print("="*72)
print(f"PART 3: 最优配置详细记录: {best['tname']}, A≤{best['mALabel']}, B≤{best['mBLabel']}")
print("="*72)

r = best
log = r['log']
print()
print(f"涡轮A 成交 ({r['na']}笔, expire={r['nA_exp']}笔):")
print(f"{'#':<3} {'类型':<12} {'日idx':>5} {'价格':>8} {'数量':>5} {'等待':>5} {'触发':<12} {'利润'}")
print("-"*65)
a_log = [x for x in log if 'A' in x['type']]
for i, e in enumerate(a_log):
    expire = "【过期】" if e['trigger']=='EXPIRED' else ""
    prof = f"${e.get('profit',0):>+7,.0f}" if 'profit' in e else ''
    print(f"{i+1:<3} {e['type']:<12} {e['day']:>5} ${e['price']:>7.2f} {e['qty']:>5} {e.get('wait',0):>4}d  {e['trigger']:<12} {prof} {expire}")

print()
print(f"涡轮B 成交 ({r['nb']}笔, expire={r['nB_exp']}笔):")
print(f"{'#':<3} {'类型':<12} {'日idx':>5} {'价格':>8} {'数量':>5} {'等待':>5} {'触发':<12} {'利润'}")
print("-"*65)
b_log = [x for x in log if 'B' in x['type']]
for i, e in enumerate(b_log):
    expire = "【过期】" if e['trigger']=='EXPIRED' else ""
    prof = f"${e.get('profit',0):>+7,.0f}" if 'profit' in e else ''
    print(f"{i+1:<3} {e['type']:<12} {e['day']:>5} ${e['price']:>7.2f} {e['qty']:>5} {e.get('wait',0):>4}d  {e['trigger']:<12} {prof} {expire}")

# ============================================================
# PART 4: 时间窗口分析（按A/B维度拆分）
# ============================================================
print()
print("="*72)
print("PART 4: A/B时间限制独立影响分析")
print("="*72)

# 固定B_max=5天，看不同A_max
print("\n固定 B_max=5天，不同 A_max 的表现:")
print(f"{'A_max':<10} {'Trades':>6} {'Net':>9} {'Excess':>8} {'A_exp':>7} {'A_profit':>10}")
print("-"*55)
for sell_t, buy_t, tname in [(0.05,0.05,"S5%/B5%")]:
    for mA in [1,3,5,10,20,999]:
        r = next(x for x in all_results if x['sell_t']==sell_t and x['buy_t']==buy_t and x['maxA']==mA and x['maxB']==5)
        a_exp_str = f"{r['nA_exp']}/{r['na']}" if r['na']>0 else "0"
        print(f"A≤{'无限制' if mA==999 else str(mA)+'天':<8} {r['trades']:>6} ${r['net']:>8,.0f} {r['excess']:>+7.3f}%  {a_exp_str:>6}  ${r['pa']:>+9,.0f}")

print("\n固定 A_max=5天，不同 B_max 的表现:")
print(f"{'B_max':<10} {'Trades':>6} {'Net':>9} {'Excess':>8} {'B_exp':>7} {'B_profit':>10}")
print("-"*55)
for sell_t, buy_t, tname in [(0.05,0.05,"S5%/B5%")]:
    for mB in [1,3,5,10,20,999]:
        r = next(x for x in all_results if x['sell_t']==sell_t and x['buy_t']==buy_t and x['maxA']==5 and x['maxB']==mB)
        b_exp_str = f"{r['nB_exp']}/{r['nb']}" if r['nb']>0 else "0"
        print(f"B≤{'无限制' if mB==999 else str(mB)+'天':<8} {r['trades']:>6} ${r['net']:>8,.0f} {r['excess']:>+7.3f}%  {b_exp_str:>6}  ${r['pb']:>+9,.0f}")

# ============================================================
# PART 5: 策略对比汇总
# ============================================================
print()
print("="*72)
print("PART 5: 策略对比（含富途真实成本）")
print("="*72)

USDHKD = 7.8
per_trade_hk = max(50,13.79*1000*0.001)+15+13.79*1000*0.001*0.5
per_trade_usd = per_trade_hk / USDHKD

# Best PrevClose timed configs
benchmarks = [
    ("PrevClose+5天 S5%/B5%", 0.05, 0.05, 5, 5),
    ("PrevClose+10天 S5%/B5%", 0.05, 0.05, 10, 10),
    ("PrevClose+3天 S3%/B5%", 0.03, 0.05, 3, 3),
    ("PrevClose无限制 S5%", 0.05, 0.05, 999, 999),
    ("A+3%_Bret2% S5% (基准)", None, None, None, None),
]

print()
print(f"{'策略':<32} {'交易':>5} {'毛PnL':>9} {'成本':>7} {'净PnL':>9} {'超额':>8}")
print("-"*75)
base_r = None
for label, st, bt, mA, mB in benchmarks:
    if st is None:
        r = run_a3_base(ps, ops, n, 0.05, 0.05, comm=0.001, slip=0.001)
    else:
        r = run_bt_timed(ps, ops, n, st, bt, mA, mB, comm=0.001, slip=0.001)
    hk = r['trades'] * per_trade_hk
    net_hk = r['gross'] - hk
    if base_r is None:
        base_r = r; delta_str = "(基准)"
    else:
        delta = net_hk - (base_r['gross'] - base_r['trades']*per_trade_hk)
        delta_str = f"{'+' if delta>0 else ''}{delta:,.0f}"
    flag = "STAR" if net_hk>0 else "LOSS"
    print(f"{label:<32} {r['trades']:>5} ${r['gross']:>8,.0f} ${hk:>5,.0f} ${net_hk:>8,.0f} {r['excess']:>+7.3f}%  {delta_str:>10}  {flag}")

# Save
out = DATA_DIR / "prev_close_timed.json"
save_data = [{k:v for k,v in r.items() if k!='log'} for r in all_results]
with open(out,'w') as f: json.dump(save_data,f,indent=2)
print(f"\nSaved {len(all_results)} results to {out}")
