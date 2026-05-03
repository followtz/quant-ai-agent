# -*- coding: utf-8 -*-
"""
进程守护脚本模板 (daemon_template.py)
龙虾总控智能体 · 标准化进程守护框架
版本: v1.0 | 2026-04-21

使用说明:
- 所有进程守护脚本必须基于此模板生成
- 禁止直接硬编码进程名/端口，优先通过配置传入
- 日志必须写入 {workspace}/data/logs/ 目录
"""

import os
import sys
import time
import json
import logging
import subprocess
import signal
import requests
from datetime import datetime
from pathlib import Path

# ============================================================
# 路径配置（禁止硬编码，根据运行时环境自动推导）
# ============================================================
WORKSPACE = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).parent
LOG_DIR = WORKSPACE / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 导入企业微信推送工具（禁止硬编码 Webhook URL）
sys.path.insert(0, str(WORKSPACE / "utils"))
from wechat_push import send_wecom_notification, send_email_copy

# ============================================================
# 日志配置
# ============================================================
def setup_logger(name: str, log_file: str = None) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    if not logger.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        if log_file:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
    return logger


# ============================================================
# 错误计数器（死循环防护）
# ============================================================
class ErrorTracker:
    """1小时内同一策略连续报错超过3次 → DISABLED"""

    def __init__(self, threshold: int = 3, window_seconds: int = 3600):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.errors: dict[str, list[float]] = {}  # strategy_name -> [timestamp, ...]

    def record(self, strategy_name: str) -> bool:
        """记录一次错误，返回是否触发熔断"""
        now = time.time()
        if strategy_name not in self.errors:
            self.errors[strategy_name] = []
        self.errors[strategy_name].append(now)
        # 清理窗口外的旧记录
        self.errors[strategy_name] = [
            t for t in self.errors[strategy_name] if now - t < self.window_seconds
        ]
        if len(self.errors[strategy_name]) > self.threshold:
            return True  # 触发熔断
        return False

    def is_disabled(self, strategy_name: str) -> bool:
        now = time.time()
        if strategy_name not in self.errors:
            return False
        # 清理过期
        self.errors[strategy_name] = [
            t for t in self.errors[strategy_name] if now - t < self.window_seconds
        ]
        return len(self.errors[strategy_name]) > self.threshold

    def reset(self, strategy_name: str):
        if strategy_name in self.errors:
            del self.errors[strategy_name]


# ============================================================
# 策略熔断状态管理器
# ============================================================
class CircuitBreaker:
    """策略熔断状态：NORMAL / DISABLED"""

    STATUS_FILE = LOG_DIR / "circuit_status.json"

    @staticmethod
    def load() -> dict[str, str]:
        if CircuitBreaker.STATUS_FILE.exists():
            try:
                with open(CircuitBreaker.STATUS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def save(status: dict[str, str]):
        with open(CircuitBreaker.STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status, f, ensure_ascii=False, indent=2)

    @staticmethod
    def disable(strategy_name: str, logger: logging.Logger):
        status = CircuitBreaker.load()
        status[strategy_name] = "DISABLED"
        CircuitBreaker.save(status)
        logger.error(f"[熔断] 策略 {strategy_name} 已标记为 DISABLED")
        # 发送企业微信 + 邮箱双重通知
        send_wecom_notification(
            f"🚨【最高级别警报】策略 {strategy_name} 已被自动熔断（1小时内连续报错超过3次）",
            alert_level="CRITICAL"
        )
        send_email_copy(
            subject=f"[龙虾警报] 策略 {strategy_name} 熔断通知",
            body=f"策略 {strategy_name} 已于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 被自动熔断，"
                 f"请登录系统检查。\n\n此为自动触发的人机安全机制，无需回复。"
        )

    @staticmethod
    def is_disabled(strategy_name: str) -> bool:
        status = CircuitBreaker.load()
        return status.get(strategy_name) == "DISABLED"

    @staticmethod
    def restore(strategy_name: str):
        status = CircuitBreaker.load()
        if strategy_name in status:
            del status[strategy_name]
            CircuitBreaker.save(status)


# ============================================================
# 进程查找工具
# ============================================================
def find_process_by_name(name: str) -> list[int]:
    """跨平台查找进程 PID 列表"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-Process -Name '{name}' -ErrorAction SilentlyContinue).Id"],
                capture_output=True, text=True, encoding="utf-8"
            )
            pids = [int(line.strip()) for line in result.stdout.strip().split("\n") if line.strip().isdigit()]
            return pids
        else:
            result = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True)
            return [int(line) for line in result.stdout.strip().split("\n") if line.strip().isdigit()]
    except Exception:
        return []


def find_process_by_port(port: int) -> list[int]:
    """通过端口号查找进程 PID"""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["powershell", "-Command",
                 f"(Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue).OwningProcess | Get-Unique"],
                capture_output=True, text=True, encoding="utf-8"
            )
            pids = [int(line.strip()) for line in result.stdout.strip().split("\n") if line.strip().isdigit()]
            return pids
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"], capture_output=True, text=True
            )
            return [int(line) for line in result.stdout.strip().split("\n") if line.strip().isdigit()]
    except Exception:
        return []


# ============================================================
# 交易日志写入（JSON 格式，强制约束）
# ============================================================
def log_trade(
    symbol: str,
    action: str,       # "BUY" | "SELL"
    price: float,
    volume: int,
    status: str,       # "FILLED" | "REJECTED" | "PENDING"
    strategy: str = "UNKNOWN",
    extra: dict = None
):
    """写入标准 JSON 交易日志"""
    log_file = LOG_DIR / "trades.jsonl"
    entry = {
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "symbol": symbol,
        "action": action,
        "price": round(price, 4),
        "volume": volume,
        "status": status,
        "strategy": strategy,
        **(extra or {})
    }
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


# ============================================================
# 错误报告标准格式
# ============================================================
def format_error_report(error_code: str, context: str, suggested_fix: str) -> str:
    return (
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"[Error Code] {error_code}\n"
        f"[Context] {context}\n"
        f"[Suggested Fix] {suggested_fix}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# ============================================================
# 主守护循环（子类覆盖）
# ============================================================
class DaemonTemplate:
    """进程守护基类，子类实现 _check() 和 _run()"""

    def __init__(
        self,
        name: str,
        check_interval: int = 30,
        restart_cmd: list = None,
        process_name: str = None,
        port: int = None,
        logger: logging.Logger = None
    ):
        self.name = name
        self.check_interval = check_interval
        self.restart_cmd = restart_cmd
        self.process_name = process_name
        self.port = port
        self.logger = logger or setup_logger(name)
        self.error_tracker = ErrorTracker()
        self._running = True
        self._setup_signal()

    def _setup_signal(self):
        def handle_signal(signum, frame):
            self.logger.info(f"收到退出信号，优雅关闭 {self.name}...")
            self._running = False
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    def _is_alive(self) -> bool:
        """检测进程是否存活"""
        if self.process_name:
            return len(find_process_by_name(self.process_name)) > 0
        if self.port:
            return len(find_process_by_port(self.port)) > 0
        return False

    def _restart(self):
        """重启进程"""
        self.logger.warning(f"进程 {self.name} 未存活，尝试重启...")
        try:
            if self.process_name:
                for pid in find_process_by_name(self.process_name):
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
                    time.sleep(2)
            if self.restart_cmd:
                subprocess.Popen(
                    self.restart_cmd,
                    cwd=WORKSPACE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                        if sys.platform == "win32" else 0,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.logger.info(f"重启命令已执行: {' '.join(self.restart_cmd)}")
                send_wecom_notification(
                    f"✅ [{self.name}] 进程已自动重启\n时间: {datetime.now().strftime('%H:%M:%S')}"
                )
        except Exception as e:
            self.logger.error(f"重启失败: {e}")

    def _check(self) -> bool:
        """子类实现：自定义健康检查逻辑，返回 True 表示正常"""
        raise NotImplementedError

    def run(self):
        self.logger.info(f"🚀 {self.name} 守护进程启动，检测间隔 {self.check_interval}s")
        while self._running:
            try:
                # 熔断检查
                if CircuitBreaker.is_disabled(self.name):
                    self.logger.warning(f"策略 {self.name} 处于 DISABLED 状态，跳过执行")
                    time.sleep(self.check_interval)
                    continue

                # 基础存活检查
                if not self._is_alive():
                    self.logger.warning(f"进程 {self.name} 未存活，触发重启")
                    self._restart()

                # 自定义检查
                healthy, msg = self._check(), ""
                if healthy:
                    self.error_tracker.reset(self.name)
                else:
                    if self.error_tracker.record(self.name):
                        CircuitBreaker.disable(self.name, self.logger)
                        send_wecom_notification(
                            f"🚨 策略 {self.name} 连续错误超限，已自动熔断",
                            alert_level="CRITICAL"
                        )
                        send_email_copy(
                            subject=f"[龙虾熔断] {self.name} 已自动熔断",
                            body=f"策略 {self.name} 于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 触发熔断。"
                        )
            except Exception as e:
                self.logger.error(f"守护循环异常: {e}")
                if self.error_tracker.record(self.name):
                    CircuitBreaker.disable(self.name, self.logger)
            finally:
                time.sleep(self.check_interval)
        self.logger.info(f"✅ {self.name} 守护进程已退出")
