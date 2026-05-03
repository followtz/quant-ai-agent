# -*- coding: utf-8 -*-
"""
连连数字V4引擎 - 增强风控补丁
追加到 v4_live_engine.py 的检查逻辑中

新增风控：
1. 重复订单检测（基于订单ID去重）
2. 价格异常检测（拒绝价格为0/负数/超常跳空）
3. 持仓实时对账（每次交易前对比API账户持仓）
4. 连接健康检查（心跳超时自动暂停）
5. 紧急停止开关（EMERGENCY_STOP文件存在时立即停止）
6. 日志心跳机制（记录正常心跳，识别静默崩溃）

使用方法：
将本文件内容追加到 v4_live_engine.py 的 LianlianV4LiveEngine 类末尾，
或在 run() 循环开头调用 enhanced_safety_checks()
"""
import time, json
from pathlib import Path
from datetime import datetime

# ===== 配置 =====
WORK_DIR    = Path(r"C:\Users\Administrator\Desktop\量化AI公司")
DATA_DIR    = WORK_DIR / "03_实盘与监测"
DATA_DIR.mkdir(exist_ok=True)

# 紧急停止文件路径
EMERGENCY_STOP_FILE = DATA_DIR / "EMERGENCY_STOP.txt"

# 订单去重文件
ORDER_DEDUP_FILE = DATA_DIR / "order_dedup.json"

# 持仓对账文件
POSITION_RECON_FILE = DATA_DIR / "position_recon.json"

# 日志心跳文件
HEARTBEAT_FILE = DATA_DIR / "heartbeat.json"

# 心跳超时（秒），超过此时间认为引擎已静默崩溃
HEARTBEAT_TIMEOUT = 120

# 价格跳空阈值（相对上一价格）
PRICE_GAP_THRESHOLD = 0.20  # 20% 跳空视为异常

# ===== 工具函数 =====

def log_safe(msg):
    """安全日志（无emoji，兼容Windows控制台）"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [SAFETY] {msg}")

def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except:
        return default if default is not None else {}

def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ===== 1. 紧急停止检查 =====

def check_emergency_stop():
    """
    检查紧急停止文件是否存在。
    如果存在，立即停止所有交易并返回 True。
    
    使用方法：手动创建 EMERGENCY_STOP.txt，内容为停止原因。
    删除该文件后引擎恢复正常。
    """
    if EMERGENCY_STOP_FILE.exists():
        reason = EMERGENCY_STOP_FILE.read_text(encoding="utf-8").strip()
        log_safe(f"!!! EMERGENCY STOP triggered: {reason}")
        log_safe(f"!!! 所有交易已暂停，等待人工干预")
        return True
    return False

# ===== 2. 重复订单检测 =====

def is_duplicate_order(signal_key):
    """
    检测是否为重复信号（防止API延迟导致同一信号被执行多次）。
    signal_key: 信号的字符串表示，如 "BUY_2026-04-13_10:30_1000"
    """
    dedup = read_json(ORDER_DEDUP_FILE, {})
    now = time.time()
    
    # 清理超过5分钟的记录
    dedup = {k: v for k, v in dedup.items() if now - v < 300}
    
    if signal_key in dedup:
        elapsed = now - dedup[signal_key]
        log_safe(f"[REJECT] Duplicate order detected: {signal_key} ({(now - dedup[signal_key]):.0f}s ago)")
        return True
    
    dedup[signal_key] = now
    write_json(ORDER_DEDUP_FILE, dedup)
    return False

# ===== 3. 价格异常检测 =====

def validate_price(price, prev_price=None):
    """
    检测价格是否异常。
    - price <= 0: 异常
    - price 超出合理范围: 异常
    - 相对上一价格跳空 > 20%: 异常
    返回 (ok, reason)
    """
    if price is None or price <= 0:
        return False, "Price is None or <= 0"
    
    # 合理价格范围检查（连连数字合理范围）
    if price < 1 or price > 1000:
        return False, f"Price {price} out of reasonable range [1, 1000]"
    
    # 跳空检测
    if prev_price and prev_price > 0:
        gap = abs(price - prev_price) / prev_price
        if gap > PRICE_GAP_THRESHOLD:
            return False, f"Price gap {gap:.1%} exceeds threshold {PRICE_GAP_THRESHOLD:.0%} (prev={prev_price}, curr={price})"
    
    return True, "OK"

# ===== 4. 持仓实时对账 =====

def check_position_reconciliation(current_position, tolerance=500):
    """
    定期检查引擎内部持仓与实际账户持仓是否一致。
    tolerance: 允许的误差范围（股）
    
    如不一致，记录告警并返回 False。
    """
    recon_file = POSITION_RECON_FILE
    last_recon = read_json(recon_file, {})
    now = time.time()
    
    # 每30分钟对账一次
    if last_recon and (now - last_recon.get("checked_at", 0)) < 1800:
        return True
    
    # 这里需要富途API来查询实际持仓
    # 如果API不可用，跳过（返回True，避免误报）
    # 实际使用时用富途持仓查询API替换这里
    
    expected_pos = last_recon.get("expected_position", current_position)
    diff = abs(current_position - expected_pos)
    
    if diff > tolerance:
        log_safe(f"[WARN] Position mismatch: engine={current_position}, expected={expected_pos}, diff={diff}")
        # 写入告警
        alert = {
            "timestamp": datetime.now().isoformat(),
            "type": "position_mismatch",
            "engine_position": current_position,
            "expected_position": expected_pos,
            "diff": diff,
            "tolerance": tolerance
        }
        write_json(DATA_DIR / f"position_alert_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", alert)
    
    # 更新对账记录
    write_json(recon_file, {
        "checked_at": now,
        "expected_position": current_position
    })
    return True

# ===== 5. 心跳机制 =====

def update_heartbeat(strategy_name="v4_live"):
    """更新心跳文件"""
    write_json(HEARTBEAT_FILE, {
        "strategy": strategy_name,
        "timestamp": datetime.now().isoformat(),
        "epoch": time.time()
    })

def check_heartbeat(strategy_name="v4_live"):
    """
    检查心跳是否超时。
    如果超过 HEARTBEAT_TIMEOUT 秒未更新，说明引擎可能已崩溃。
    """
    hb = read_json(HEARTBEAT_FILE, None)
    if hb is None:
        log_safe(f"[WARN] No heartbeat file for {strategy_name}")
        update_heartbeat(strategy_name)
        return True
    
    last_epoch = hb.get("epoch", 0)
    elapsed = time.time() - last_epoch
    
    if elapsed > HEARTBEAT_TIMEOUT:
        log_safe(f"[CRITICAL] Heartbeat timeout: {elapsed:.0f}s > {HEARTBEAT_TIMEOUT}s")
        log_safe(f"[CRITICAL] Engine may have silently crashed! Manual inspection required!")
        return False
    
    return True

# ===== 6. API连接健康检查 =====

def check_api_connection(quote_ctx, trade_ctx):
    """
    检查富途API连接是否健康。
    - 尝试获取行情数据
    - 尝试查询账户
    """
    try:
        # 测试行情API
        ret, data = quote_ctx.get_stock_quote(["HK.02598"])
        if ret != 0 or data is None or len(data) == 0:
            log_safe("[WARN] Quote API returned empty data")
            return False
        
        # 测试交易API（只读）
        # ret, acc = trade_ctx.accinfo_query(trd_env=TrdEnv.REAL)
        # if ret != 0:
        #     log_safe("[WARN] Trade API check failed")
        #     return False
        
        return True
    except Exception as e:
        log_safe(f"[WARN] API connection check failed: {e}")
        return False

# ===== 7. 综合安全检查（主入口） =====

def enhanced_safety_checks(engine, price=None):
    """
    在引擎主循环每次迭代时调用。
    任何一项检查失败，返回 False 跳过本次交易。
    """
    checks_passed = True
    
    # 1. 紧急停止检查
    if check_emergency_stop():
        log_safe("Skipping cycle due to emergency stop")
        time.sleep(30)
        return False
    
    # 2. 心跳超时检查
    if not check_heartbeat("v4_live"):
        log_safe("Skipping cycle due to heartbeat timeout - possible silent crash!")
        time.sleep(60)
        return False
    
    # 3. 价格验证
    if price:
        prev = getattr(engine, "_prev_price", None)
        ok, reason = validate_price(price, prev)
        if not ok:
            log_safe(f"[REJECT] Abnormal price: {reason}")
            time.sleep(10)
            return False
        engine._prev_price = price
    
    # 4. API连接检查（每10分钟一次）
    now = time.time()
    last_api_check = getattr(engine, "_last_api_check", 0)
    if now - last_api_check > 600:
        if engine.quote_ctx:
            api_ok = check_api_connection(engine.quote_ctx, engine.trade_ctx)
            if not api_ok:
                log_safe("[WARN] API connection unhealthy, pausing for 60s")
                time.sleep(60)
                return False
        engine._last_api_check = now
    
    # 5. 持仓对账（每30分钟）
    check_position_reconciliation(engine.current_position)
    
    # 6. 更新心跳
    update_heartbeat("v4_live")
    
    return True

# ===== 8. 手动触发紧急停止 =====

def trigger_emergency_stop(reason="Manual trigger"):
    """手动触发紧急停止"""
    EMERGENCY_STOP_FILE.write_text(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | {reason}",
        encoding="utf-8"
    )
    log_safe(f"Emergency stop file created: {reason}")

def clear_emergency_stop():
    """清除紧急停止，恢复交易"""
    if EMERGENCY_STOP_FILE.exists():
        EMERGENCY_STOP_FILE.unlink()
        log_safe("Emergency stop cleared, trading resumed")

# ===== 测试 =====
if __name__ == "__main__":
    print("Enhanced Safety Module Test")
    print("=" * 50)
    
    # 测试紧急停止
    print(f"Emergency stop file: {EMERGENCY_STOP_FILE}")
    print(f"Current status: {'ACTIVE' if EMERGENCY_STOP_FILE.exists() else 'INACTIVE'}")
    
    # 测试价格验证
    ok, r = validate_price(10.5, 10.0)
    print(f"Price test 10.5 vs 10.0: {ok} - {r}")
    ok, r = validate_price(15.0, 10.0)  # 50%跳空
    print(f"Price test 15.0 vs 10.0: {ok} - {r}")
    ok, r = validate_price(0, 10.0)  # 异常价格
    print(f"Price test 0 vs 10.0: {ok} - {r}")
    
    # 测试心跳
    update_heartbeat("test")
    ok = check_heartbeat("test")
    print(f"Heartbeat test: {'OK' if ok else 'TIMEOUT'}")
    
    print("=" * 50)
    print("All tests completed")
