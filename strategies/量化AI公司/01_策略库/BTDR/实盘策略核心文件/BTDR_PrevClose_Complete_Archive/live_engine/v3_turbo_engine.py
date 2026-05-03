# -*- coding: utf-8 -*-
"""
双涡轮策略 V3 实盘引擎
- 策略: 渐进式阈值 + 动态阈值调整 + 无强制平仓
- 逻辑来源: force_close_v3.py -> S2_GradualDynamic 回测最优方案
- 实盘模式
"""
import sys
import time
import json
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, r'C:\Users\Administrator\AppData\Local\Programs\FutuOpenD')

from futu import (OpenQuoteContext, OpenSecTradeContext,
                  RET_OK, TrdSide, OrderType, TrdEnv,
                  TrdMarket, SecurityFirm)

# ========== 策略参数 ==========
STOCK_CODE    = "US.BTDR"
BASE_SHARES   = 8894          # 实测底仓
TRADE_QTY     = 1000          # 每笔交易量
POLL_SEC      = 10            # 轮询间隔（秒）

# 基础阈值
BASE_THRESHOLD = 0.05        # 5% 基础阈值

# 渐进式阈值折扣 (持仓天数 -> 折扣系数)
GRADUAL_DAYS     = [3, 5, 7]
GRADUAL_DISCOUNT = [0.6, 0.4, 0.2]

# 动态阈值参数
USE_DYNAMIC    = True
DYN_MIN        = 0.02         # 动态阈值最低2%
TARGET_SHARES  = 9000         # 目标持仓（中间值）
MIN_SHARES     = 7000         # 持仓下限（低于此A不卖，B可买）
MAX_SHARES     = 11000        # 持仓上限（高于此A可卖，B不买）

# 账户配置（主账户自动选取）
ACC_ID         = "281756477947279377"

DATA_DIR = Path("C:/Trading/data")
LOG_DIR  = Path("C:/Trading/logs")
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "v3_live_state.json"

# ========== 日志 ==========
def log(msg, to_file=True):
    ts = datetime.now().strftime('%H:%M:%S')
    line = "[%s] %s" % (ts, msg)
    print(line)
    if to_file:
        f = LOG_DIR / ("v3_live_%s.log" % date.today().strftime('%Y%m%d'))
        with open(f, 'a', encoding='utf-8') as lf:
            lf.write(line + '\n')

# ========== 状态持久化 ==========
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception:
            pass
    return None

def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding='utf-8')

# ========== 阈值计算 ==========
def _get_gradual_discount(days_held: int) -> float:
    """根据持仓天数返回渐进式折扣系数"""
    for d, disc in zip(sorted(GRADUAL_DAYS, reverse=True),
                       [GRADUAL_DISCOUNT[i] for i in range(len(GRADUAL_DAYS))]):
        if days_held >= d:
            return disc
    return 1.0

def _get_dynamic_base(shares: int) -> float:
    """根据持仓偏离度返回动态基础阈值"""
    if not USE_DYNAMIC:
        return BASE_THRESHOLD
    mid = (MIN_SHARES + MAX_SHARES) / 2.0
    range_half = (MAX_SHARES - MIN_SHARES) / 2.0
    deviation = (shares - mid) / range_half  # -1 to +1
    if abs(deviation) > 0.3:
        reduction = min(abs(deviation) * 0.03, BASE_THRESHOLD - DYN_MIN)
        return BASE_THRESHOLD - reduction
    return BASE_THRESHOLD

def _get_A_thresholds(shares: int, days_held: int):
    """涡轮A: 卖出用原始阈值，买回用渐进折扣"""
    base = _get_dynamic_base(shares)
    discount = _get_gradual_discount(days_held)
    sell_t = BASE_THRESHOLD           # 卖出: 原始5%
    buy_t  = base * discount          # 买回: 动态折扣
    return sell_t, buy_t

def _get_B_thresholds(shares: int, days_held: int):
    """涡轮B: 买入用原始阈值，卖出用渐进折扣"""
    base = _get_dynamic_base(shares)
    discount = _get_gradual_discount(days_held)
    buy_t  = BASE_THRESHOLD           # 买入: 原始5%
    sell_t = base * discount          # 卖出: 动态折扣
    return buy_t, sell_t

# ========== V3 引擎 ==========
class V3Engine:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        time.sleep(1)

        if not dry_run:
            # 关键: 用 OpenSecTradeContext + filter_trdmarket=TrdMarket.NONE
            self.trade_ctx = OpenSecTradeContext(
                filter_trdmarket=TrdMarket.NONE,
                host='127.0.0.1', port=11111,
                security_firm=SecurityFirm.FUTUSECURITIES)
            time.sleep(1)
            log("[V3启动] 实盘模式 渐进式+动态阈值(无强制)")
            self._verify_account()
        else:
            self.trade_ctx = None
            log("[V3启动] 模拟模式")

        # 恢复状态
        saved = load_state()
        today_str = date.today().strftime('%Y-%m-%d')

        # 检查是否跨日：如果 state 日期和今天不一致，重置每日数据
        is_new_day = not (saved and saved.get('date') == today_str)

        if saved:
            self.tA = saved.get('turbo_A', {})
            self.tB = saved.get('turbo_B', {})
            self.today_pnl    = 0 if is_new_day else saved.get('pnl', 0)
            self.today_trades = 0 if is_new_day else saved.get('trades', 0)
            self.last_close  = saved.get('last_close')
            self.current_shares = saved.get('shares', BASE_SHARES)

            # 跨日：重置每日计数器和涡轮持仓天数
            if is_new_day:
                if self.tA.get('active'):
                    self.tA['days_held'] = 0  # 继续持有，重新从0计算天数
                if self.tB.get('active'):
                    self.tB['days_held'] = 0
                log("[V3跨日重置] 日期%s → %s 涡轮A days_held=0 涡轮B days_held=0" % (
                    saved.get('date'), today_str))
            log("[V3恢复] 涡轮A: %s | 涡轮B: %s | 今日盈亏: $%.2f" % (
                self.tA, self.tB, self.today_pnl))
        else:
            self.tA = {'active': False, 'entry_price': 0, 'pending_qty': 0, 'days_held': 0}
            self.tB = {'active': False, 'entry_price': 0, 'pending_qty': 0, 'days_held': 0}
            self.today_pnl    = 0
            self.today_trades = 0
            self.last_close  = None
            self.current_shares = BASE_SHARES
            log("[V3新交易日] 状态已重置")

        self.cur_price = 0
        self._init_last_close()

    def _verify_account(self):
        """验证账户连接"""
        ret, f = self.trade_ctx.accinfo_query(trd_env=TrdEnv.REAL)
        if ret == RET_OK:
            power = float(f.iloc[0]['power'])
            log("[账户] 购买力=$%.2f USD" % power)
        else:
            log("[账户警告] 无法获取账户信息: %s" % f)

    def _init_last_close(self):
        """初始化昨日收盘价"""
        if self.last_close is None:
            ret, df, _ = self.quote_ctx.request_history_kline(
                STOCK_CODE, start='2026-04-07', end='2026-04-09',
                ktype='K_DAY', autype='qfq')
            if ret == RET_OK and len(df) >= 1:
                self.last_close = float(df['close'].iloc[-1])
                log("[初始化] 昨日收盘价: $%.2f" % self.last_close)
            else:
                self.last_close = 10.11
                log("[初始化] 用最新价 $10.11 作为参考")

    def _persist(self):
        save_state({
            'date'    : date.today().strftime('%Y-%m-%d'),
            'turbo_A' : self.tA,
            'turbo_B' : self.tB,
            'pnl'     : self.today_pnl,
            'trades'  : self.today_trades,
            'last_close': self.last_close,
            'shares'  : self.current_shares,
        })

    # ---- 获取实时价格 ----
    def get_price(self):
        # 优先用 get_stock_quote，失败则用 get_market_snapshot
        ret, data = self.quote_ctx.get_stock_quote([STOCK_CODE])
        if ret == RET_OK and len(data) > 0:
            p = float(data['last'].iloc[0])
            if p > 0:
                self.cur_price = p
                return p
        # Fallback: get_market_snapshot
        ret2, data2 = self.quote_ctx.get_market_snapshot(STOCK_CODE)
        if ret2 == RET_OK and len(data2) > 0:
            p2 = float(data2['last_price'].iloc[0])
            if p2 > 0:
                self.cur_price = p2
                return p2
        return self.cur_price if self.cur_price > 0 else None

    def _place_order(self, side, qty, price):
        """真实下单，返回 (success, order_id_or_error)"""
        if self.dry_run:
            log("[下单模拟] %s %d股 @$%.4f" % (side, qty, price))
            return True, "DRY_RUN"
        for attempt in range(3):
            try:
                ret, data = self.trade_ctx.place_order(
                    price=round(price, 2),
                    qty=qty,
                    code=STOCK_CODE,
                    trd_side=side,
                    order_type=OrderType.NORMAL,
                    trd_env=TrdEnv.REAL)
                if ret == RET_OK:
                    order_id = str(data.iloc[0]['order_id'])
                    status   = str(data.iloc[0]['order_status'])
                    log("[下单成功] %s %d股 @$%.4f 订单:%s 状态:%s" % (side, qty, price, order_id, status))
                    return True, order_id
                else:
                    log("[下单失败重试] %s %d股 @$%.4f 错误:%s" % (side, qty, price, data))
                    time.sleep(2)
            except Exception as e:
                log("[下单异常] %s %d股 @$%.4f 异常:%s" % (side, qty, price, e))
                time.sleep(3)
        log("[下单放弃] %s %d股 @$%.4f" % (side, qty, price))
        return False, "MAX_RETRIES"

    # ---- 涡轮A: 先卖后买 ----
    def check_turbo_A(self):
        """A策略: 底仓足够时涨卖跌买，底仓不足时加速买回"""
        if self.tA['active']:
            # 持仓中 → 检查买回
            days = self.tA['days_held'] + 1
            sell_t, buy_t = _get_A_thresholds(self.current_shares, days)
            buy_trigger = self.last_close * (1 - buy_t)
            self.tA['days_held'] = days

            if self.cur_price <= buy_trigger:
                qty   = self.tA['pending_qty']
                entry = self.tA['entry_price']
                ok, _ = self._place_order(TrdSide.BUY, qty, self.cur_price)
                if ok:
                    pnl = (entry - self.cur_price) * qty
                    self.today_pnl     += pnl
                    self.today_trades += 2
                    self.current_shares += qty
                    self.tA = {'active': False, 'entry_price': 0, 'pending_qty': 0, 'days_held': 0}
                    self._persist()
                    log("[涡轮A买回] %d股 @ $%.4f  触发<=%.4f  持有%d天  盈亏 $%.2f" % (
                        qty, self.cur_price, buy_trigger, days, pnl))
                    self._report("涡轮A买回 %d股 @$%.4f" % (qty, self.cur_price))
                    return True
                else:
                    self.tA['days_held'] -= 1
                    log("[涡轮A买回失败] 维持持仓状态")
                    return False
        else:
            # 待命 → 检查卖出
            if self.current_shares <= MIN_SHARES:
                return False
            sell_t, buy_t = _get_A_thresholds(self.current_shares, 0)
            sell_trigger = self.last_close * (1 + sell_t)

            if self.cur_price >= sell_trigger:
                qty = min(TRADE_QTY, self.current_shares - MIN_SHARES)
                if qty <= 0:
                    return False
                ok, _ = self._place_order(TrdSide.SELL, qty, self.cur_price)
                if ok:
                    self.tA = {'active': True, 'entry_price': self.cur_price,
                               'pending_qty': qty, 'days_held': 0}
                    self.current_shares -= qty
                    self._persist()
                    log("[涡轮A卖出] %d股 @ $%.4f  触发>=%.4f" % (
                        qty, self.cur_price, sell_trigger))
                    self._report("涡轮A卖出 %d股 @$%.4f" % (qty, self.cur_price))
                    return True
                else:
                    log("[涡轮A卖出失败] 维持待命状态")
                    return False
        return False

    # ---- 涡轮B: 先买后卖 ----
    def check_turbo_B(self):
        """B策略: 预留现金时跌买涨卖，持仓过高时加速卖出"""
        if self.tB['active']:
            # 持仓中 → 检查卖出
            days = self.tB['days_held'] + 1
            buy_t, sell_t = _get_B_thresholds(self.current_shares, days)
            sell_trigger = self.last_close * (1 + sell_t)
            self.tB['days_held'] = days

            if self.cur_price >= sell_trigger:
                qty   = self.tB['pending_qty']
                entry = self.tB['entry_price']
                ok, _ = self._place_order(TrdSide.SELL, qty, self.cur_price)
                if ok:
                    pnl = (self.cur_price - entry) * qty
                    self.today_pnl     += pnl
                    self.today_trades += 2
                    self.current_shares -= qty
                    self.tB = {'active': False, 'entry_price': 0, 'pending_qty': 0, 'days_held': 0}
                    self._persist()
                    log("[涡轮B卖出] %d股 @ $%.4f  触发>=%.4f  持有%d天  盈亏 $%.2f" % (
                        qty, self.cur_price, sell_trigger, days, pnl))
                    self._report("涡轮B卖出 %d股 @$%.4f" % (qty, self.cur_price))
                    return True
                else:
                    self.tB['days_held'] -= 1
                    log("[涡轮B卖出失败] 维持持仓状态")
                    return False
        else:
            # 待命 → 检查买入
            if self.current_shares >= MAX_SHARES:
                return False
            buy_t, sell_t = _get_B_thresholds(self.current_shares, 0)
            buy_trigger = self.last_close * (1 - buy_t)

            if self.cur_price <= buy_trigger:
                qty = TRADE_QTY
                if self.current_shares + qty > MAX_SHARES:
                    qty = MAX_SHARES - self.current_shares
                if qty <= 0:
                    return False
                ok, _ = self._place_order(TrdSide.BUY, qty, self.cur_price)
                if ok:
                    self.tB = {'active': True, 'entry_price': self.cur_price,
                               'pending_qty': qty, 'days_held': 0}
                    self.current_shares += qty
                    self._persist()
                    log("[涡轮B买入] %d股 @ $%.4f  触发<=%.4f" % (
                        qty, self.cur_price, buy_trigger))
                    self._report("涡轮B买入 %d股 @$%.4f" % (qty, self.cur_price))
                    return True
                else:
                    log("[涡轮B买入失败] 维持待命状态")
                    return False
        return False

    # ---- 报告 ----
    def _report(self, msg):
        report_file = DATA_DIR / "v3_live_report.json"
        report_file.write_text(json.dumps({
            'time'   : datetime.now().isoformat(),
            'price'  : self.cur_price,
            'msg'    : msg,
            'pnl'    : self.today_pnl,
            'trades' : self.today_trades,
            'shares' : self.current_shares,
            'turbo_A': self.tA,
            'turbo_B': self.tB,
        }, ensure_ascii=False), encoding='utf-8')

    # ---- 更新收盘价（新的一天开始） ----
    def update_last_close(self):
        # 动态计算日期：取最近一个非今天的交易日
        import calendar
        today_d = date.today()
        # 往前最多查5天
        dates_to_try = []
        for delta in range(1, 6):
            d = today_d - timedelta(days=delta)
            if d.weekday() < 5:  # 跳过周末
                dates_to_try.append(d.strftime('%Y-%m-%d'))
        # 从最近一天开始试
        new_close = None
        for end_d in dates_to_try:
            ret, df, _ = self.quote_ctx.request_history_kline(
                STOCK_CODE, start=end_d, end=end_d,
                ktype='K_DAY', autype='qfq')
            if ret == RET_OK and len(df) >= 1:
                new_close = float(df['close'].iloc[-1])
                actual_date = str(df['time_key'].iloc[-1])[:10]
                break
        if new_close:
            old_close = self.last_close
            self.last_close = new_close
            # 跨日重置：涡轮持仓天数归零（今日重新计算）
            old_A_days = self.tA.get('days_held', 0)
            old_B_days = self.tB.get('days_held', 0)
            self.tA['days_held'] = 0
            self.tB['days_held'] = 0
            self.today_pnl = 0
            self.today_trades = 0
            self._persist()
            log("[收盘更新] %s 收盘 $%.2f（原$%.2f）涡轮A days: %d→0 涡轮B days: %d→0" % (
                actual_date, new_close, old_close, old_A_days, old_B_days))
        else:
            log("[收盘更新失败] 无法获取最新收盘价")

    # ---- 主循环 ----
    def run(self):
        log("=" * 60)
        log("  V3 双涡轮引擎 - 渐进式+动态阈值(无强制)")
        log("  股票: %s" % STOCK_CODE)
        log("  基础阈值: %.0f%%  渐进: 3d->60%% 5d->40%% 7d->20%%" % (BASE_THRESHOLD * 100))
        log("  动态阈值: %.0f%%-%.0f%%  持仓范围: %d-%d股" % (
            DYN_MIN * 100, BASE_THRESHOLD * 100, MIN_SHARES, MAX_SHARES))
        log("  每笔交易量: %d股  底仓: %d股" % (TRADE_QTY, BASE_SHARES))
        log("  模式: %s" % ('实盘 LIVE' if not self.dry_run else '模拟 SIM'))
        log("=" * 60)

        if self.last_close:
            sell_t, buy_t = _get_A_thresholds(self.current_shares, 0)
            bbuy_t, bsell_t = _get_B_thresholds(self.current_shares, 0)
            log("昨日收盘: $%.2f" % self.last_close)
            log("A卖出>=%.4f  A买回<=%.4f" % (
                self.last_close * (1 + sell_t),
                self.last_close * (1 - buy_t)))
            log("B买入<=%.4f  B卖出>=%.4f" % (
                self.last_close * (1 - bbuy_t),
                self.last_close * (1 + bsell_t)))
            log("持仓偏离: %d股 (目标%d)" % (self.current_shares, TARGET_SHARES))
        log("-" * 60)

        loop = 0
        while True:
            try:
                price = self.get_price()
                if price:
                    if loop % 6 == 0:
                        shares = self.current_shares
                        base_dyn = _get_dynamic_base(shares)
                        log("[V3状态] 现价 $%.4f | 持仓%d | A:%s B:%s | 今日盈亏 $%.2f | 动态基础%.2f%%" % (
                            price, shares,
                            '已卖' if self.tA['active'] else '待命',
                            '已买' if self.tB['active'] else '待命',
                            self.today_pnl, base_dyn * 100))

                    self.check_turbo_A()
                    self.check_turbo_B()
                    self._persist()

                time.sleep(POLL_SEC)
                loop += 1

                now = datetime.now()
                if now.hour == 5 and now.minute < 10:
                    self.update_last_close()
                    time.sleep(120)

            except KeyboardInterrupt:
                log("[V3停止] 用户中断")
                break
            except Exception as e:
                log("[V3错误] %s" % e)
                time.sleep(30)


if __name__ == '__main__':
    engine = V3Engine(dry_run=False)
    engine.run()
