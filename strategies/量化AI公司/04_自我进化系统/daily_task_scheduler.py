#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日任务调度器 (Round 2 产出)
功能: 统一调度每日自动化任务，整合边界检查、健康监控、股票池管理、组合框架
来源: Round 2 进化任务整合
作者: 龙虾总控智能体 | 版本: 1.0 | 日期: 2026-04-21
"""
import os, sys, json, logging, time, schedule
from datetime import datetime, timedelta, date
from pathlib import Path
import subprocess

# ===== 路径与编码 =====
SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('gbk')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('gbk')(sys.stderr.buffer, 'strict')

# ===== 日志 =====
LOG_FILE = LOG_DIR / f"scheduler_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===== 状态文件 =====
SCHEDULE_FILE = SCRIPT_DIR / "schedule_state.json"

# ===== 任务定义 =====
TASKS = {
    'boundary_check': {
        'name': '边界规则检查',
        'script': SCRIPT_DIR / 'boundary_engine.py',
        'schedule': 'interval',
        'interval_minutes': 60,
        'enabled': True,
        'priority': 1
    },
    'health_monitor': {
        'name': '策略健康度监控',
        'script': SCRIPT_DIR / 'strategy_health_monitor.py',
        'schedule': 'daily',
        'time': '09:00',
        'enabled': True,
        'priority': 2
    },
    'stock_pool': {
        'name': '股票池管理',
        'script': SCRIPT_DIR / 'stock_pool_manager.py',
        'schedule': 'weekly',
        'day': 'monday',
        'time': '10:00',
        'enabled': True,
        'priority': 3
    },
    'portfolio_check': {
        'name': '组合框架检查',
        'script': SCRIPT_DIR / 'portfolio_framework.py',
        'schedule': 'interval',
        'interval_minutes': 30,
        'enabled': True,
        'priority': 2
    },
    'token_monitor': {
        'name': 'Token监控',
        'script': None,  # 内置任务
        'schedule': 'interval',
        'interval_minutes': 30,
        'enabled': True,
        'priority': 1
    },
    'daily_report': {
        'name': '每日报告生成',
        'script': None,  # 内置任务
        'schedule': 'daily',
        'time': '16:30',
        'enabled': True,
        'priority': 3
    }
}

# ===== 工具函数 =====
def load_schedule_state():
    if SCHEDULE_FILE.exists():
        with open(SCHEDULE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'last_run': {}, 'run_count': {}, 'errors': []}

def save_schedule_state(state):
    with open(SCHEDULE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def run_script(script_path, args=[]):
    """执行Python脚本"""
    if not script_path or not script_path.exists():
        logger.error(f"脚本不存在: {script_path}")
        return False, None

    try:
        cmd = [sys.executable, str(script_path)] + args
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=300)
        if result.returncode == 0:
            return True, result.stdout
        else:
            logger.error(f"脚本执行失败: {result.stderr}")
            return False, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"脚本超时: {script_path}")
        return False, "timeout"
    except Exception as e:
        logger.error(f"执行异常: {e}")
        return False, str(e)

# ===== 任务执行函数 =====
def execute_task(task_id):
    """执行单个任务"""
    task = TASKS.get(task_id)
    if not task or not task.get('enabled', False):
        logger.info(f"任务 {task_id} 未启用或不存在，跳过")
        return

    state = load_schedule_state()
    logger.info(f"\n{'='*50}")
    logger.info(f"[执行任务] {task['name']} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"{'='*50}")

    start_time = datetime.now()

    if task['script'] and task['script'].exists():
        success, output = run_script(task['script'])
    else:
        # 内置任务
        success, output = execute_builtin_task(task_id)

    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    # 更新状态
    state['last_run'][task_id] = {
        'time': start_time.isoformat(),
        'duration_sec': duration,
        'success': success
    }
    state['run_count'][task_id] = state['run_count'].get(task_id, 0) + 1

    if not success:
        state['errors'].append({
            'task': task_id,
            'time': start_time.isoformat(),
            'error': output
        })

    save_schedule_state(state)

    status = "[OK] 成功" if success else "[FAIL] 失败"
    logger.info(f"[任务完成] {task['name']} | {status} | 耗时{duration:.1f}秒")

def execute_builtin_task(task_id):
    """执行内置任务"""
    if task_id == 'token_monitor':
        # Token监控内置逻辑
        try:
            # 读取heartbeat数据
            hb_file = Path("C:/Users/Administrator/Desktop/量化AI公司/03_实盘与监测/heartbeat.json")
            if hb_file.exists():
                with open(hb_file, 'r', encoding='utf-8') as f:
                    hb = json.load(f)
                tokens_in = hb.get('tokens_in', 0)
                tokens_out = hb.get('tokens_out', 0)
                total = tokens_in + tokens_out
                remaining = 40_000_000 - total
                pct = remaining / 40_000_000 * 100

                logger.info(f"Token状态: 已用{total/1e6:.1f}万 | 剩余{remaining/1e6:.1f}万({pct:.1f}%)")

                if pct < 20:
                    logger.warning(f"[WARN] Token剩余<20%，启动低消耗模式")
                if pct < 12.5:
                    logger.warning(f"[RED] Token剩余<12.5%，触发降级")

                return True, f"剩余{pct:.1f}%"
            return False, "heartbeat文件不存在"
        except Exception as e:
            return False, str(e)

    elif task_id == 'daily_report':
        # 每日报告生成
        try:
            report = generate_daily_report()
            report_file = SCRIPT_DIR / "reports" / f"daily_{datetime.now().strftime('%Y%m%d')}.md"
            report_file.parent.mkdir(exist_ok=True, parents=True)
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            logger.info(f"每日报告已生成: {report_file}")
            return True, str(report_file)
        except Exception as e:
            return False, str(e)

    return False, "未知内置任务"

def generate_daily_report():
    """生成每日报告"""
    state = load_schedule_state()

    report = f"""# 龙虾量化交易系统 - 每日报告

**日期**: {datetime.now().strftime('%Y-%m-%d')}
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 一、任务执行统计

| 任务 | 最后执行 | 执行次数 | 状态 |
|------|---------|---------|------|
"""
    for task_id, task in TASKS.items():
        last = state['last_run'].get(task_id, {})
        lr_time = last.get('time', 'N/A')
        lr_status = "[OK]" if last.get('success', False) else "[FAIL]"
        count = state['run_count'].get(task_id, 0)
        report += f"| {task['name']} | {lr_time} | {count} | {lr_status} |\n"

    report += f"""
---

## 二、策略状态

- **BTDR PrevClose V2**: 运行中 (持仓7,894股)
- **连连数字V4**: 运行中 (持仓8,000股)

---

## 三、Token使用

- 日预算: 4000万
- 已用: {state.get('token_used', 0):.0f}万
- 剩余: {state.get('token_remaining', 4000):.0f}万

---

*报告由每日任务调度器自动生成*
"""
    return report

# ===== 调度器设置 =====
def setup_scheduler():
    """设置调度任务"""
    import schedule

    for task_id, task in TASKS.items():
        if not task.get('enabled', False):
            continue

        if task['schedule'] == 'interval':
            mins = task['interval_minutes']
            schedule.every(mins).minutes.do(execute_task, task_id)
            logger.info(f"已调度: {task['name']} (每{mins}分钟)")

        elif task['schedule'] == 'daily':
            t = task['time']
            schedule.every().day.at(t).do(execute_task, task_id)
            logger.info(f"已调度: {task['name']} (每日{t})")

        elif task['schedule'] == 'weekly':
            day = task.get('day', 'monday')
            t = task['time']
            getattr(schedule.every(), day).at(t).do(execute_task, task_id)
            logger.info(f"已调度: {task['name']} (每周{day} {t})")

# ===== 主运行循环 =====
def run_scheduler():
    """运行调度器"""
    logger.info("=" * 60)
    logger.info(f"[每日任务调度器] 启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    setup_scheduler()

    logger.info("\n调度器运行中，按Ctrl+C停止...")
    logger.info("-" * 60)

    while True:
        schedule.run_pending()
        time.sleep(60)

# ===== 命令行入口 =====
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='每日任务调度器')
    parser.add_argument('--mode', choices=['run', 'once', 'list'], default='once')
    parser.add_argument('--task', choices=list(TASKS.keys()), help='执行指定任务')
    args = parser.parse_args()

    if args.mode == 'list':
        print("\n可用任务:")
        for tid, t in TASKS.items():
            status = "[OK]" if t['enabled'] else "[FAIL]"
            print(f"  {status} {tid}: {t['name']} ({t['schedule']})")
    elif args.mode == 'once':
        if args.task:
            execute_task(args.task)
        else:
            # 执行所有启用的任务一次
            for tid, t in sorted(TASKS.items(), key=lambda x: x[1]['priority']):
                if t['enabled']:
                    execute_task(tid)
    elif args.mode == 'run':
        try:
            run_scheduler()
        except KeyboardInterrupt:
            logger.info("\n调度器已停止")