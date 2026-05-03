# -*- coding: utf-8 -*-
"""
协同 PrevClose V2 实盘引擎
策略: 涡轮A+涡轮B协同 PrevClose偏移策略
- A卖出: prev_close * (1 + 12%)
- A买回: prev_close_A_sell_day * (1 - 1%)
- B买入: prev_close * (1 - 5%)
- B卖出: prev_close_B_buy_day * (1 + 5%)
- 协同平衡: 仓位<6000时B自动买入, 仓位>11000时A自动卖出
参数来源: C:/Trading/strategies/prev_close_v2.json
"""
import sys, time, json
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, r'C:\Users\Administrator\AppData\Local\Programs\FutuOpenD')
from futu import (OpenQuoteContext, OpenSecTradeContext,
                  RET_OK, TrdSide, OrderType, TrdEnv,
                  TrdMarket, SecurityFirm)

# ========== V2 策略参数 ==========
STOCK_CODE   = "US.BTDR"
TRADE_QTY    = 1000          # 每笔交易量
POLL_SEC     = 10            # 轮询间隔（秒）
DRY_RUN      = False         # False=实盘 True=模拟

# 涡轮A参数
SELL_T       = 0.12          # A卖出触发: 前收涨12%
A_OFFSET     = -0.01         # A买回偏移: 前收-1% (即更低价买回)
POS_MIN      = 7000          # 仓位硬下限
POS_MAX      = 11000         # 仓位硬上限
BAL_LOWER    = 7500          # 协同平衡下限: 仓位<此值B自动买入
BAL_UPPER    = 10500         # 协同平衡上限: 仓位>此值A自动卖出

# 涡轮B参数
BUY_T        = 0.05          # B买入触发: 前收跌5%
B_OFFSET     = 0.05          # B卖出偏移: 前收+5% (即更高价卖出)

# 起始持仓
BASE_SHARES  = 8894

# 账户
ACC_ID       = "281756477947279377"

DATA_DIR = Path("C:/Trading/data")
LOG_DIR  = Path("C:/Trading/logs")
DATA_DIR.mkdir(exist_ok=True); LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "prev_close_v2_state.json"

# ========== 日志 ==========
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = "[{}] {}".format(ts, msg)
    print(line)
    f = LOG_DIR / ("prev_close_v2_{}.log".format(date.today().strftime('%Y%m%d')))
    with open(f, 'a', encoding='utf-8') as lf:
        lf.write(line + '\n')

# ========== 状态持久化 ==========
def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except: pass
    return None

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

# ========== PrevClose V2 引擎 ==========
class PrevCloseV2Engine:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        time.sleep(1)

        if not dry_run:
            self.trade_ctx = OpenSecTradeContext(
                filter_trdmarket=TrdMarket.NONE,
                host='127.0.0.1', port=11111,
                security_firm=SecurityFirm.FUTUSECURITIES)
            time.sleep(1)
            log("[PrevClose V2启动] 实盘模式 S={}% Ao={}% Bo={}%".format(
                int(SELL_T*100), int(A_OFFSET*100), int(B_OFFSET*100)))
            self._verify_account()
        else:
            self.trade_ctx = None
            log("[PrevClose V2启动] 模拟模式")

        # 恢复状态
        saved = load_state()
        today_str = date.today().strftime('%Y-%m-%d')
        is_new_day = not (saved and saved.get('date') == today_str)

        if saved:
            self.tA = saved.get('turbo_A', {})
            self.tB = saved.get('turbo_B', {})
            self.today_pnl    = 0 if is_new_day else saved.get('pnl', 0)
            self.today_trades= 0 if is_new_day else saved.get('trades', 0)
            self.total_pnl   = saved.get('total_pnl', 0)
            self.total_trades= saved.get('total_trades', 0)
            self.last_close  = saved.get('last_close')
            self.current_shares = saved.get('shares', BASE_SHARES)
            if is_new_day:
                if self.tA.get('active'):
                    self.tA['days_held'] = 0
                if self.tB.get('active'):
                    self.tB['days_held'] = 0
                log("[跨日重置] {}涡轮A days=0 涡轮B days=0".format(saved.get('date')))
            log("[恢复] 涡轮A: {} | 涡轮B: {} | 持仓{} | 今日盈亏${:.2f}".format(
                self.tA, self.tB, self.current_shares, self.today_pnl))
        else:
            self.tA = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
            self.tB = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
            self.today_pnl=0; self.today_trades=0
            self.total_pnl=0; self.total_trades=0
            self.last_close=None; self.current_shares=BASE_SHARES
            log("[新交易日] 状态已重置")

        self.cur_price = 0
        self._init_last_close()

    def _verify_account(self):
        ret, f = self.trade_ctx.accinfo_query(trd_env=TrdEnv.REAL)
        if ret == RET_OK:
            power = float(f.iloc[0]['power'])
            log("[账户] 购买力=${:.2f} USD".format(power))

    def _init_last_close(self):
        if self.last_close is None:
            ret, df, _ = self.quote_ctx.request_history_kline(
                STOCK_CODE, start='2026-04-07', end='2026-04-09',
                ktype='K_DAY', autype='qfq')
            if ret == RET_OK and len(df) >= 1:
                self.last_close = float(df['close'].iloc[-1])
                log("[初始化] 昨日收盘=${:.2f}".format(self.last_close))
            else:
                self.last_close = 10.11
                log("[初始化] 使用参考价 $10.11")

    def _persist(self):
        save_state({
            'date'   : date.today().strftime('%Y-%m-%d'),
            'turbo_A': self.tA,
            'turbo_B': self.tB,
            'pnl'    : self.today_pnl,
            'trades' : self.today_trades,
            'total_pnl'   : self.total_pnl,
            'total_trades': self.total_trades,
            'last_close': self.last_close,
            'shares'  : self.current_shares,
        })

    def get_price(self):
        ret, data = self.quote_ctx.get_stock_quote([STOCK_CODE])
        if ret == RET_OK and len(data) > 0:
            p = float(data['last'].iloc[0])
            if p > 0:
                self.cur_price = p; return p
        ret2, data2 = self.quote_ctx.get_market_snapshot(STOCK_CODE)
        if ret2 == RET_OK and len(data2) > 0:
            p2 = float(data2['last_price'].iloc[0])
            if p2 > 0:
                self.cur_price = p2; return p2
        return self.cur_price if self.cur_price > 0 else None

    def _place_order(self, side, qty, price):
        if self.dry_run:
            log("[模拟下单] {} {}股 @${:.4f}".format(side, qty, price))
            return True, "DRY"
        for attempt in range(3):
            try:
                ret, data = self.trade_ctx.place_order(
                    price=round(price, 2), qty=qty, code=STOCK_CODE,
                    trd_side=side, order_type=OrderType.NORMAL, trd_env=TrdEnv.REAL)
                if ret == RET_OK:
                    oid = str(data.iloc[0]['order_id'])
                    sts = str(data.iloc[0]['order_status'])
                    log("[下单成功] {} {}股 @${:.4f} 订单:{} 状态:{}".format(side, qty, price, oid, sts))
                    return True, oid
                else:
                    log("[下单失败] {} {}股 @${:.4f} 重试({}): {}".format(side, qty, price, attempt+1, data))
                    time.sleep(2)
            except Exception as e:
                log("[下单异常] {} {}股 @${:.4f}: {}".format(side, qty, price, e))
                time.sleep(3)
        log("[下单放弃] {} {}股 @${:.4f}".format(side, qty, price))
        return False, "MAX_RETRIES"

    # ---- 涡轮A: 先卖后买 ----
    def check_turbo_A(self):
        # === 持仓中 → 检查买回 ===
        if self.tA['active']:
            days = self.tA['days_held'] + 1
            prev_close_A = self.tA['prev_close']          # 卖出日的前收
            buyback_target = prev_close_A * (1 + A_OFFSET)  # 前收-1%
            self.tA['days_held'] = days

            if self.cur_price <= buyback_target:
                qty = self.tA['pending_qty']
                entry = self.tA['entry_price']
                ok, _ = self._place_order(TrdSide.BUY, qty, self.cur_price)
                if ok:
                    pnl = (entry - self.cur_price) * qty
                    self.today_pnl += pnl; self.total_pnl += pnl
                    self.today_trades += 2; self.total_trades += 2
                    self.current_shares += qty
                    self.tA = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
                    self._persist()
                    log("[A买回] {}股@${:.4f} 目标<=${:.4f}(Ao={:.0%}) 持有{}天 盈亏${:+.2f}".format(
                        qty, self.cur_price, buyback_target, A_OFFSET, days, pnl))
                    return True
                else:
                    self.tA['days_held'] -= 1

        # === 待命 → 检查卖出 ===
        else:
            if self.current_shares <= POS_MIN:
                return False
            sell_trigger = self.last_close * (1 + SELL_T)  # 前收涨12%
            if self.cur_price >= sell_trigger:
                qty = min(TRADE_QTY, self.current_shares - POS_MIN)
                if qty <= 0: return False
                ok, _ = self._place_order(TrdSide.SELL, qty, self.cur_price)
                if ok:
                    self.tA = {'active':True,'entry_price':self.cur_price,
                               'pending_qty':qty,'days_held':0,
                               'prev_close':self.last_close}
                    self.current_shares -= qty
                    self._persist()
                    log("[A卖出] {}股@${:.4f} 触发>=${:.4f}(S={:.0%})".format(
                        qty, self.cur_price, sell_trigger, SELL_T))
                    return True

        # === 协同平衡: 仓位过低时B自动买入补位 ===
        if not self.tA['active'] and self.current_shares < BAL_LOWER and self.tB['active']:
            qty = min(TRADE_QTY, int(self.cur_price and 10000/self.cur_price or 1000))
            if qty > 0:
                ok, _ = self._place_order(TrdSide.BUY, qty, self.cur_price)
                if ok:
                    log("[A协同] 仓位{}<{} B买补位{}股@${:.4f}".format(
                        self.current_shares, BAL_LOWER, qty, self.cur_price))
                    self.current_shares += qty
                    self._persist()

        return False

    # ---- 涡轮B: 先买后卖 ----
    def check_turbo_B(self):
        # === 持仓中 → 检查卖出 ===
        if self.tB['active']:
            days = self.tB['days_held'] + 1
            prev_close_B = self.tB['prev_close']            # 买入日的前收
            sellback_target = prev_close_B * (1 + B_OFFSET)  # 前收+5%
            self.tB['days_held'] = days

            if self.cur_price >= sellback_target:
                qty = self.tB['pending_qty']
                entry = self.tB['entry_price']
                ok, _ = self._place_order(TrdSide.SELL, qty, self.cur_price)
                if ok:
                    pnl = (self.cur_price - entry) * qty
                    self.today_pnl += pnl; self.total_pnl += pnl
                    self.today_trades += 2; self.total_trades += 2
                    self.current_shares -= qty
                    self.tB = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
                    self._persist()
                    log("[B卖出] {}股@${:.4f} 目标>=${:.4f}(Bo=+{:.0%}) 持有{}天 盈亏${:+.2f}".format(
                        qty, self.cur_price, sellback_target, B_OFFSET, days, pnl))
                    return True
                else:
                    self.tB['days_held'] -= 1

        # === 待命 → 检查买入 ===
        else:
            if self.current_shares >= POS_MAX:
                return False
            buy_trigger = self.last_close * (1 - BUY_T)  # 前收跌5%
            if self.cur_price <= buy_trigger:
                qty = TRADE_QTY
                if self.current_shares + qty > POS_MAX:
                    qty = POS_MAX - self.current_shares
                if qty <= 0: return False
                ok, _ = self._place_order(TrdSide.BUY, qty, self.cur_price)
                if ok:
                    self.tB = {'active':True,'entry_price':self.cur_price,
                               'pending_qty':qty,'days_held':0,
                               'prev_close':self.last_close}
                    self.current_shares += qty
                    self._persist()
                    log("[B买入] {}股@${:.4f} 触发<=${:.4f}(B={:.0%})".format(
                        qty, self.cur_price, buy_trigger, BUY_T))
                    return True

        # === 协同平衡: 仓位过高时A自动卖出减位 ===
        if not self.tB['active'] and self.current_shares > BAL_UPPER and self.tA['active']:
            qty = min(TRADE_QTY, self.current_shares - POS_MIN)
            if qty > 0:
                ok, _ = self._place_order(TrdSide.SELL, qty, self.cur_price)
                if ok:
                    log("[B协同] 仓位{}>{} A卖减位{}股@${:.4f}".format(
                        self.current_shares, BAL_UPPER, qty, self.cur_price))
                    self.current_shares -= qty
                    self._persist()

        return False

    # ---- 收盘价更新 ----
    def update_last_close(self):
        import calendar
        today_d = date.today()
        for delta in range(1, 6):
            d = today_d - timedelta(days=delta)
            if d.weekday() < 5:
                end_d = d.strftime('%Y-%m-%d')
                ret, df, _ = self.quote_ctx.request_history_kline(
                    STOCK_CODE, start=end_d, end=end_d,
                    ktype='K_DAY', autype='qfq')
                if ret == RET_OK and len(df) >= 1:
                    new_close = float(df['close'].iloc[-1])
                    actual_date = str(df['time_key'].iloc[-1])[:10]
                    old = self.last_close
                    self.last_close = new_close
                    old_A = self.tA.get('days_held', 0)
                    old_B = self.tB.get('days_held', 0)
                    self.tA['days_held'] = 0
                    self.tB['days_held'] = 0
                    self.today_pnl = 0; self.today_trades = 0
                    self._persist()
                    log("[收盘更新] {} 收盘${:.2f}(原${:.2f}) A_days={}->0 B_days={}->0".format(
                        actual_date, new_close, old, old_A, old_B))
                    return
        log("[收盘更新失败]")

    def _report(self):
        DATA_DIR / "prev_close_v2_report.json"
        rpt = DATA_DIR / "prev_close_v2_report.json"
        rpt.write_text(json.dumps({
            'time'   : datetime.now().isoformat(),
            'price'  : self.cur_price,
            'pnl'    : self.today_pnl,
            'total_pnl': self.total_pnl,
            'trades' : self.today_trades,
            'total_trades': self.total_trades,
            'shares' : self.current_shares,
            'turbo_A': self.tA,
            'turbo_B': self.tB,
            'strategy': 'prev_close_v2',
            'params' : {
                'S': SELL_T, 'Ao': A_OFFSET, 'B': BUY_T, 'Bo': B_OFFSET,
                'qty': TRADE_QTY, 'pos_range': [POS_MIN, POS_MAX],
                'balance_range': [BAL_LOWER, BAL_UPPER]
            }
        }, ensure_ascii=False, indent=2), encoding='utf-8')

    # ---- 主循环 ----
    def run(self):
        log("="*65)
        log("  PrevClose V2 双涡轮引擎 - 协同 PrevClose 策略")
        log("  股票: {} | 参数: S={:.0%} Ao={:+.0%} B={:.0%} Bo={:+.0%}".format(
            STOCK_CODE, SELL_T, A_OFFSET, BUY_T, B_OFFSET))
        log("  每笔: {}股 | 仓位: {}-{} | 平衡: {}-{}".format(
            TRADE_QTY, POS_MIN, POS_MAX, BAL_LOWER, BAL_UPPER))
        log("  模式: {}".format('实盘 LIVE' if not self.dry_run else '模拟 SIM'))
        log("="*65)
        if self.last_close:
            log("昨收: ${:.4f}".format(self.last_close))
            log("A卖出>=${:.4f} | A买回<=${:.4f}".format(
                self.last_close*(1+SELL_T), self.last_close*(1+A_OFFSET)))
            log("B买入<=${:.4f} | B卖出>=${:.4f}".format(
                self.last_close*(1-BUY_T), self.last_close*(1+B_OFFSET)))
        log("-"*65)

        loop = 0
        while True:
            try:
                price = self.get_price()
                if price:
                    if loop % 6 == 0:
                        log("[V2态] 价${:.4f} 仓{} A:{} B:{} 今日${:+.2f} 总${:+.2f}".format(
                            price, self.current_shares,
                            '已卖' if self.tA['active'] else '待命',
                            '已买' if self.tB['active'] else '待命',
                            self.today_pnl, self.total_pnl))
                    self.check_turbo_A()
                    self.check_turbo_B()
                    self._persist()
                    self._report()

                time.sleep(POLL_SEC)
                loop += 1

                now = datetime.now()
                if now.hour == 5 and now.minute < 10:
                    self.update_last_close()
                    time.sleep(120)

            except KeyboardInterrupt:
                log("[停止] 用户中断")
                break
            except Exception as e:
                log("[错误] {}".format(e))
                time.sleep(30)


if __name__ == '__main__':
    engine = PrevCloseV2Engine(dry_run=DRY_RUN)
    engine.run()
