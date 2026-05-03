# -*- coding: utf-8 -*-
"""
可视化指挥舱 · 状态快照生成器 (dashboard_writer.py)
龙虾总控智能体 · P0 阶段
版本: v1.0 | 2026-04-22

职责：
  - 维护 global_status.json（全局状态快照）
  - 维护 trade_risk.json（交易与风控状态）
  - 追加 decision_evolution.jsonl（决策与进化日志）
  - 敏感信息自动脱敏

调用方式：
  from utils.dashboard_writer import DashboardWriter
  dw = DashboardWriter()
  dw.update_global_status(...)
  dw.update_trade_risk(...)
  dw.append_decision(...)
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

WORKSPACE = Path(__file__).parent.parent
DASHBOARD_DIR = WORKSPACE / "data" / "dashboard"
GLOBAL_STATUS_FILE = DASHBOARD_DIR / "global_status.json"
TRADE_RISK_FILE = DASHBOARD_DIR / "trade_risk.json"
DECISION_FILE = DASHBOARD_DIR / "decision_evolution.jsonl"
STRATEGY_EVOLUTION_FILE = DASHBOARD_DIR / "strategy_evolution.json"
PLAN_BOARD_FILE = DASHBOARD_DIR / "plan_board.json"
TASK_RADAR_FILE = DASHBOARD_DIR / "task_radar.json"

# 敏感字段正则
SENSITIVE_PATTERNS = [
    re.compile(r'(api[_-]?key\s*[:=]\s*)\S+', re.I),
    re.compile(r'(password\s*[:=]\s*)\S+', re.I),
    re.compile(r'(secret\s*[:=]\s*)\S+', re.I),
    re.compile(r'(token\s*[:=]\s*)\S+', re.I),
]  # email等无捕获组的模式单独处理


def _mask_email(text: str) -> str:
    """将邮箱地址脱敏为 u***@domain.com"""
    return re.sub(
        r'\b([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b',
        lambda m: f"{m.group(1)}***@{m.group(3)}",
        text
    )

# ============================================================
# 脱敏工具
# ============================================================

def sanitize(obj: Any) -> Any:
    """递归脱敏：字符串中的敏感信息替换为 ***"""
    if isinstance(obj, str):
        for pat in SENSITIVE_PATTERNS:
            obj = pat.sub(r'\1***', obj)
        obj = _mask_email(obj)
        return obj
    elif isinstance(obj, dict):
        return {sanitize(k): sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize(item) for item in obj]
    return obj


# ============================================================
# DashboardWriter 核心类
# ============================================================

class DashboardWriter:
    def __init__(self):
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
        # 初始化文件（不存在则创建空骨架）
        self._init_files()

    def _init_files(self):
        """确保6个状态文件存在且有合法JSON"""
        # P0 文件
        if not GLOBAL_STATUS_FILE.exists():
            self._write_json(GLOBAL_STATUS_FILE, {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "total_capital": 0,
                "daily_pnl": 0,
                "token_usage": {"used": 0, "budget": 40000000, "percent": 0},
                "active_market": "none",
                "groups": {
                    "risk_control": {"status": "online", "priority": 1},
                    "trade_execution": {"status": "online", "priority": 2},
                    "strategy_research": {"status": "online", "priority": 3},
                    "ai_learning": {"status": "online", "priority": 4}
                },
                "strategies": {
                    "BTDR_PrevClose_V2": {"status": "normal", "panel_port": 8082},
                    "LianLian_V4": {"status": "normal", "panel_port": 8082}
                }
            })

        if not TRADE_RISK_FILE.exists():
            self._write_json(TRADE_RISK_FILE, {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "circuit_breaker": {"level": "L0", "status": "normal"},
                "recent_orders": [],
                "drawdown_monitor": {},
                "error_loop_counter": {}
            })

        if not DECISION_FILE.exists():
            pass  # jsonl 文件可以为空

        # P2 文件
        if not STRATEGY_EVOLUTION_FILE.exists():
            self._write_json(STRATEGY_EVOLUTION_FILE, {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "current_versions": {
                    "BTDR_PrevClose_V2": "v2.0",
                    "LianLian_V4": "v4.0"
                },
                "version_timeline": [],
                "target_radar": []
            })

        if not PLAN_BOARD_FILE.exists():
            self._write_json(PLAN_BOARD_FILE, {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "plans": [],
                "permission_log": []
            })

        if not TASK_RADAR_FILE.exists():
            self._write_json(TASK_RADAR_FILE, {
                "version": "1.0",
                "last_updated": datetime.now().isoformat(),
                "tasks": []
            })

    # ----------------------------------------------------------
    # 全局状态更新
    # ----------------------------------------------------------
    def update_global_status(
        self,
        total_capital: Optional[float] = None,
        daily_pnl: Optional[float] = None,
        token_used: Optional[int] = None,
        token_budget: Optional[int] = None,
        active_market: Optional[str] = None,
        group_status: Optional[Dict[str, str]] = None,
        strategy_status: Optional[Dict[str, Any]] = None,
    ) -> dict:
        """
        更新全局状态快照。
        只传需要更新的字段，其余保留原值。
        返回更新后的完整状态。
        """
        data = self._read_json(GLOBAL_STATUS_FILE)
        data["last_updated"] = datetime.now().isoformat()

        if total_capital is not None:
            data["total_capital"] = total_capital
        if daily_pnl is not None:
            data["daily_pnl"] = round(daily_pnl, 2)
        if token_used is not None:
            budget = token_budget or data["token_usage"]["budget"]
            data["token_usage"] = {
                "used": token_used,
                "budget": budget,
                "percent": round(token_used / budget * 100, 1)
            }
        if token_budget is not None:
            data["token_usage"]["budget"] = token_budget
        if active_market is not None:
            data["active_market"] = active_market
        if group_status is not None:
            for g, s in group_status.items():
                if g in data["groups"]:
                    data["groups"][g]["status"] = s
        if strategy_status is not None:
            for s, v in strategy_status.items():
                if s in data["strategies"]:
                    data["strategies"][s].update(v)

        data = sanitize(data)
        self._write_json(GLOBAL_STATUS_FILE, data)
        return data

    # ----------------------------------------------------------
    # 交易与风控更新
    # ----------------------------------------------------------
    def update_trade_risk(
        self,
        circuit_level: Optional[str] = None,
        circuit_status: Optional[str] = None,
        order: Optional[Dict] = None,
        drawdown: Optional[Dict] = None,
        error_loop: Optional[Dict] = None,
    ) -> dict:
        """
        更新交易与风控状态。
        order: 单笔订单 {"timestamp", "symbol", "action", "price", "volume", "status", "strategy"}
        drawdown: {"symbol": float} 单票回撤百分比
        error_loop: {"strategy": count} 错误计数
        """
        data = self._read_json(TRADE_RISK_FILE)
        data["last_updated"] = datetime.now().isoformat()

        if circuit_level is not None:
            data["circuit_breaker"]["level"] = circuit_level
        if circuit_status is not None:
            data["circuit_breaker"]["status"] = circuit_status
        if order is not None:
            order = sanitize(order)
            data["recent_orders"].append(order)
            data["recent_orders"] = data["recent_orders"][-50:]  # 保留最近50条
        if drawdown is not None:
            data["drawdown_monitor"].update(drawdown)
        if error_loop is not None:
            data["error_loop_counter"].update(error_loop)

        data = sanitize(data)
        self._write_json(TRADE_RISK_FILE, data)
        return data

    # ----------------------------------------------------------
    # 决策与进化日志追加
    # ----------------------------------------------------------
    def append_decision(
        self,
        decision_type: str,
        content: str,
        detail: Optional[Dict] = None,
    ):
        """
        追加一条决策/进化日志。
        decision_type: STRATEGY_ADJUST | PLAN_CONFIRM | VERSION_ITERATE | LEARNING_RESULT | RISK_ALERT
        """
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": decision_type,
            "content": content,
        }
        if detail is not None:
            entry["detail"] = sanitize(detail)

        entry = sanitize(entry)
        with open(DECISION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ----------------------------------------------------------
    # P2: 策略进化追踪
    # ----------------------------------------------------------
    def update_strategy_evolution(
        self,
        strategy_name: str = None,
        version: str = None,
        change_type: str = None,
        change_desc: str = None,
        backtest_result: Optional[Dict] = None,
        new_target: Optional[Dict] = None,
    ) -> dict:
        """
        更新策略进化追踪数据。
        change_type: VERSION_ITERATE | PARAM_ADJUST | NEW_TARGET | MODEL_UPGRADE
        new_target: {"symbol": str, "correlation": float, "score": float, "status": "shadow|paper|live"}
        backtest_result: {"sharpe": float, "max_dd": float, "win_rate": float, "period": str}
        """
        data = self._read_json(STRATEGY_EVOLUTION_FILE)
        data["last_updated"] = datetime.now().isoformat()

        # 版本迭代时间线
        if strategy_name and version and change_type:
            timeline = data.setdefault("version_timeline", [])
            entry = {
                "timestamp": datetime.now().isoformat(),
                "strategy": strategy_name,
                "version": version,
                "change_type": change_type,
                "description": change_desc or "",
            }
            if backtest_result:
                entry["backtest"] = backtest_result
            timeline.append(entry)
            data["version_timeline"] = timeline[-100:]  # 保留最近100条

            # 更新当前版本号
            versions = data.setdefault("current_versions", {})
            versions[strategy_name] = version

        # 新标的雷达
        if new_target:
            radar = data.setdefault("target_radar", [])
            # 同symbol更新而非追加
            existing = [i for i, t in enumerate(radar) if t.get("symbol") == new_target["symbol"]]
            if existing:
                radar[existing[0]] = {**radar[existing[0]], **new_target, "updated": datetime.now().isoformat()}
            else:
                new_target["added"] = datetime.now().isoformat()
                radar.append(new_target)
            data["target_radar"] = radar

        data = sanitize(data)
        self._write_json(STRATEGY_EVOLUTION_FILE, data)
        return data

    # ----------------------------------------------------------
    # P2: 决策看板（PLAN确认 + 权限记录）
    # ----------------------------------------------------------
    def update_plan_board(
        self,
        plan_id: str = None,
        action: str = "create",
        content: str = None,
        detail: Optional[Dict] = None,
        status: str = None,
    ) -> dict:
        """
        管理决策看板（PLAN确认 + 权限管控记录）。
        action: create | confirm | reject | expire | execute
        status: PENDING | CONFIRMED | REJECTED | EXPIRED | EXECUTED
        """
        data = self._read_json(PLAN_BOARD_FILE)
        data["last_updated"] = datetime.now().isoformat()

        plans = data.setdefault("plans", [])

        if plan_id and action == "create":
            plan = {
                "plan_id": plan_id,
                "created": datetime.now().isoformat(),
                "content": content or "",
                "detail": sanitize(detail) if detail else {},
                "status": "PENDING",
                "expires_at": None,  # 15分钟后由调用方设置
                "confirmed_at": None,
                "executed_at": None,
            }
            plans.append(plan)
        elif plan_id:
            # 查找并更新现有PLAN
            for p in plans:
                if p.get("plan_id") == plan_id:
                    if action == "confirm":
                        p["status"] = "CONFIRMED"
                        p["confirmed_at"] = datetime.now().isoformat()
                    elif action == "reject":
                        p["status"] = "REJECTED"
                    elif action == "expire":
                        p["status"] = "EXPIRED"
                    elif action == "execute":
                        p["status"] = "EXECUTED"
                        p["executed_at"] = datetime.now().isoformat()
                    if status:
                        p["status"] = status
                    break

        # 权限管控记录
        if detail and detail.get("permission_change"):
            perm_log = data.setdefault("permission_log", [])
            perm_log.append({
                "timestamp": datetime.now().isoformat(),
                "change": detail["permission_change"],
                "actor": detail.get("actor", "system"),
            })
            data["permission_log"] = perm_log[-50:]

        # 只保留最近50条PLAN
        data["plans"] = plans[-50:]

        data = sanitize(data)
        self._write_json(PLAN_BOARD_FILE, data)
        return data

    # ----------------------------------------------------------
    # P2: 任务雷达（在执行任务 + AI学习成果）
    # ----------------------------------------------------------
    def update_task_radar(
        self,
        task_id: str = None,
        action: str = "update",
        title: str = None,
        group: str = None,
        progress: Optional[float] = None,
        status: str = None,
        result_summary: str = None,
    ) -> dict:
        """
        管理任务雷达看板数据。
        action: add | update | complete | remove
        group: risk_control | trade_execution | strategy_research | ai_learning
        status: PLANNED | RUNNING | COMPLETED | FAILED | CANCELLED
        """
        data = self._read_json(TASK_RADAR_FILE)
        data["last_updated"] = datetime.now().isoformat()

        tasks = data.setdefault("tasks", [])

        if task_id and action == "add":
            tasks.append({
                "task_id": task_id,
                "title": title or "",
                "group": group or "strategy_research",
                "status": status or "PLANNED",
                "progress": progress or 0.0,
                "created": datetime.now().isoformat(),
                "updated": datetime.now().isoformat(),
                "result_summary": result_summary or "",
            })
        elif task_id:
            for t in tasks:
                if t.get("task_id") == task_id:
                    if title:
                        t["title"] = title
                    if group:
                        t["group"] = group
                    if progress is not None:
                        t["progress"] = progress
                    if status:
                        t["status"] = status
                    if result_summary:
                        t["result_summary"] = result_summary
                    t["updated"] = datetime.now().isoformat()
                    if status == "COMPLETED":
                        t["completed_at"] = datetime.now().isoformat()
                    break

        # 清理：COMPLETED/FAILED/CANCELLED 超过24小时的移除
        now = datetime.now()
        active = []
        for t in tasks:
            if t.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
                updated = t.get("updated", "")
                try:
                    dt = datetime.fromisoformat(updated)
                    if (now - dt).total_seconds() > 86400:
                        continue
                except (ValueError, TypeError):
                    pass
            active.append(t)

        data["tasks"] = active[-30:]  # 最多保留30条
        data = sanitize(data)
        self._write_json(TASK_RADAR_FILE, data)
        return data

    # ----------------------------------------------------------
    # P2: 快照读取扩展
    # ----------------------------------------------------------
    def get_strategy_evolution(self) -> dict:
        return self._read_json(STRATEGY_EVOLUTION_FILE)

    def get_plan_board(self) -> dict:
        return self._read_json(PLAN_BOARD_FILE)

    def get_task_radar(self) -> dict:
        return self._read_json(TASK_RADAR_FILE)

    # ----------------------------------------------------------
    # 快照读取（供面板或其他工具调用）
    # ----------------------------------------------------------
    def get_global_status(self) -> dict:
        return self._read_json(GLOBAL_STATUS_FILE)

    def get_trade_risk(self) -> dict:
        return self._read_json(TRADE_RISK_FILE)

    def get_recent_decisions(self, limit: int = 20) -> List[dict]:
        if not DECISION_FILE.exists():
            return []
        lines = DECISION_FILE.read_text(encoding="utf-8").strip().split("\n")
        entries = []
        for line in lines[-limit:]:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries

    # ----------------------------------------------------------
    # 内部工具
    # ----------------------------------------------------------
    def _read_json(self, path: Path) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_json(self, path: Path, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 命令行快速测试
# ============================================================
if __name__ == "__main__":
    dw = DashboardWriter()

    print("1. 初始化全局状态...")
    gs = dw.update_global_status(
        total_capital=100000,
        daily_pnl=250.50,
        token_used=8000000,
        active_market="us_stock",
    )
    print(f"   Token: {gs['token_usage']['used']}/{gs['token_usage']['budget']} ({gs['token_usage']['percent']}%)")

    print("2. 添加模拟订单...")
    tr = dw.update_trade_risk(
        order={
            "timestamp": datetime.now().isoformat(),
            "symbol": "BTDR",
            "action": "SELL",
            "price": 25.50,
            "volume": 100,
            "status": "FILLED",
            "strategy": "BTDR_PrevClose_V2"
        }
    )
    print(f"   近期订单数: {len(tr['recent_orders'])}")

    print("3. 追加决策日志...")
    dw.append_decision(
        decision_type="STRATEGY_ADJUST",
        content="BTDR PrevClose V2 止损点从5%调整至4.5%",
        detail={"strategy": "BTDR_PrevClose_V2", "old_stop": "5%", "new_stop": "4.5%"}
    )

    print("4. 读取快照确认...")
    print(f"   global_status.json: {GLOBAL_STATUS_FILE.exists()}")
    print(f"   trade_risk.json: {TRADE_RISK_FILE.exists()}")
    print(f"   decision_evolution.jsonl: {DECISION_FILE.exists()}")
    print("\nP0 状态快照模块就绪 ✅")
