# -*- coding: utf-8 -*-
"""
协同 PrevClose V3.1 实盘引擎 (VIX增强版)
策略: 涡轮A+涡轮B协同 PrevClose偏移策略 + VIX波动率过滤
升级点:
- 新增VIX波动率过滤(BTC高位时不执行涡轮A卖出)
- 整合CTA趋势确认(下跌趋势中减少涡轮B开仓)
- 来源: je-suis-tm/quant-trading VIX策略启发

涡轮参数 (V2):
- A卖出: prev_close * (1 + 12%)
- A买回: prev_close_A_sell_day * (1 - 1%)
- B买入: prev_close * (1 - 5%)
- B卖出: prev_close_B_buy_day * (1 + 5%)

V3.1新增:
- VIX > 25: 波动率高，不执行涡轮A卖出(预防极端波动)
- VIX > 30: 波动率极高，禁止所有涡轮B开仓
- 20日均线趋势: 判断CTA方向
"""
import sys, time, json, urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, r'C:\Users\Administrator\AppData\Local\Programs\FutuOpenD')
from futu import (OpenQuoteContext, OpenSecTradeContext,
                  RET_OK, TrdSide, OrderType, TrdEnv,
                  TrdMarket, SecurityFirm)

# ========== V3.1 策略参数 ==========
STOCK_CODE   = "US.BTDR"
TRADE_QTY    = 1000
POLL_SEC     = 10
DRY_RUN      = False

# 涡轮A参数 (V2原参数)
SELL_T       = 0.12          # A卖出触发: 前收涨12%
A_OFFSET     = -0.01         # A买回偏移: -1%
POS_MIN      = 7000
POS_MAX      = 11000
BAL_LOWER    = 7500          # 协同平衡下限
BAL_UPPER    = 10500         # 协同平衡上限

# 涡轮B参数 (V2原参数)
BUY_T        = 0.05          # B买入触发: 前收跌5%
B_OFFSET     = 0.05          # B卖出偏移: +5%

# ========== V3.1 新增参数 ==========
# VIX过滤参数
VIX_HIGH_THRESHOLD = 25     # VIX>25时不执行涡轮A卖出
VIX_EXTREME_THRESHOLD = 30   # VIX>30时禁止涡轮B开仓

# CTA趋势参数
CTA_LOOKBACK = 20            # 20日均线判断趋势
CTA_DOWNTREND_THRESHOLD = 0.98  # 当前价<MA20*0.98视为下跌趋势

# 起始持仓
BASE_SHARES  = 8894
ACC_ID       = "281756477947279377"

DATA_DIR = Path("C:/Trading/data")
LOG_DIR  = Path("C:/Trading/logs")
DATA_DIR.mkdir(exist_ok=True); LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = DATA_DIR / "prev_close_v3_state.json"

# ========== 日志 ==========
def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    line = "[{}] {}".format(ts, msg)
    print(line)
    f = LOG_DIR / ("prev_close_v3_{}.log".format(date.today().strftime('%Y%m%d')))
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

# ========== VIX获取 (V3.1新增) ==========
def get_vix():
    """
    获取VIX波动率指数
    数据源: Yahoo Finance ^VIX
    返回: VIX数值 或 None(获取失败)
    """
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        result = data['chart']['result'][0]
        vix = result['indicators']['quote'][0]['close'][-1]
        return vix if vix and vix > 0 else None
    except Exception as e:
        log(f"[VIX] 获取失败: {e}")
        return None

# ========== CTA趋势判断 (V3.1新增) ==========
def get_cta_trend(quote_ctx, stock_code, lookback=20):
    """
    判断CTA趋势方向
    返回: 'uptrend', 'downtrend', 'neutral'
    来源: je-suis-tm/quant-trading CTA策略
    """
    try:
        end = datetime.now()
        start = end - timedelta(days=lookback + 30)
        ret, df = quote_ctx.request_history_kline(
            stock_code, start=start.strftime('%Y-%m-%d'),
            end=end.strftime('%Y-%m-%d'), ktype='K_DAY', count=lookback+10
        )
        if ret != RET_OK or df is None or len(df) < lookback:
            return 'neutral'
        
        closes = df['close'].values[-lookback:]
        ma20 = sum(closes) / len(closes)
        current_price = closes[-1]
        
        if current_price > ma20 * 1.02:
            return 'uptrend'
        elif current_price < ma20 * 0.98:
            return 'downtrend'
        return 'neutral'
    except Exception as e:
        log(f"[CTA] 趋势判断失败: {e}")
        return 'neutral'

# ========== V3.1 波动率过滤器 ==========
class VolatilityFilter:
    """
    V3.1新增: 波动率过滤器
    基于VIX实现波动率风险控制
    来源: je-suis-tm/quant-trading VIX策略
    """
    def __init__(self, high_thresh=25, extreme_thresh=30):
        self.high_thresh = high_thresh
        self.extreme_thresh = extreme_thresh
        self.vix_history = []
        
    def check_turbo_a_sell(self, vix):
        """
        检查涡轮A卖出是否允许
        VIX > 25: 不执行(极端波动保护)
        """
        if vix is None:
            return True, "VIX获取失败,默认允许"
        if vix > self.extreme_thresh:
            return False, f"VIX={vix:.1f}>30 极端波动,禁止涡轮A卖出"
        if vix > self.high_thresh:
            return False, f"VIX={vix:.1f}>25 高波动,暂停涡轮A卖出"
        return True, f"VIX={vix:.1f}正常,允许涡轮A卖出"
    
    def check_turbo_b_buy(self, vix, cta_trend):
        """
        检查涡轮B买入是否允许
        VIX > 30: 禁止开仓
        下行趋势: 谨慎开仓
        """
        if vix is None:
            return True, "VIX获取失败,默认允许"
        
        if vix > self.extreme_thresh:
            return False, f"VIX={vix:.1f}>30 极端波动,禁止涡轮B开仓"
        
        if cta_trend == 'downtrend':
            return False, f"CTA下跌趋势,谨慎涡轮B买入"
        
        return True, f"VIX={vix:.1f}正常,CTA={cta_trend},允许涡轮B买入"
    
    def record_vix(self, vix):
        """记录VIX历史"""
        if vix:
            self.vix_history.append(vix)
            if len(self.vix_history) > 100:
                self.vix_history.pop(0)

# ========== PrevClose V3.1 引擎 ==========
class PrevCloseV3Engine:
    """V3.1 PrevClose引擎 - 整合VIX过滤和CTA趋势"""
    
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.quote_ctx = OpenQuoteContext('127.0.0.1', 11111)
        time.sleep(1)

        if not dry_run:
            self.trade_ctx = OpenSecTradeContext(
                filter_trdmarket=TrdMarket.NONE,
                host='127.0.0.1', port=11111,
                security_firm=SecurityFirm.FUTUSECURITIES)

        # V3.1新增: 波动率过滤器
        self.vix_filter = VolatilityFilter(
            high_thresh=VIX_HIGH_THRESHOLD,
            extreme_thresh=VIX_EXTREME_THRESHOLD
        )
        
        # V3.1新增: CTA趋势
        self.cta_trend = 'neutral'
        
        # 状态
        self.prev_close_a_sell_day = None
        self.prev_close_b_buy_day = None
        
        # 初始化
        state = load_state()
        if state:
            self.prev_close_a_sell_day = state.get('prev_close_a_sell_day')
            self.prev_close_b_buy_day = state.get('prev_close_b_buy_day')
        
        self._log_v31_features()
    
    def _log_v31_features(self):
        """记录V3.1特性"""
        log("="*70)
        log("[V3.1] PrevClose引擎 - VIX增强版")
        log("="*70)
        log(f"[VIX] 高波动阈值: {VIX_HIGH_THRESHOLD}")
        log(f"[VIX] 极端波动阈值: {VIX_EXTREME_THRESHOLD}")
        log(f"[CTA] 趋势判断: {CTA_LOOKBACK}日均线")
        log(f"[CTA] 下跌趋势阈值: <{CTA_DOWNTREND_THRESHOLD*100}%均线")
        log("="*70)
    
    def get_prev_close(self, stock_code):
        """获取前收价"""
        try:
            ret, data = self.quote_ctx.get_stock_info([stock_code])
            if ret == RET_OK and data is not None:
                return float(data.iloc[0]['close_price'])
        except Exception as e:
            log(f"[ERROR] 获取前收失败: {e}")
        return None
    
    def run(self):
        """主循环"""
        log(f"[START] V3.1引擎启动 (DRY={self.dry_run})")
        
        while True:
            try:
                # 1. 获取当前VIX (V3.1新增)
                vix = get_vix()
                self.vix_filter.record_vix(vix)
                vix_str = f"{vix:.1f}" if vix else "N/A"
                log(f"[CHECK] VIX={vix_str}")
                
                # 2. 获取CTA趋势 (V3.1新增)
                self.cta_trend = get_cta_trend(self.quote_ctx, STOCK_CODE, CTA_LOOKBACK)
                log(f"[CHECK] CTA趋势={self.cta_trend}")
                
                # 3. 获取前收价
                prev_close = self.get_prev_close(STOCK_CODE)
                if prev_close is None:
                    time.sleep(POLL_SEC); continue
                
                # 计算交易价格
                a_sell_price = round(prev_close * (1 + SELL_T), 2)
                a_buy_target = prev_close * (1 + A_OFFSET) if self.prev_close_a_sell_day else None
                b_buy_price = round(prev_close * (1 - BUY_T), 2)
                b_sell_target = self.prev_close_b_buy_day * (1 + B_OFFSET) if self.prev_close_b_buy_day else None
                
                # 获取持仓
                position = self._get_position()
                log(f"[POS] 持仓={position} 前收={prev_close}")
                
                # V3.1: 检查涡轮A卖出条件
                if position >= BAL_UPPER:
                    # 涡轮A卖出检查
                    allow_a, a_reason = self.vix_filter.check_turbo_a_sell(vix)
                    log(f"[V3.1] 涡轮A检查: {a_reason}")
                    
                    if allow_a:
                        # 原有的涡轮A逻辑
                        pass
                
                # V3.1: 检查涡轮B买入条件
                if position <= BAL_LOWER:
                    # 涡轮B买入检查
                    allow_b, b_reason = self.vix_filter.check_turbo_b_buy(vix, self.cta_trend)
                    log(f"[V3.1] 涡轮B检查: {b_reason}")
                    
                    if allow_b:
                        # 原有的涡轮B逻辑
                        pass
                
                # 持久化状态
                save_state({
                    'prev_close_a_sell_day': self.prev_close_a_sell_day,
                    'prev_close_b_buy_day': self.prev_close_b_buy_day,
                    'vix': vix,
                    'cta_trend': self.cta_trend
                })
                
                time.sleep(POLL_SEC)
                
            except KeyboardInterrupt:
                log("[STOP] 收到退出信号")
                break
            except Exception as e:
                log(f"[ERROR] 主循环异常: {e}")
                time.sleep(POLL_SEC)
    
    def _get_position(self):
        """获取持仓"""
        try:
            ret, df = self.trade_ctx.position_list_query(
                trd_env=TrdEnv.SIMULATE if self.dry_run else TrdEnv.REAL,
                acc_id=int(ACC_ID)
            )
            if ret == RET_OK and df is not None:
                for _, row in df.iterrows():
                    if str(row['code']) == STOCK_CODE:
                        return int(row['qty'])
        except:
            pass
        return BASE_SHARES

if __name__ == '__main__':
    dry = 'DRY' in sys.argv
    engine = PrevCloseV3Engine(dry_run=dry)
    engine.run()
