#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
边界规则执行引擎 (Round 2 核心产出)
功能: 自动化执行B-001至B-005边界规则，支持L0-L1自动化等级
来源: memory/BOUNDARY_RULES.md 第一轮进化成果
作者: 龙虾总控智能体 | 版本: 1.0 | 日期: 2026-04-21
"""
import os, sys, json, time, logging
from datetime import datetime, date
from pathlib import Path

# ===== 路径配置 =====
SCRIPT_DIR = Path(__file__).parent
WORKSPACE_ROOT = Path("C:/Users/Administrator/.qclaw/workspace-agent-40f5a53e")
MEMORY_DIR = WORKSPACE_ROOT / "memory"
SYSTEM_ROOT = Path("C:/Users/Administrator/Desktop/量化AI公司")
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

# ===== Windows控制台编码修复 =====
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('gbk')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('gbk')(sys.stderr.buffer, 'strict')

# ===== 日志配置 =====
LOG_FILE = LOG_DIR / f"boundary_engine_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ===== 状态文件 =====
STATE_FILE = SCRIPT_DIR / "boundary_state.json"

# ===== 全局常量 =====
DAILY_TOKEN_BUDGET = 40_000_000    # 4000万Token
DEGRADE_THRESHOLD = 35_000_000    # 3500万降级
CIRCUIT_BREAKER = 36_000_000      # 3600万熔断
TOKEN_WARNING = 0.20              # 剩余<20%预警
TOKEN_CRITICAL = 0.125            # 剩余<12.5%降级

# ===== 代理签名 =====
def _signature():
    return f"[边界引擎 @ {datetime.now().strftime('%H:%M:%S')}]"

# ===== 工具函数 =====
def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'last_run': None, 'run_count': 0, 'violations': [],
        'b001_last_check': None, 'b002_last_check': None,
        'b003_last_check': None, 'b004_last_check': None,
        'b005_last_check': None
    }

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def notify_wecom(msg):
    logger.info(f"{_signature()} [企微通知] {msg}")

def load_heartbeat():
    hbf = SYSTEM_ROOT / "03_实盘与监测" / "heartbeat.json"
    if hbf.exists():
        try:
            with open(hbf, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: pass
    return {}

# ============================================================
# B-001: 策略健康度自动检查
# ============================================================
def check_b001_strategy_health(state):
    logger.info(f"{_signature()} [B-001] 策略健康度检查...")
    # 加载统一面板状态
    dashboard_file = SYSTEM_ROOT / "03_实盘与监测" / "dashboard_state.json"
    alerts = []

    if dashboard_file.exists():
        try:
            with open(dashboard_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # 模拟检查逻辑（实际需要真实回测数据）
            # 本次检查示例：BTDR持仓7,894股，成本$17.52，当前价$12.55
            # 浮亏-$39,230 (-28.2%) → 红色预警
            pnl_pct = data.get('btdr_pnl_pct', 0)
            if pnl_pct < -20:
                alerts.append({
                    'rule': 'B-001', 'level': '[RED] 红色预警',
                    'strategy': 'BTDR PrevClose V2',
                    'message': f'浮亏{pnl_pct:.1f}%，超过-20%红色阈值',
                    'action': '建议暂停实盘交易，启动策略失效分析',
                    'time': datetime.now().isoformat()
                })
        except Exception as e:
            logger.warning(f"B-001读取面板状态失败: {e}")

    if alerts:
        logger.warning(f"{_signature()} [B-001] 发现 {len(alerts)} 个预警")
        for a in alerts:
            logger.warning(f"  → {a['strategy']}: {a['message']}")
        notify_wecom(f"[B-001红色预警] {alerts[0]['message']} | {alerts[0]['action']}")
        state['violations'].extend(alerts)
    else:
        logger.info(f"{_signature()} [B-001] [OK] 策略健康度正常")

    state['b001_last_check'] = datetime.now().isoformat()
    return alerts

# ============================================================
# B-002: Token战略储备机制
# ============================================================
def check_b002_token_reserve(state):
    logger.info(f"{_signature()} [B-002] Token战略储备检查...")
    hb = load_heartbeat()

    tokens_in = hb.get('tokens_in', 0)
    tokens_out = hb.get('tokens_out', 0)
    total_used = tokens_in + tokens_out

    remaining = DAILY_TOKEN_BUDGET - total_used
    remaining_pct = remaining / DAILY_TOKEN_BUDGET

    status = "[OK] 正常"
    level = "INFO"
    msg = f"已用{total_used/1e6:.1f}万Token，剩余{remaining/1e6:.1f}万({remaining_pct*100:.1f}%)"

    if remaining_pct < 0.10:
        status = "[STOP] 熔断"
        level = "CRITICAL"
        msg += " | [WARN] 剩余<10%，触发熔断，暂停所有非必要功能"
    elif remaining_pct < 0.125:
        status = "[RED] 降级"
        level = "WARNING"
        msg += " | [WARN] 剩余<12.5%，触发降级模式"
    elif remaining_pct < 0.20:
        status = "[WARN] 预警"
        level = "WARNING"
        msg += " | [WARN] 剩余<20%，启动低消耗模式"

    logger.log(logging.WARNING if level != "INFO" else logging.INFO,
               f"{_signature()} [B-002] {status} - {msg}")

    if level != "INFO":
        notify_wecom(f"[B-002 Token] {status} {msg}")

    state['b002_last_check'] = datetime.now().isoformat()
    state['token_status'] = {'used': total_used, 'remaining': remaining,
                              'pct': remaining_pct, 'level': level}
    return level, msg

# ============================================================
# B-003: 数据覆盖度门槛
# ============================================================
def check_b003_data_coverage(state):
    logger.info(f"{_signature()} [B-003] 数据覆盖度检查...")
    required_assets = ['US.BTDR', 'HK.02598', 'US.CLSK', 'US.MARA', 'US.RIOT']
    covered = []
    missing = []

    for code in required_assets:
        data_file = SYSTEM_ROOT / "02_回测数据" / "每日新回测" / f"{code.replace('.','_')}_kline.json"
        if data_file.exists():
            covered.append(code)
        else:
            missing.append(code)

    pct = len(covered) / len(required_assets) * 100
    status = "[OK] 达标" if pct >= 60 else "[WARN] 不足"
    logger.info(f"{_signature()} [B-003] {status} - 覆盖{len(covered)}/{len(required_assets)}个标的({pct:.0f}%)")

    if missing:
        logger.info(f"{_signature()} [B-003] 缺失数据: {', '.join(missing)}")

    state['b003_last_check'] = datetime.now().isoformat()
    state['data_coverage'] = {'covered': covered, 'missing': missing, 'pct': pct}
    return pct, covered, missing

# ============================================================
# B-004: 记忆文件分卷机制
# ============================================================
def check_b004_memory_archive(state):
    logger.info(f"{_signature()} [B-004] 记忆分卷检查...")
    if not MEMORY_DIR.exists():
        logger.warning(f"{_signature()} [B-004] 记忆目录不存在，跳过")
        return []

    files = sorted(MEMORY_DIR.glob("*.md"))
    archives = [f for f in files if f.stem not in ['BOUNDARY_RULES', 'evolution_round_1_20260421']]

    sizes = [(f, f.stat().st_size) for f in archives]
    sizes.sort(key=lambda x: x[1], reverse=True)
    oversized = [(f, s) for f, s in sizes if s > 50 * 1024]  # >50KB

    alerts = []
    if oversized:
        for f, s in oversized:
            logger.warning(f"{_signature()} [B-004] [WARN] {f.name} ({s/1024:.0f}KB > 50KB)")
            alerts.append({'file': f.name, 'size_kb': s/1024})
        notify_wecom(f"[B-004] {len(alerts)}个记忆文件过大，建议分卷处理")

    state['b004_last_check'] = datetime.now().isoformat()
    state['memory_files'] = {'total': len(archives), 'oversized': len(oversized)}
    return alerts

# ============================================================
# B-005: 指标缓存机制
# ============================================================
def check_b005_indicator_cache(state):
    logger.info(f"{_signature()} [B-005] 指标缓存检查...")
    cache_dir = SYSTEM_ROOT / "02_回测数据" / "cache"
    cache_dir.mkdir(exist_ok=True, parents=True)

    # 清理超过7天的缓存
    import time as time_module
    now = time_module.time()
    max_age = 7 * 24 * 3600
    cleaned = 0

    for f in cache_dir.glob("*.json"):
        if now - f.stat().st_mtime > max_age:
            try: f.unlink(); cleaned += 1
            except: pass

    logger.info(f"{_signature()} [B-005] [OK] 缓存清理完成，清理{cleaned}个过期文件")

    state['b005_last_check'] = datetime.now().isoformat()
    state['cache_cleaned'] = cleaned
    return cleaned

# ============================================================
# 主执行函数
# ============================================================
def run_all_checks():
    logger.info("=" * 60)
    logger.info(f"{_signature()} 【边界规则执行引擎】启动")
    logger.info(f"{_signature()} Round 2 执行 - 代码实现版 v1.0")
    logger.info("=" * 60)

    state = load_state()
    state['run_count'] += 1
    state['last_run'] = datetime.now().isoformat()

    # 依次执行5条规则
    check_b001_strategy_health(state)
    check_b002_token_reserve(state)
    pct, covered, missing = check_b003_data_coverage(state)
    check_b004_memory_archive(state)
    check_b005_indicator_cache(state)

    # 汇总报告
    logger.info("=" * 60)
    logger.info(f"{_signature()} 【本轮执行完成】")
    logger.info(f"{_signature()} 运行次数: {state['run_count']}")
    logger.info(f"{_signature()} Token状态: {state.get('token_status',{}).get('level','未知')}")
    logger.info(f"{_signature()} 数据覆盖: {pct:.0f}% ({len(covered)}/{len(covered)+len(missing)} 标的)")
    logger.info(f"{_signature()} 违规记录: {len(state.get('violations',[]))}条")
    logger.info("=" * 60)

    save_state(state)
    return state

def run_single_rule(rule_id):
    state = load_state()
    if rule_id == 'B-001': return check_b001_strategy_health(state)
    elif rule_id == 'B-002': return check_b002_token_reserve(state)
    elif rule_id == 'B-003': return check_b003_data_coverage(state)
    elif rule_id == 'B-004': return check_b004_memory_archive(state)
    elif rule_id == 'B-005': return check_b005_indicator_cache(state)
    else: logger.error(f"未知规则: {rule_id}"); return None

# ===== 命令行入口 =====
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='边界规则执行引擎')
    parser.add_argument('--rule', choices=['B-001','B-002','B-003','B-004','B-005','all'],
                        default='all', help='执行指定规则或全部')
    parser.add_argument('--daemon', action='store_true', help='守护模式（定期执行）')
    args = parser.parse_args()

    if args.daemon:
        logger.info(f"{_signature()} 守护模式启动，间隔300秒")
        while True:
            run_all_checks()
            time.sleep(300)
    elif args.rule == 'all':
        run_all_checks()
    else:
        result = run_single_rule(args.rule)
        if result is not None:
            print(json.dumps(result, ensure_ascii=False, indent=2))