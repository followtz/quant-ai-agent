# -*- coding: utf-8 -*-
import json, warnings, numpy as np, pandas as pd
from pathlib import Path
warnings.filterwarnings('ignore')

DATA_DIR = Path('C:/Trading/data')
with open(DATA_DIR / 'btdr_daily_360d.json') as f:
    d = json.load(f)
df = pd.DataFrame(d)
df['date'] = pd.to_datetime(df['date'])
df = df.sort_values('date').reset_index(drop=True)
for col in ['open','high','low','close']:
    df[col] = pd.to_numeric(df[col], errors='coerce')
df = df.dropna(subset=['close','open']).reset_index(drop=True)
ps = df['close'].values.astype(float)
n = len(ps)
bh = round((ps[-1]/ps[0]-1)*100, 2)
print('Data: {} days, BH={}%'.format(n, bh))
print()

def run(n_bars, prices, sell_t, buy_t, A_offset, B_offset,
        pos_min=7000, pos_max=11000, bal_lower=7500, bal_upper=10500,
        p0=8894, cash0=200000.0, comm=0.001, slip=0.001):
    pos=p0; cash=cash0; tA=None; tB=None; pA=0.0; pB=0.0; cost=0.0; vol=0.0
    nA=0; nB=0; trades=0; log=[]
    for i in range(n_bars):
        p=float(prices[i])
        if i==0: continue
        prv=float(prices[i-1])
        # A sell
        if tA is None and pos>pos_min:
            if p>=prv*(1+sell_t):
                q=min(1000,pos-pos_min); sp=p*(1-slip)
                cash+=sp*q*(1-comm); cost+=sp*q*comm; vol+=sp*q; pos-=q; trades+=1
                tA=[sp,prv]; log.append(('A_sell',i,sp,q,prv,A_offset,sell_t))
        # A buyback
        if tA is not None:
            bt=tA[1]*(1+A_offset)
            if p<=bt:
                q=min(1000,int(cash/p))
                if q>0: bp=p*(1+slip); cash-=bp*q*(1+comm); cost+=bp*q*comm; pos+=q
                pA+=(tA[0]-bp)*q; nA+=1
                log.append(('A_buy',i,bp,q,tA[0]-bp,tA[1],bt,A_offset))
                tA=None
            elif pos<bal_lower:
                q=min(1000,int(cash/p))
                if q>0: bp2=p*(1+slip); cash-=bp2*q*(1+comm); cost+=bp2*q*comm; pos+=q
                trades+=1; log.append(('A_comp',i,bp2,q,0,tA[1],p,A_offset))
                if tB is None: tB=[bp2,prv]
        # B buy
        if tB is None and pos<pos_max:
            if p<=prv*(1-buy_t):
                q=min(1000,int(cash/p),pos_max-pos)
                if q>0: bp=p*(1+slip); cash-=bp*q*(1+comm); cost+=bp*q*comm; vol+=bp*q
                pos+=q; trades+=1; nB+=1; tB=[bp,prv]; log.append(('B_buy',i,bp,q,prv,B_offset,buy_t))
        # B sellback
        if tB is not None:
            st=tB[1]*(1+B_offset)
            if p>=st:
                q=min(1000,pos-pos_min)
                if q>0: sp=p*(1-slip); cash+=sp*q*(1-comm); cost+=sp*q*comm; pos-=q
                pB+=(sp-tB[0])*q; nB+=1
                log.append(('B_sell',i,sp,q,sp-tB[0],tB[1],st,B_offset))
                tB=None
            elif pos>bal_upper:
                q=min(1000,pos-pos_min)
                if q>0: sp=p*(1-slip); cash+=sp*q*(1-comm); cost+=sp*q*comm; pos-=q; trades+=1
                log.append(('B_comp',i,sp,q,0,tB[1],p,B_offset))
                if tA is None: tA=[sp,prv]
    gross=round(pA+pB); net=round(pA+pB-cost)
    fv=pos*float(prices[-1])+cash; sv=p0*float(prices[0])+cash0
    fills=[e for e in log if e[0] in('A_buy','B_sell')]
    wins=sum(1 for e in fills if e[4]>0)
    wr=wins/len(fills)*100 if fills else 0
    return {'sell_t':sell_t,'buy_t':buy_t,'A_offset':A_offset,'B_offset':B_offset,
            'trades':trades,'gross':gross,'cost':round(cost),'net':net,
            'excess':round((fv-sv)/sv*100-bh,3),'win_rate':round(wr,1),
            'na':nA,'nb':nB,'log':log,'bh':bh,'pos_final':pos,'cash_final':round(cash)}

# ============================================================
# PART 1: Config comparison
# ============================================================
print('='*72)
print('PART 1: 关键配置对比')
print('='*72)
print()
configs=[
    ('V1基准 S10%_Ao0%_Bo0%',  0.10, 0.05, 0.0,  0.0),
    ('直觉 S7%_Ao-3%_Bo+3%',   0.07, 0.05,-0.03, 0.03),
    ('优化 S12%_Ao-1%_Bo+5%',  0.12, 0.05,-0.01, 0.05),
    ('S12%_Ao0%_Bo+5%',        0.12, 0.05, 0.0,  0.05),
    ('S8%_Ao-2%_Bo+5%',        0.08, 0.05,-0.02, 0.05),
    ('S5%_Ao-2%_Bo+5%',        0.05, 0.05,-0.02, 0.05),
    ('S4%_Ao0%_Bo+5%',         0.04, 0.05, 0.0,  0.05),
    ('S3%_Ao-1%_Bo+5%',         0.03, 0.05,-0.01, 0.05),
]
print('{:<30} {:>5} {:>8} {:>6} {:>8} {:>8} {:>6}'.format(
    '配置','交易','毛利','佣金','净利','超额','胜率'))
print('-'*72)
results={}
for name,st,bt,ao,bo in configs:
    r=run(n,ps,st,bt,ao,bo)
    results[name]=r
    print('{:<30} {:>5} ${:>7,.0f} ${:>5,.0f} ${:>+7,.0f} {:>+7.3f}% {:>5.1f}%'.format(
        name, r['trades'], r['gross'], r['cost'], r['net'], r['excess'], r['win_rate']))

# ============================================================
# PART 2: Full grid top results
# ============================================================
print()
print('='*72)
print('PART 2: 全网格 Top-15 排名')
print('='*72)
sell_ts=[0.03,0.04,0.05,0.06,0.07,0.08,0.10,0.12]
A_offsets=[0.0,-0.01,-0.02,-0.03,-0.05]
B_offsets=[0.0,0.01,0.02,0.03,0.05]
all_results=[]
for st in sell_ts:
    for ao in A_offsets:
        for bo in B_offsets:
            r=run(n,ps,st,bt,ao,bo)
            r['name']='S{}%_Ao{}%_Bo{}%'.format(int(st*100),'+'if ao>=0 else''+str(int(ao*100)),'+'if bo>=0 else''+str(int(bo*100)))
            all_results.append(r)
all_sorted=sorted(all_results,key=lambda x:x['net'],reverse=True)
print()
print('{:<30} {:>5} {:>8} {:>6} {:>8} {:>8} {:>6}'.format(
    '配置','交易','毛利','佣金','净利','超额','胜率'))
print('-'*72)
for r in all_sorted[:15]:
    star='STAR' if r['net']>20000 else ('+' if r['net']>15000 else '')
    print('{:<30} {:>5} ${:>7,.0f} ${:>5,.0f} ${:>+7,.0f} {:>+7.3f}% {:>5.1f}% {}'.format(
        r['name'][:28], r['trades'], r['gross'], r['cost'], r['net'], r['excess'], r['win_rate'], star))

# ============================================================
# PART 3: Top config detailed trades
# ============================================================
print()
print('='*72)
print('PART 3: 最优配置 S12%_Ao-1%_Bo+5% 完整成交记录')
print('='*72)
best=all_sorted[0]
log=best['log']
a_all=[e for e in log if e[0] in('A_sell','A_buy','A_comp')]
b_all=[e for e in log if e[0] in('B_buy','B_sell','B_comp')]
print()
print('涡轮A ({}笔主动平仓):'.format(len([e for e in log if e[0]=='A_buy'])))
print('  {:<2} {:<10} {:>4} {:>7} {:>5} {:>9} {:>12} {}'.format(
    '#','类型','日','价格','数量','利润','目标价','备注'))
print('  '+'-'*65)
for j,e in enumerate(a_all):
    if e[0]=='A_sell':
        note='sell_t={:.0%}'.format(e[6])
        print('  {:<2} {:<10} {:>4} ${:>6.2f} {:>5} {:>9} prev=${:>6.2f} {}'.format(
            j+1,'A卖出',e[1],e[2],e[3],'-',e[4],note))
    elif e[0]=='A_buy':
        note='Ao={:+.0%}'.format(e[7]) if e[7]!=0 else 'prev_close'
        print('  {:<2} {:<10} {:>4} ${:>6.2f} {:>5} ${:>+8,.0f} target=${:>6.2f} {}'.format(
            j+1,'A买回',e[1],e[2],e[3],e[4],e[6],note))
    elif e[0]=='A_comp':
        print('  {:<2} {:<10} {:>4} ${:>6.2f} {:>5} ${:>+8,.0f} prev=${:>6.2f} balance'.format(
            j+1,'A协同',e[1],e[2],e[3],e[4],e[5]))

print()
print('涡轮B ({}笔主动平仓):'.format(len([e for e in log if e[0]=='B_sell'])))
print('  {:<2} {:<10} {:>4} {:>7} {:>5} {:>9} {:>12} {}'.format(
    '#','类型','日','价格','数量','利润','目标价','备注'))
print('  '+'-'*65)
for j,e in enumerate(b_all):
    if e[0]=='B_buy':
        note='buy_t={:.0%}'.format(e[6])
        print('  {:<2} {:<10} {:>4} ${:>6.2f} {:>5} {:>9} prev=${:>6.2f} {}'.format(
            j+1,'B买入',e[1],e[2],e[3],'-',e[4],note))
    elif e[0]=='B_sell':
        note='Bo={:+.0%}'.format(e[7]) if e[7]!=0 else 'prev_close'
        print('  {:<2} {:<10} {:>4} ${:>6.2f} {:>5} ${:>+8,.0f} target=${:>6.2f} {}'.format(
            j+1,'B卖出',e[1],e[2],e[3],e[4],e[6],note))
    elif e[0]=='B_comp':
        print('  {:<2} {:<10} {:>4} ${:>6.2f} {:>5} ${:>+8,.0f} prev=${:>6.2f} balance'.format(
            j+1,'B协同',e[1],e[2],e[3],e[4],e[5]))

# ============================================================
# PART 4: Key insights - B_offset analysis
# ============================================================
print()
print('='*72)
print('PART 4: 关键洞察 - B_offset 利润来源')
print('='*72)
print()
print('V1(B_offset=0%) vs S10%(B_offset=+5%):')
for bo,label in [(0.0,'Bo=0%'),(0.05,'Bo=+5%')]:
    r=run(n,ps,0.10,0.05,0.0,bo)
    b_sells=[e for e in r['log'] if e[0]=='B_sell']
    print()
    print('  B卖出明细 ({}) 总{}笔:'.format(label,len(b_sells)))
    for e in b_sells:
        prev_p=e[5]; target=e[6]; tpct=(target-prev_p)/prev_p*100
        print('    day={:>3} sell@${:.2f}  target=${:.2f}({:+.1f}%前收)  profit=${:+,.0f}'.format(
            e[1],e[2],target,tpct,e[4]))

print()
print('V1(A_offset=0%) vs S10%(A_offset=-1%):')
for ao,label in [(0.0,'Ao=0%'),(-0.01,'Ao=-1%')]:
    r=run(n,ps,0.10,0.05,ao,0.0)
    a_buys=[e for e in r['log'] if e[0]=='A_buy']
    print()
    print('  A买回明细 ({}) 总{}笔:'.format(label,len(a_buys)))
    for e in a_buys:
        prev_p=e[5]; target=e[6]; tpct=(target-prev_p)/prev_p*100
        print('    day={:>3} buy@${:.2f}  target=${:.2f}({:+.1f}%前收)  profit=${:+,.0f}'.format(
            e[1],e[2],target,tpct,e[4]))

# ============================================================
# PART 5: Phase analysis
# ============================================================
print()
print('='*72)
print('PART 5: 分阶段表现')
print('='*72)
phases=[(1,57,'Phase1 暴跌前'),(58,99,'Phase2 暴涨期'),(100,218,'Phase3 震荡下行'),(219,341,'Phase4 恢复期')]
print()
print('{:<20} {:>10} {:>10} {:>10} {:>10} {:>10}'.format('配置','Phase1','Phase2','Phase3','Phase4','全年'))
print('-'*72)
phase_results={}
for name,st,bt,ao,bo in configs:
    phase_pnl={}
    for s,e,label in phases:
        r=run(e,ps,st,bt,ao,bo)
        phase_pnl[label]=r['net']
    phase_results[name]=phase_pnl

for name,st,bt,ao,bo in configs:
    r=phase_results[name]
    total=r['Phase1 暴跌前']+r['Phase2 暴涨期']+r['Phase3 震荡下行']+r['Phase4 恢复期']
    print('{:<20} {:>+10,.0f} {:>+10,.0f} {:>+10,.0f} {:>+10,.0f} {:>+10,.0f}'.format(
        name[:18], r['Phase1 暴跌前'], r['Phase2 暴涨期'], r['Phase3 震荡下行'], r['Phase4 恢复期'], total))

# ============================================================
# PART 6: Comprehensive ranking
# ============================================================
print()
print('='*72)
print('PART 6: 综合推荐 (净利*0.4 + 频率*0.2 + 胜率*0.2 + 盈利安全*0.2)')
print('='*72)
HK=7.8
for r in all_sorted[:20]:
    r['score']=(
        min(r['net']/25000,1)*0.4 +
        min(r['trades']/20,1)*0.2 +
        r['win_rate']/100*0.2 +
        (1 if r['net']>15000 else 0.5 if r['net']>10000 else 0)*0.2
    )
final=sorted(all_sorted,key=lambda x:x['score'],reverse=True)
print()
print('{:<30} {:>5} {:>7} {:>8} {:>8} {:>5} {:>6} {}'.format(
    '配置','交易','净利$','净利HK','超额%','胜率','评分','推荐'))
print('-'*82)
for i,r in enumerate(final[:10]):
    net_hk=r['net']*HK
    star='STAR' if i<3 else ('+' if i<6 else '')
    print('{:<30} {:>5} ${:>6,.0f} ${:>+7,.0f} {:>+7.3f}% {:>5.1f}% {:>5.3f} {}'.format(
        r['name'][:28], r['trades'], r['net'], net_hk, r['excess'], r['win_rate'], r['score'], star))
print()
print('推荐: 综合评分Top3候选，需结合交易频率和鲁棒性人工判断')
print()
print('Top3 关键参数解读:')
for i,r in enumerate(final[:3]):
    print('  #{} {}'.format(i+1,r['name']))
    print('    涡轮A: 涨{:>4.0%}卖出 -> 买回触发=前收{:>+5.0%}'.format(r['sell_t'],r['A_offset']))
    print('    涡轮B: 跌{:>4.0%}买入 -> 卖出触发=前收{:>+5.0%}'.format(r['buy_t'],r['B_offset']))
    print('    净${:,}  交易{}笔  胜率{:>5.1f}%  超额{:>+6.3f}%'.format(
        r['net'],r['trades'],r['win_rate'],r['excess']))
    print()
