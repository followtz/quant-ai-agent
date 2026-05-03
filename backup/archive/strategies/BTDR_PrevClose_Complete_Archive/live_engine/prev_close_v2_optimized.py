# -*- coding: utf-8 -*-
"""
BTDR PrevClose V2 优化版实盘引擎 (v2.1-Optimized)
优化目标 (基于归因分析 v2026-04-20):
  1. 止损机制 → 解决最大回撤 -54.04%
  2. 信号过滤 → 解决胜率 51.9%
  3. 动态仓位管理 → 解决波动率 93.4%

新增参数 (v2.1):
  - STOP_LOSS_PCT: 单笔止损线 (-5%)
  - SIGNAL_FILTER: 信号过滤 (RSI + 成交量)
  - VOL_TARGET: 目标波动率 (30%)
  - MAX_DRAWDON: 最大回撤熔断 (-15%)
"""
import sys, time, json
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, r'C:\Users\Administrator\AppData\Local\Programs\FutuOpenD')
from futu import (OpenQuoteContext, OpenSecTradeContext,
                  RET_OK, TrdSide, OrderType, TrdEnv,
                  TrdMarket, SecurityFirm)

# ========== V2 基础参数 ==========
STOCK_CODE   = "US.BTDR"
TRADE_QTY    = 1000          # 基础每笔交易量
POLL_SEC     = 10            # 轮询间隔（秒）
DRY_RUN      = False         # False=实盘 True=模拟

# 涡轮A参数
SELL_T       = 0.12          # A卖出触发: 前收涨12%
A_OFFSET     = -0.01         # A买回偏移: 前收-1%
POS_MIN      = 7000          # 仓位硬下限
POS_MAX      = 11000         # 仓位硬上限
BAL_LOWER    = 7500          # 协同平衡下限
BAL_UPPER    = 10500         # 协同平衡上限

# 涡轮B参数
BUY_T        = 0.05          # B买入触发: 前收跌5%
B_OFFSET     = 0.05          # B卖出偏移: 前收+5%

# 账户
ACC_ID       = "281756477947279377"

# ========== V2.1 优化参数 ==========
STOP_LOSS_PCT    = -0.05    # 单笔止损 -5%
MAX_DRAWDOWN     = -0.15    # 最大回撤熔断 -15%
VOL_TARGET       = 0.30      # 目标波动率 30%
RSI_FILTER       = True       # RSI信号过滤
RSI_BUY_THRESH   = 30        # RSI买入阈值 (<30超卖)
RSI_SELL_THRESH  = 70        # RSI卖出阈值 (>70超买)
VOLUME_FILTER    = True       # 成交量过滤
VOLUME_RATIO     = 1.2       # 成交量需 > 20日均量×1.2

# ========== 路径配置 ==========
DATA_DIR = Path("C:/Trading/data")
LOG_DIR  = Path("C:/Trading/logs")
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

STATE_FILE = DATA_DIR / "prev_close_v2_optimized_state.json"
OPTIMIZED_LOG = LOG_DIR / "prev_close_v2_optimized_{}.log".format(date.today().strftime('%Y%m%d'))

# ========== 日志 ==========
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = "[{}] {}".format(ts, msg)
    print(line)
    with open(OPTIMIZED_LOG, 'a', encoding='utf-8') as lf:
        lf.write(line + '\n')

# ========== 状态持久化 ==========
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except Exception as e:
            log("[状态加载失败] {}".format(e))
    return None

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')

# ========== 技术指标计算 ==========
def calculate_rsi(prices: list, period: int = 14) -> float:
    """计算RSI指标"""
    if len(prices) < period + 1:
        return 50.0  # 数据不足返回中性值
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

def calculate_volume_ratio(quote_ctx, stock_code: str) -> float:
    """计算当日成交量 / 20日平均成交量比率"""
    try:
        end_date = date.today().strftime('%Y-%m-%d')
        start_date = (date.today() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        ret, df, _ = quote_ctx.request_history_kline(
            stock_code, start=start_date, end=end_date,
            ktype='K_DAY', autype='qfq'
        )
        
        if ret == RET_OK and len(df) >= 20:
            volumes = df['volume'].tolist()
            today_vol = volumes[-1]
            avg_vol = sum(volumes[-20:-1]) / 19  # 前19日平均
            
            if avg_vol > 0:
                return round(today_vol / avg_vol, 2)
        
        return 1.0  # 计算失败返回1.0
    
    except Exception as e:
        log("[成交量计算失败] {}".format(e))
        return 1.0

def calculate_volatility(prices: list, period: int = 20) -> float:
    """计算历史波动率（标准差/均值）"""
    if len(prices) < period:
        return 0.5  # 数据不足返回50%波动率
    
    recent = prices[-period:]
    mean = sum(recent) / len(recent)
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    std_dev = variance ** 0.5
    
    volatility = std_dev / mean if mean > 0 else 0.5
    return round(volatility, 4)

# ========== 动态仓位计算 ==========
def calc_dynamic_position_size(current_price: float, volatility: float) -> int:
    """
    根据波动率动态调整仓位
    目标波动率 VOL_TARGET=30%
    公式: 调整后的交易量 = 基础交易量 × (VOL_TARGET / 实际波动率)
    """
    if volatility <= 0:
        return TRADE_QTY
    
    scale = min(2.0, max(0.5, VOL_TARGET / volatility))  # 限制在0.5-2倍
    adjusted_qty = int(TRADE_QTY * scale / 100) * 100  # 取整百
    
    log("[动态仓位] 波动率={:.2%} 调整系数={:.2f} 交易量={}".format(
        volatility, scale, adjusted_qty))
    
    return max(100, adjusted_qty)  # 最少100股

# ========== PrevClose V2.1 优化引擎 ==========
class PrevCloseV2OptimizedEngine:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        time.sleep(1)

        if not dry_run:
            self.trade_ctx = OpenSecTradeContext(
                filter_trdmarket=TrdMarket.US,
                host='127.0.0.1', port=11111,
                security_firm=SecurityFirm.FUTUSECURITIES)
            time.sleep(1)
            log("[PrevClose V2.1优化版启动] 实盘模式")
            self._verify_account()
        else:
            self.trade_ctx = None
            log("[PrevClose V2.1优化版启动] 模拟模式")

        # 恢复状态
        saved = load_state()
        today_str = date.today().strftime('%Y-%m-%d')
        is_new_day = not (saved and saved.get('date') == today_str)

        if saved:
            self.tA = saved.get('turbo_A', {})
            self.tB = saved.get('turbo_B', {})
            self.today_pnl    = 0 if is_new_day else saved.get('pnl', 0)
            self.today_trades  = 0 if is_new_day else saved.get('trades', 0)
            self.total_pnl     = saved.get('total_pnl', 0)
            self.total_trades  = saved.get('total_trades', 0)
            self.last_close    = saved.get('last_close')
            self.current_shares= saved.get('shares', 8894)
            
            if is_new_day:
                if self.tA.get('active'):
                    self.tA['days_held'] = 0
                if self.tB.get('active'):
                    self.tB['days_held'] = 0
                self.today_pnl = 0
                self.today_trades = 0
                log("[跨日重置] 盈亏和交易次数已重置")
            
            # V2.1新增：恢复回撤记录
            self.max_total_pnl = saved.get('max_total_pnl', self.total_pnl)
            self.drawdown_pct  = saved.get('drawdown_pct', 0.0)
            
            log("[恢复] 涡轮A: {} | 涡轮B: {} | 持仓{} | 今日盈亏${:.2f}".format(
                self.tA, self.tB, self.current_shares, self.today_pnl))
        else:
            self.tA = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
            self.tB = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
            self.today_pnl = 0
            self.today_trades = 0
            self.total_pnl = 0
            self.total_trades = 0
            self.last_close = None
            self.current_shares = 8894
            self.max_total_pnl = 0
            self.drawdown_pct = 0.0
            log("[新交易日] 状态已初始化")

        self.cur_price = 0
        self._init_last_close()
        self._init_history_prices()

    def _init_history_prices(self):
        """初始化历史价格（用于技术指标计算）"""
        self.history_prices = []
        try:
            end_date = date.today().strftime('%Y-%m-%d')
            start_date = (date.today() - timedelta(days=60)).strftime('%Y-%m-%d')
            
            ret, df, _ = self.quote_ctx.request_history_kline(
                STOCK_CODE, start=start_date, end=end_date,
                ktype='K_DAY', autype='qfq'
            )
            
            if ret == RET_OK and len(df) > 0:
                self.history_prices = [float(p) for p in df['close'].tolist()]
                log("[历史价格] 加载{}条历史数据".format(len(self.history_prices)))
        except Exception as e:
            log("[历史价格初始化失败] {}".format(e))
            self.history_prices = []

    def _verify_account(self):
        try:
            ret, f = self.trade_ctx.accinfo_query(trd_env=TrdEnv.REAL)
            if ret == RET_OK:
                power = float(f.iloc[0]['power'])
                log("[账户] 购买力=${:.2f} USD".format(power))
        except Exception as e:
            log("[账户验证失败] {}".format(e))

    def _init_last_close(self):
        if self.last_close is None:
            try:
                ret, df, _ = self.quote_ctx.request_history_kline(
                    STOCK_CODE, start='2026-04-07', end='2026-04-25',
                    ktype='K_DAY', autype='qfq')
                if ret == RET_OK and len(df) >= 1:
                    self.last_close = float(df['close'].iloc[-1])
                    log("[初始化] 昨日收盘=${:.2f}".format(self.last_close))
                else:
                    self.last_close = 10.11
                    log("[初始化] 使用参考价 $10.11")
            except Exception as e:
                self.last_close = 10.11
                log("[初始化失败] 使用参考价 $10.11 ({})".format(e))

    def _persist(self):
        """持久化状态（含V2.1新增字段）"""
        save_state({
            'date'         : date.today().strftime('%Y-%m-%d'),
            'turbo_A'      : self.tA,
            'turbo_B'      : self.tB,
            'pnl'          : self.today_pnl,
            'trades'       : self.today_trades,
            'total_pnl'    : self.total_pnl,
            'total_trades'  : self.total_trades,
            'last_close'   : self.last_close,
            'shares'       : self.current_shares,
            'max_total_pnl': self.max_total_pnl,
            'drawdown_pct' : self.drawdown_pct
        })

    def get_price(self):
        try:
            ret, data = self.quote_ctx.get_stock_quote([STOCK_CODE])
            if ret == RET_OK and len(data) > 0:
                p = float(data['last'].iloc[0])
                if p > 0:
                    self.cur_price = p
                    return p
        except:
            pass
        
        try:
            ret2, data2 = self.quote_ctx.get_market_snapshot(STOCK_CODE)
            if ret2 == RET_OK and len(data2) > 0:
                p2 = float(data2['last_price'].iloc[0])
                if p2 > 0:
                    self.cur_price = p2
                    return p2
        except:
            pass
        
        return self.cur_price if self.cur_price > 0 else None

    def update_drawdown(self):
        """更新回撤百分比（V2.1新增）"""
        if self.total_pnl > self.max_total_pnl:
            self.max_total_pnl = self.total_pnl
        
        if self.max_total_pnl > 0:
            self.drawdown_pct = (self.total_pnl - self.max_total_pnl) / abs(self.max_total_pnl)
            self.drawdown_pct = round(self.drawdown_pct, 4)
        
        # 检查熔断
        if self.drawdown_pct <= MAX_DRAWDOWN:
            log("[熔断触发] 最大回撤={:.2%} <= 阈值{:.2%}".format(
                self.drawdown_pct, MAX_DRAWDOWN))
            return True  # 触发熔断
        
        return False  # 正常

    def check_signal_filter(self, side: str) -> bool:
        """
        信号过滤（V2.1新增）
        返回: True=通过过滤 False=未通过
        """
        # RSI过滤
        if RSI_FILTER:
            rsi = calculate_rsi(self.history_prices)
            if side == 'BUY' and rsi >= RSI_BUY_THRESH:
                log("[信号过滤] RSI={:.2f} >= 买入阈值{}(不超卖)".format(rsi, RSI_BUY_THRESH))
                return False
            if side == 'SELL' and rsi <= RSI_SELL_THRESH:
                log("[信号过滤] RSI={:.2f} <= 卖出阈值{}(不超买)".format(rsi, RSI_SELL_THRESH))
                return False
        
        # 成交量过滤
        if VOLUME_FILTER:
            vol_ratio = calculate_volume_ratio(self.quote_ctx, STOCK_CODE)
            if vol_ratio < VOLUME_RATIO:
                log("[信号过滤] 成交量比率={:.2f} < 阈值{}".format(vol_ratio, VOLUME_RATIO))
                return False
        
        return True  # 通过所有过滤

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
                    log("[下单成功] {} {}股 @${:.4f} 订单:{} 状态:{}".format(
                        side, qty, price, oid, sts))
                    return True, oid
                else:
                    log("[下单失败] {} {}股 @${:.4f} 重试({}): {}".format(
                        side, qty, price, attempt+1, data))
                    time.sleep(2)
            except Exception as e:
                log("[下单异常] {} {}股 @${:.4f}: {}".format(side, qty, price, e))
                time.sleep(3)
        
        log("[下单放弃] {} {}股 @${:.4f}".format(side, qty, price))
        return False, "MAX_RETRIES"

    # ========== 涡轮A检查（含止损） ==========
    def check_turbo_A(self):
        # === 持仓中 → 检查买回 或 止损 ===
        if self.tA['active']:
            days = self.tA['days_held'] + 1
            prev_close_A = self.tA['prev_close']
            buyback_target = prev_close_A * (1 + A_OFFSET)
            self.tA['days_held'] = days

            # 止损检查（V2.1新增）
            entry = self.tA['entry_price']
            stop_loss_price = entry * (1 + STOP_LOSS_PCT)  # 卖出价低于买入价5%
            if self.cur_price <= stop_loss_price:
                qty = self.tA['pending_qty']
                loss = (self.cur_price - entry) * qty
                ok, _ = self._place_order(TrdSide.BUY, qty, self.cur_price)
                if ok:
                    self.today_pnl += loss
                    self.total_pnl += loss
                    self.today_trades += 2
                    self.total_trades += 2
                    self.current_shares += qty
                    self.tA = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
                    self._persist()
                    log("[A止损] {}股@${:.4f} 止损线${:.4f} 持有{}天 亏损${:.2f}".format(
                        qty, self.cur_price, stop_loss_price, days, loss))
                    return True

            # 正常买回检查
            if self.cur_price <= buyback_target:
                qty = self.tA['pending_qty']
                entry = self.tA['entry_price']
                ok, _ = self._place_order(TrdSide.BUY, qty, self.cur_price)
                if ok:
                    pnl = (entry - self.cur_price) * qty
                    self.today_pnl += pnl
                    self.total_pnl += pnl
                    self.today_trades += 2
                    self.total_trades += 2
                    self.current_shares += qty
                    self.tA = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
                    self._persist()
                    log("[A买回] {}股@${:.4f} 目标<=${:.4f}(Ao={:.0%}) 持有{}天 盈亏${:+.2f}".format(
                        qty, self.cur_price, buyback_target, A_OFFSET, days, pnl))
                    return True
                else:
                    self.tA['days_held'] -= 1

        # === 待命 → 检查卖出（信号过滤） ===
        else:
            if self.current_shares <= POS_MIN:
                return False
            
            # 信号过滤（V2.1新增）
            if not self.check_signal_filter('SELL'):
                return False
            
            sell_trigger = self.last_close * (1 + SELL_T)
            if self.cur_price >= sell_trigger:
                qty = min(TRADE_QTY, self.current_shares - POS_MIN)
                if qty <= 0:
                    return False
                
                # 动态仓位（V2.1新增）
                if len(self.history_prices) >= 20:
                    volatility = calculate_volatility(self.history_prices)
                    qty = calc_dynamic_position_size(self.cur_price, volatility)
                    qty = min(qty, self.current_shares - POS_MIN)
                
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

        # === 协同平衡 ===
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

    # ========== 涡轮B检查（含止损） ==========
    def check_turbo_B(self):
        # === 持仓中 → 检查卖出 或 止损 ===
        if self.tB['active']:
            days = self.tB['days_held'] + 1
            prev_close_B = self.tB['prev_close']
            sellback_target = prev_close_B * (1 + B_OFFSET)
            self.tB['days_held'] = days

            # 止损检查（V2.1新增）
            entry = self.tB['entry_price']
            stop_loss_price = entry * (1 - STOP_LOSS_PCT)  # 买入价高于卖出价5%
            if self.cur_price <= stop_loss_price:
                qty = self.tB['pending_qty']
                loss = (self.cur_price - entry) * qty
                ok, _ = self._place_order(TrdSide.SELL, qty, self.cur_price)
                if ok:
                    self.today_pnl += loss
                    self.total_pnl += loss
                    self.today_trades += 2
                    self.total_trades += 2
                    self.current_shares -= qty
                    self.tB = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
                    self._persist()
                    log("[B止损] {}股@${:.4f} 止损线${:.4f} 持有{}天 亏损${:.2f}".format(
                        qty, self.cur_price, stop_loss_price, days, loss))
                    return True

            # 正常卖出检查
            if self.cur_price >= sellback_target:
                qty = self.tB['pending_qty']
                entry = self.tB['entry_price']
                ok, _ = self._place_order(TrdSide.SELL, qty, self.cur_price)
                if ok:
                    pnl = (self.cur_price - entry) * qty
                    self.today_pnl += pnl
                    self.total_pnl += pnl
                    self.today_trades += 2
                    self.total_trades += 2
                    self.current_shares -= qty
                    self.tB = {'active':False,'entry_price':0,'pending_qty':0,'days_held':0}
                    self._persist()
                    log("[B卖出] {}股@${:.4f} 目标>=${:.4f}(Bo=+{:.0%}) 持有{}天 盈亏${:+.2f}".format(
                        qty, self.cur_price, sellback_target, B_OFFSET, days, pnl))
                    return True
                else:
                    self.tB['days_held'] -= 1

        # === 待命 → 检查买入（信号过滤） ===
        else:
            if self.current_shares >= POS_MAX:
                return False
            
            # 信号过滤（V2.1新增）
            if not self.check_signal_filter('BUY'):
                return False
            
            buy_trigger = self.last_close * (1 - BUY_T)
            if self.cur_price <= buy_trigger:
                qty = TRADE_QTY
                if self.current_shares + qty > POS_MAX:
                    qty = POS_MAX - self.current_shares
                if qty <= 0:
                    return False
                
                # 动态仓位（V2.1新增）
                if len(self.history_prices) >= 20:
                    volatility = calculate_volatility(self.history_prices)
                    qty = calc_dynamic_position_size(self.cur_price, volatility)
                    qty = min(qty, POS_MAX - self.current_shares)
                
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

        # === 协同平衡 ===
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

    # ========== 收盘价更新 ==========
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
                    self.today_pnl = 0
                    self.today_trades = 0
                    
                    # 更新历史价格
                    self.history_prices.append(new_close)
                    if len(self.history_prices) > 60:
                        self.history_prices = self.history_prices[-60:]
                    
                    self._persist()
                    log("[收盘更新] {} 收盘${:.2f}(原${:.2f}) A_days={}->0 B_days={}->0".format(
                        actual_date, new_close, old, old_A, old_B))
                    return
        log("[收盘更新失败]")

    def _report(self):
        """生成报告（含V2.1新增指标）"""
        rpt = DATA_DIR / "prev_close_v2_optimized_report.json"
        report_data = {
            'time'         : datetime.now().isoformat(),
            'price'        : self.cur_price,
            'pnl'          : self.today_pnl,
            'total_pnl'    : self.total_pnl,
            'trades'       : self.today_trades,
            'total_trades' : self.total_trades,
            'shares'       : self.current_shares,
            'turbo_A'      : self.tA,
            'turbo_B'      : self.tB,
            'strategy'     : 'prev_close_v2_optimized',
            'params'       : {
                'S': SELL_T, 'Ao': A_OFFSET, 'B': BUY_T, 'Bo': B_OFFSET,
                'qty': TRADE_QTY, 'pos_range': [POS_MIN, POS_MAX],
                'stop_loss': STOP_LOSS_PCT, 'max_drawdown': MAX_DRAWDOWN,
                'vol_target': VOL_TARGET, 'rsi_filter': RSI_FILTER
            },
            'v2.1_metrics': {
                'max_total_pnl'  : self.max_total_pnl,
                'drawdown_pct'   : self.drawdown_pct,
                'trigger_stop_loss': STOP_LOSS_PCT,
                'signal_filter_on': RSI_FILTER or VOLUME_FILTER
            }
        }
        rpt.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding='utf-8')

    def run(self):
        """主运行循环"""
        log("="*60)
        log("[PrevClose V2.1优化版] 启动完成，开始监控...")
        log("="*60)
        
        try:
            while True:
                # 检查熔断（V2.1新增）
                if self.update_drawdown():
                    log("[熔断] 已达到最大回撤阈值，停止交易")
                    self._report()
                    break
                
                price = self.get_price()
                if price is None:
                    log("[价格获取失败] 等待{}秒".format(POLL_SEC))
                    time.sleep(POLL_SEC)
                    continue
                
                log("[监控] 当前价格=${:.2f} 持仓{}股 今日盈亏${:.2f}".format(
                    price, self.current_shares, self.today_pnl))
                
                # 检查涡轮A和B
                self.check_turbo_A()
                self.check_turbo_B()
                
                # 更新历史价格
                if price > 0:
                    self.history_prices.append(price)
                    if len(self.history_prices) > 60:
                        self.history_prices = self.history_prices[-60:]
                
                time.sleep(POLL_SEC)
                
        except KeyboardInterrupt:
            log("[手动停止] 保存状态并退出")
            self._report()
            self._persist()
        except Exception as e:
            log("[异常退出] {}".format(e))
            self._report()
            self._persist()


def main():
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv
    engine = PrevCloseV2OptimizedEngine(dry_run=dry_run)
    engine.run()


if __name__ == '__main__':
    main()
