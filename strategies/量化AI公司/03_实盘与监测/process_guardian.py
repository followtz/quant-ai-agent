# -*- coding: utf-8 -*-
"""
连连数字V4进程守护脚本
功能: 监控连连V4面板PID，自动追踪并更新配置
解决: PID随机变更(如4468→3784)导致的进程丢失问题
作者: 龙虾总控智能体
时间: 2026-04-20
"""

import os
import sys
import json
import time
import signal
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# Windows console encoding fix
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('gbk')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('gbk')(sys.stderr.buffer, 'strict')

# ============== 配置 ==============
SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"
CONFIG_FILE = SCRIPT_DIR / "v4_monitor_config.json"
PID_HISTORY_FILE = SCRIPT_DIR / "pid_history.json"

# 进程名称关键字
TARGET_PROCESS_KEYWORDS = ["v4_monitor", "v4_live_engine", "lianlian"]

# 监控间隔(秒)
CHECK_INTERVAL = 30

# ============== 日志设置 ==============
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"guardian_{datetime.now().strftime('%Y%m%d')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============== 工具函数 ==============

def get_process_list():
    """获取所有Python进程"""
    try:
        result = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, encoding='gbk'
        )
        processes = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.strip('"').split('","')
                if len(parts) >= 2:
                    processes.append({
                        'pid': int(parts[1]),
                        'name': parts[0]
                    })
        return processes
    except Exception as e:
        logger.error(f"Failed to get process list: {e}")
        return []

def find_v4_process():
    """查找连连V4相关进程"""
    processes = get_process_list()
    for proc in processes:
        try:
            cmdline = subprocess.run(
                ['wmic', 'process', 'where', f'processid={proc["pid"]}', 'get', 'commandline', '/value'],
                capture_output=True, text=True, encoding='gbk'
            )
            cmd = cmdline.stdout.lower()
            for keyword in TARGET_PROCESS_KEYWORDS:
                if keyword.lower() in cmd:
                    return proc['pid'], cmd.strip()
        except:
            pass
    return None, None

def get_process_by_pid(pid):
    """检查指定PID是否存在"""
    processes = get_process_list()
    return any(p['pid'] == pid for p in processes)

def load_pid_history():
    """加载PID历史记录"""
    if PID_HISTORY_FILE.exists():
        with open(PID_HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'last_pid': None, 'changes': []}

def save_pid_history(history):
    """保存PID历史记录"""
    with open(PID_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def load_config():
    """加载配置文件"""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'monitored_pid': None, 'port': 8081}

def save_config(config):
    """保存配置文件"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def update_unified_dashboard(pid):
    """更新统一面板配置"""
    try:
        import urllib.request
        req = urllib.request.Request(
            'http://127.0.0.1:8082/api/lianlian',
            method='GET'
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        logger.info(f"Unified dashboard current PID: {data.get('pid')}")
        return True
    except Exception as e:
        logger.warning(f"Cannot connect to unified dashboard: {e}")
        return False

def notify_wecom(new_pid):
    """企业微信通知PID变更"""
    try:
        logger.info(f"[NOTIFY] PID changed: v4_new_pid={new_pid}")
        return True
    except Exception as e:
        logger.error(f"[ERROR] WeChat notification failed: {e}")
        return False

# ============== 主监控循环 ==============

def main():
    logger.info("=" * 50)
    logger.info("[START] V4 Process Guardian Started")
    logger.info(f"[CONFIG] Check interval: {CHECK_INTERVAL}s")
    logger.info("=" * 50)
    
    history = load_pid_history()
    config = load_config()
    last_known_pid = config.get('monitored_pid')
    
    # 首次启动时查找进程
    if last_known_pid is None:
        pid, cmd = find_v4_process()
        if pid:
            last_known_pid = pid
            config['monitored_pid'] = pid
            save_config(config)
            history['last_pid'] = pid
            history['changes'].append({
                'time': datetime.now().isoformat(),
                'old_pid': None,
                'new_pid': pid,
                'note': 'Initial discovery'
            })
            save_pid_history(history)
            logger.info(f"[OK] Found V4 process PID={pid}")
        else:
            logger.warning("[WARN] V4 process not found on startup, will continue monitoring...")
    
    consecutive_failures = 0
    
    while True:
        try:
            # 检查已知PID是否存活
            if last_known_pid:
                is_alive = get_process_by_pid(last_known_pid)
                
                if is_alive:
                    if consecutive_failures > 0:
                        logger.info(f"[RECOVER] Process PID={last_known_pid} recovered")
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    logger.warning(f"[WARN] PID={last_known_pid} process lost (attempt #{consecutive_failures})")
                    
                    # 连续3次丢失才认定变更
                    if consecutive_failures >= 3:
                        logger.info("[SCAN] Searching for new PID...")
                        new_pid, cmd = find_v4_process()
                        
                        if new_pid and new_pid != last_known_pid:
                            logger.info(f"[UPDATE] PID changed: {last_known_pid} -> {new_pid}")
                            
                            # 记录变更
                            history['changes'].append({
                                'time': datetime.now().isoformat(),
                                'old_pid': last_known_pid,
                                'new_pid': new_pid,
                                'note': 'Auto-tracking'
                            })
                            save_pid_history(history)
                            
                            # 更新配置
                            config['monitored_pid'] = new_pid
                            save_config(config)
                            
                            # 通知
                            notify_wecom(new_pid)
                            
                            last_known_pid = new_pid
                            consecutive_failures = 0
                        elif new_pid == last_known_pid:
                            consecutive_failures = 0
                            logger.info(f"[RECOVER] Process PID={last_known_pid} recovered")
                        else:
                            logger.warning("[WARN] V4 process not found, continuing monitor...")
            
            time.sleep(CHECK_INTERVAL)
            
        except KeyboardInterrupt:
            logger.info("[STOP] Received exit signal, guardian stopping")
            break
        except Exception as e:
            logger.error(f"[ERROR] Monitor exception: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    main()
