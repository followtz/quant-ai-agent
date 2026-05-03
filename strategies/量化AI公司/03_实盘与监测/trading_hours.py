# -*- coding: utf-8 -*-
"""
硬编码交易时段常量 — 所有引擎必须引用此文件
禁止在引擎代码内直接写死时区转换逻辑
来源: 2026-04-22 用户指令，根因：时区混乱导致V3引擎运行时段与美股实际波动时段错位

时区基准:
  CST  = UTC+8  (北京时间/上海时间)
  ET   = UTC-4/5 (美东时间，夏令时UTC-4，冬令时UTC-5)
  HKT  = UTC+8  (香港时间，与CST相同)
  默认采用夏令时(EST/EDT): ET = CST - 12h (4月适用)

美股夏令时(3月中-11月中): ET = CST - 12
美股冬令时:               ET = CST - 13

美股2026年夏令时: 2026-03-08 ~ 2026-11-01
"""

from datetime import time as dtime, datetime
from typing import Tuple

# ═══════════════════════════════════════════════════════════════
# 美股交易时段（美东时间 ET）
# ═══════════════════════════════════════════════════════════════
# 常规交易: 9:30 ~ 16:00 ET
# 盘前:     4:00 ~ 9:30 ET  (允许读取行情，但不开仓)
# 盘后:     16:00 ~ 20:00 ET (同上)

US_MARKET_OPEN  = dtime(9, 30)    # 美股开盘（常规交易开始）
US_MARKET_CLOSE = dtime(16, 0)    # 美股收盘（常规交易结束）

US_PREOPEN_START = dtime(4, 0)    # 盘前开始（可读取行情，不开仓）
US_PREOPEN_END   = dtime(9, 30)   # 盘前结束

US_AFTER_END = dtime(20, 0)       # 盘后结束

# 全时段（美股任何活跃时段，可读取行情）
US_ANY_ACTIVE_START = dtime(4, 0)
US_ANY_ACTIVE_END   = dtime(20, 0)

# ═══════════════════════════════════════════════════════════════
# 港股交易时段（香港时间 HKT = UTC+8）
# ═══════════════════════════════════════════════════════════════
# 早市: 9:30 ~ 12:00 HKT
# 午间休市: 12:00 ~ 13:00 HKT
# 午市: 13:00 ~ 16:00 HKT

HK_MARKET_OPEN   = dtime(9, 30)   # 港股开盘
HK_MARKET_CLOSE  = dtime(16, 0)   # 港股收盘
HK_PREOPEN_START = dtime(9, 0)    # 港股盘前开始
HK_LUNCH_START   = dtime(12, 0)   # 午间休市开始
HK_LUNCH_END     = dtime(13, 0)   # 午间休市结束

# ═══════════════════════════════════════════════════════════════
# 夏令时判断（2026年3月8日起夏令时，11月1日结束）
# ═══════════════════════════════════════════════════════════════
DST_START_2026 = datetime(2026, 3, 8)   # 2026年夏令时开始
DST_END_2026   = datetime(2026, 11, 1)   # 2026年夏令时结束

def is_dst(d: datetime) -> bool:
    """判断给定时间是否在夏令时期间"""
    return DST_START_2026 <= d.replace(tzinfo=None) < DST_END_2026

def cst_to_et_offset(cst_hour: int, is_dst_local: bool = None) -> int:
    """
    将CST小时转换为ET偏移量
    夏令时: ET = CST - 12
    冬令时: ET = CST - 13
    """
    if is_dst_local is None:
        is_dst_local = is_dst(datetime.now())
    return -12 if is_dst_local else -13

def cst_now_et() -> datetime:
    """当前北京时间对应的美东时间"""
    now = datetime.now()
    offset_h = 12 if is_dst(now) else 13
    return now.replace(hour=(now.hour - offset_h) % 24)

def get_et_now() -> datetime:
    """获取当前美东时间"""
    cst = datetime.now()
    offset_h = 12 if is_dst(cst) else 13
    et_hour = (cst.hour - offset_h) % 24
    return cst.replace(hour=et_hour, minute=cst.minute, second=cst.second)

def time_in_us_session(et_time: datetime = None, include_prepost: bool = False) -> bool:
    """
    判断美东时间是否在美股交易时段
    include_prepost=True: 含盘前盘后（允许读行情，不允许开仓）
    """
    if et_time is None:
        et_time = get_et_now()
    t = et_time.time()
    if include_prepost:
        return US_PREOPEN_START <= t < US_AFTER_END
    return US_MARKET_OPEN <= t < US_MARKET_CLOSE

def time_in_hk_session(hkt_time: datetime = None) -> bool:
    """判断香港时间是否在港股交易时段（午间不休市判断）"""
    if hkt_time is None:
        hkt_time = datetime.now()
    t = hkt_time.time()
    in_morning = HK_MARKET_OPEN <= t < HK_LUNCH_START
    in_afternoon = HK_LUNCH_END <= t < HK_MARKET_CLOSE
    return in_morning or in_afternoon

def is_market_day(dt: datetime = None) -> bool:
    """判断是否为美股交易日（周一=0 ~ 周五=4）"""
    if dt is None:
        dt = datetime.now()
    return dt.weekday() < 5

def us_session_status() -> Tuple[str, str]:
    """
    返回 (session_phase, description)
    session_phase: PREMARKET / OPEN / AFTERHOURS / CLOSED
    description: 中文描述
    """
    et = get_et_now()
    t = et.time()
    if not is_market_day(et):
        return "CLOSED", "美股非交易日"
    if t < US_MARKET_OPEN:
        return "PREMARKET", f"盘前(至{US_MARKET_OPEN.strftime('%H:%M')}ET)"
    elif t < US_MARKET_CLOSE:
        return "OPEN", f"交易中(至{US_MARKET_CLOSE.strftime('%H:%M')}ET)"
    elif t < US_AFTER_END:
        return "AFTERHOURS", f"盘后(至{US_AFTER_END.strftime('%H:%M')}ET)"
    else:
        return "CLOSED", "收盘后"

def engine_run_status() -> Tuple[bool, str]:
    """
    返回 (should_run, reason)
    判断美股当前时段是否应该运行引擎（读取行情+交易）
    美股开盘后和盘前均可运行（非交易时段可读不可交易）
    """
    et = get_et_now()
    t = et.time()
    if not is_market_day(et):
        return False, "非美股交易日"
    if US_MARKET_OPEN <= t < US_MARKET_CLOSE:
        return True, "美股交易时段"
    if US_PREOPEN_START <= t < US_MARKET_OPEN:
        return True, "盘前时段(可读行情，暂不开仓)"
    if US_MARKET_CLOSE <= t < US_AFTER_END:
        return True, "盘后时段(可读行情，暂不开仓)"
    return False, "非活跃时段(20:00-04:00ET)"


# ═══════════════════════════════════════════════════════════════
# 常用转换（供引擎直接调用）
# ═══════════════════════════════════════════════════════════════
def now_et() -> datetime:
    """当前美东时间"""
    return get_et_now()

def now_cst() -> datetime:
    """当前北京时间（直接返回now）"""
    return datetime.now()

def now_hkt() -> datetime:
    """当前香港时间（同CST）"""
    return datetime.now()

# ═══════════════════════════════════════════════════════════════
# 导出常量供引擎引用
# ═══════════════════════════════════════════════════════════════
US_ENGINE_RUN_START_ET = dtime(4, 0)   # 引擎运行开始（含盘前）
US_ENGINE_RUN_END_ET   = dtime(20, 0)  # 引擎运行结束（含盘后）
US_TRADE_WINDOW_ET     = (US_MARKET_OPEN, US_MARKET_CLOSE)  # 可开仓时段
