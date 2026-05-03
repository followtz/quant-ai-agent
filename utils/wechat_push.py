# -*- coding: utf-8 -*-
"""
企业微信通知 + 邮箱抄送工具 (wechat_push.py)
龙虾总控智能体 · 标准化通知通道
版本: v2.4 | 2026-04-21

v2.4 变更：企业微信通过 StreamableHttp MCP 新端点发送（已授权）
  - 端点: https://qyapi.weixin.qq.com/mcp/bot/msg?uaKey=...
  - 邮箱: email_gateway.cmd

使用说明：
  import wechat_push as wp
  wp.push_report(title, content, ...)  # 企业微信+邮箱同步
  wp.push_daily_trade_report(...)      # 每日交易报告
"""

import os, json, logging, subprocess, tempfile, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
from typing import Optional

WORKSPACE = Path(__file__).parent.parent
CONFIG_FILE = WORKSPACE / "config" / "notify_config.json"
EMAIL_SCRIPT = r"C:\Program Files\QClaw\resources\openclaw\config\skills\public-skill\scripts\windows\email_gateway.cmd"
DEFAULT_TO_EMAIL = "126959876@qq.com"
DEFAULT_WECOM_USER = "TongZhuang"

# ============================================================
# 企业微信 StreamableHttp MCP 端点（2026-04-21 新授权）
# ============================================================
WECOM_MCP_URL = (
    "https://qyapi.weixin.qq.com/mcp/bot/msg"
    "?uaKey=2LnvNY6XTafiryEvE4RyP7zo65j6tfqH9NdzD7SJNXpUhgXnZzDRBeNU7rvVghrEkj2H3dSEqPQS7KNbhAQfR86AKhPmr"
)

_logger: Optional[logging.Logger] = None

def get_logger() -> logging.Logger:
    global _logger
    if _logger is None:
        _logger = logging.getLogger("wechat_push")
        _logger.setLevel(logging.INFO)
        if not _logger.handlers:
            sh = logging.StreamHandler()
            sh.setFormatter(logging.Formatter("%(asctime)s [wecom] %(message)s", datefmt="%H:%M:%S"))
            _logger.addHandler(sh)
    return _logger


# ============================================================
# 企业微信通知（StreamableHttp MCP）
# ============================================================

def send_wecom_notification(
    message: str,
    alert_level: str = "INFO",
    userid: str = None,
    mention: bool = False,
) -> bool:
    """
    通过 StreamableHttp MCP 新端点发送企业微信消息
    端点：https://qyapi.weixin.qq.com/mcp/bot/msg?uaKey=...
    """
    target = userid or DEFAULT_WECOM_USER
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    emoji = {
        "CRITICAL": "[CRITICAL]",
        "WARNING": "[WARNING]",
        "INFO": "[INFO]"
    }.get(alert_level.upper(), "[INFO]")

    full_msg = f"{emoji} 龙虾智能体\n\n{message}\n\n-- {ts}"
    if mention or alert_level.upper() == "CRITICAL":
        full_msg += "\n\n@TongZhuang 请注意查收"

    payload = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "send_message",
            "arguments": {
                "chat_type": 1,
                "chatid": target,
                "msgtype": "text",
                "text": {"content": full_msg}
            }
        }
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WECOM_MCP_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode("utf-8")
        resp = json.loads(raw)

        # 解析 MCP 响应格式
        if "result" in resp:
            content = resp["result"].get("content", [])
            if content and isinstance(content, list):
                inner_text = content[0].get("text", "{}")
                inner = json.loads(inner_text)
                if inner.get("errcode") == 0:
                    get_logger().info(f"企业微信发送成功: errcode=0")
                    return True
                else:
                    get_logger().warning(f"企业微信 API 错误: {inner}")
                    return False
        get_logger().warning(f"企业微信响应异常: {raw[:200]}")
        return False
    except Exception as e:
        get_logger().error(f"企业微信发送异常: {e}")
        return False


# ============================================================
# 邮箱抄送（public-skill email_gateway.cmd）
# ============================================================

def send_email_copy(
    subject: str,
    body: str,
    to_email: str = DEFAULT_TO_EMAIL
) -> bool:
    """发送邮件抄送"""
    email_body = (
        f"发件时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"发件人：龙虾总控智能体\n"
        f"{'='*40}\n\n{body}\n\n{'='*40}\n"
        f"本邮件由龙虾总控智能体自动发送。"
    )

    body_file = os.path.join(tempfile.gettempdir(), "_wecom_email_body.txt")
    try:
        with open(body_file, "w", encoding="utf-8") as f:
            f.write(email_body)

        ps_cmd = (
            f"& '{EMAIL_SCRIPT}' send "
            f"--email '{to_email}' "
            f"--subject \"{subject}\" "
            f"--body-file '{body_file}'"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace"
        )
        out = r.stdout.strip()
        try:
            resp = json.loads(out)
            ok = resp.get("success", False)
        except json.JSONDecodeError:
            ok = r.returncode == 0 or "success" in out.lower()

        if ok:
            get_logger().info(f"邮件发送成功: {to_email} | {subject[:50]}")
            return True
        else:
            get_logger().error(f"邮件发送失败: {out[:200]}")
            _queue_email(subject, email_body, to_email)
            return False
    except Exception as e:
        get_logger().error(f"邮件发送异常: {e}")
        _queue_email(subject, email_body, to_email)
        return False
    finally:
        try:
            os.remove(body_file)
        except Exception:
            pass


def _queue_email(subject: str, body: str, to_email: str):
    """邮件失败时写入本地队列待补发"""
    qf = WORKSPACE / "data" / "logs" / "email_queue.jsonl"
    qf.parent.mkdir(parents=True, exist_ok=True)
    with open(qf, "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "subject": subject, "body": body, "to": to_email, "status": "PENDING"
        }, ensure_ascii=False) + "\n")


# ============================================================
# 标准推送入口（企业微信 + 邮箱同步）
# ============================================================

def push_report(
    title: str,
    content: str,
    report_type: str = "分析报告",
    alert_level: str = "INFO",
    userid: str = None,
    mention: bool = False
):
    """标准报告推送：企业微信 + 邮箱同步"""
    prefix = {"CRITICAL": "[CRITICAL] ", "WARNING": "[WARNING] ", "INFO": ""}.get(alert_level.upper(), "")
    full_msg = f"**{title}**\n\n{content}"
    full_email = f"{title}\n{'='*40}\n\n{content}"

    wecom_ok = send_wecom_notification(full_msg, alert_level=alert_level, userid=userid, mention=mention)
    email_ok = send_email_copy(
        subject=f"{prefix}[龙虾{report_type}] {title}",
        body=full_email
    )

    return wecom_ok, email_ok


def push_daily_trade_report(
    date: str,
    pnl: float,
    positions: dict,
    signals: dict,
    alerts: list = None
):
    """每日交易报告"""
    pnl_str = f"+{pnl:.2f}" if pnl >= 0 else f"{pnl:.2f}"
    lines = [
        f"**每日交易报告 | {date} | PnL: {pnl_str}**", "",
        "**持仓**",
    ]
    for ticker, info in positions.items():
        pnl_h = (info.get("现价", 0) - info.get("成本", 0)) * info.get("数量", 0)
        p_str = f"+{pnl_h:.2f}" if pnl_h >= 0 else f"{pnl_h:.2f}"
        lines.append(f"- {ticker}: {info.get('数量', 0)}@{info.get('现价', 0):.2f} (浮: {p_str})")
    lines += ["", "**策略信号**"]
    for s, sig in signals.items():
        lines.append(f"- {s}: {sig}")
    if alerts:
        lines += ["", "**告警**"] + [f"- {a}" for a in alerts]

    push_report(
        title=f"每日交易报告 {date}",
        content="\n".join(lines),
        report_type="交易报告",
        alert_level="WARNING" if pnl < 0 else "INFO"
    )


# ============================================================
# 初始化配置
# ============================================================

def init_config():
    cfg = {
        "version": "2.4",
        "wecom_userid": DEFAULT_WECOM_USER,
        "to_email": DEFAULT_TO_EMAIL,
        "wecom_mcp_url": WECOM_MCP_URL,
        "note": "企业微信: StreamableHttp MCP新端点; 邮箱: email_gateway.cmd"
    }
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    return CONFIG_FILE


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    print("通知工具 v2.4 测试")
    print("=" * 40)
    init_config()

    print("发送企业微信...")
    ok1 = send_wecom_notification(
        "通知工具 v2.4 测试\n✅ 企业微信 StreamableHttp MCP 端点正式启用！",
        alert_level="INFO"
    )
    print(f"企业微信: {'SUCCESS' if ok1 else 'FAILED'}")

    print("发送邮箱...")
    ok2 = send_email_copy(
        subject="[龙虾通知] 邮件通道v2.4测试",
        body="通知工具 v2.4 测试成功。\n时间: " + datetime.now().strftime("%Y-%m-%d %H:%M")
    )
    print(f"邮箱: {'SUCCESS' if ok2 else 'FAILED (queued)'}")

    print("\n双通道同步测试...")
    ok_w, ok_e = push_report(
        title="v2.4 双通道同步测试",
        content="企业微信 + 邮箱双通道同步推送测试。\n如同时收到两条消息，说明双通道完全正常。",
        report_type="系统测试",
        alert_level="INFO"
    )
    print(f"企业微信: {'SUCCESS' if ok_w else 'FAILED'}")
    print(f"邮箱: {'SUCCESS' if ok_e else 'FAILED'}")
    print("\n测试完成。")


# ============================================================
# 可视化指挥舱卡片推送（2026-04-22 P0 新增）
# ============================================================

def push_dashboard_card(
    risk_status: str,
    trade_status: str,
    token_usage: str,
    current_task: str,
    alert_level: str = "normal",
    detail: str = "",
) -> bool:
    """
    推送可视化指挥舱状态卡片到企业微信。

    参数:
        risk_status: 风控状态摘要，如 "🟢 安全 (回撤 0.5%)"
        trade_status: 交易执行状态，如 "美股运行中 (BTDR V2)"
        token_usage: Token使用情况，如 "800万/4000万 (20%)"
        current_task: 当前任务描述
        alert_level: "normal" | "warning" | "critical"
        detail: 补充说明（可选）

    卡片颜色映射:
        normal   → 绿色 (正常运行)
        warning  → 橙色 (接近风控线/Token不足)
        critical → 红色 (熔断触发/严重报错)
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 颜色标记
    color_map = {"normal": "🟢", "warning": "🟠", "critical": "🔴"}
    icon = color_map.get(alert_level, "🟢")

    # 组装文本消息（企业微信 text 消息格式，兼容性最好）
    lines = [
        f"{icon} 龙虾指挥舱 | {ts}",
        f"{'━' * 28}",
        f"🛡️ 风控: {risk_status}",
        f"📈 交易: {trade_status}",
        f"⚡ Token: {token_usage}",
        f"🎯 任务: {current_task}",
    ]
    if detail:
        lines.append(f"📋 详情: {detail}")

    # 面板入口
    lines += [
        f"{'━' * 28}",
        f"🌐 面板: http://localhost:8082 (统一监控)",
    ]

    # critical 级别@用户
    mention = alert_level == "critical"
    full_msg = "\n".join(lines)

    # 转换 alert_level 给 send_wecom_notification
    level_map = {"normal": "INFO", "warning": "WARNING", "critical": "CRITICAL"}
    wecom_level = level_map.get(alert_level, "INFO")

    wecom_ok = send_wecom_notification(full_msg, alert_level=wecom_level, mention=mention)

    # 邮箱同步（warning和critical级别）
    email_ok = True
    if alert_level in ("warning", "critical"):
        email_ok = send_email_copy(
            subject=f"[{icon} 龙虾指挥舱] {alert_level.upper()} | {ts}",
            body=full_msg
        )

    return wecom_ok


# ============================================================
# 快捷方法：从状态快照自动组装并推送
# ============================================================

def push_dashboard_from_snapshot(current_task: str = "") -> bool:
    """
    从 /data/dashboard/*.json 读取最新状态，自动组装卡片推送。
    供 Heartbeat 或 Cron 定时任务调用。
    """
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from dashboard_writer import DashboardWriter

        dw = DashboardWriter()
        gs = dw.get_global_status()
        tr = dw.get_trade_risk()

        # 风控状态
        circuit = tr.get("circuit_breaker", {})
        level = circuit.get("level", "L0")
        level_emoji = {"L0": "🟢 安全", "L1": "🟡 警告", "L2": "🟠 熔断", "L3": "🔴 全局熔断"}
        risk_status = level_emoji.get(level, f"未知({level})")

        # 交易状态
        market = gs.get("active_market", "none")
        market_label = {"us_stock": "美股", "hk_stock": "港股", "none": "休市"}.get(market, market)
        strategies = gs.get("strategies", {})
        active_strats = [k for k, v in strategies.items() if v.get("status") == "normal"]
        trade_status = f"{market_label}运行中 ({', '.join(active_strats)})" if market != "none" else "休市"

        # Token
        tu = gs.get("token_usage", {})
        used_wan = tu.get("used", 0) // 10000
        budget_wan = tu.get("budget", 40000000) // 10000
        pct = tu.get("percent", 0)
        token_usage = f"{used_wan}万/{budget_wan}万 ({pct}%)"

        # 警报级别判定
        alert = "normal"
        if level in ("L2", "L3"):
            alert = "critical"
        elif level == "L1" or pct >= 80:
            alert = "warning"

        return push_dashboard_card(
            risk_status=risk_status,
            trade_status=trade_status,
            token_usage=token_usage,
            current_task=current_task or "系统巡检",
            alert_level=alert
        )
    except Exception as e:
        get_logger().error(f"快照推送失败: {e}")
        return False


# ============================================================
# P2: 策略进化卡片
# ============================================================

def push_evolution_card() -> bool:
    """推送策略进化卡片：版本时间轴 + 新标的雷达"""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from dashboard_writer import DashboardWriter

        dw = DashboardWriter()
        se = dw.get_strategy_evolution()

        lines = [f"🧬 策略进化看板 | {datetime.now().strftime('%Y-%m-%d %H:%M')}", "━" * 28]

        # 当前版本
        versions = se.get("current_versions", {})
        if versions:
            lines.append("📦 当前版本:")
            for strat, ver in versions.items():
                lines.append(f"  · {strat}: {ver}")

        # 最近版本迭代
        timeline = se.get("version_timeline", [])
        if timeline:
            lines.append("")
            lines.append("🔄 近期迭代:")
            for t in timeline[-5:]:
                lines.append(f"  · {t.get('strategy','')}→{t.get('version','')} [{t.get('change_type','')}]")

        # 新标的雷达
        radar = se.get("target_radar", [])
        if radar:
            lines.append("")
            lines.append("📡 新标的雷达:")
            for r in radar[:5]:
                status_emoji = {"shadow": "👻", "paper": "📝", "live": "🔴"}.get(r.get("status", ""), "❓")
                lines.append(f"  · {status_emoji} {r.get('symbol','')} 相关性={r.get('correlation',0):.2f} 评分={r.get('score',0):.1f}")

        lines += ["━" * 28, "🌐 面板: http://localhost:8082"]

        return send_wecom_notification("\n".join(lines), alert_level="INFO")
    except Exception as e:
        get_logger().error(f"策略进化卡片推送失败: {e}")
        return False


# ============================================================
# P2: 任务雷达卡片
# ============================================================

def push_task_radar_card() -> bool:
    """推送任务雷达卡片：在执行任务 + 学习成果"""
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from dashboard_writer import DashboardWriter

        dw = DashboardWriter()
        tr = dw.get_task_radar()

        lines = [f"📡 任务雷达 | {datetime.now().strftime('%Y-%m-%d %H:%M')}", "━" * 28]

        tasks = tr.get("tasks", [])
        if not tasks:
            lines.append("暂无活跃任务")
        else:
            # 按组分类
            group_labels = {
                "risk_control": "🛡️ 风控",
                "trade_execution": "📈 交易",
                "strategy_research": "🧠 策略研究",
                "ai_learning": "📚 AI学习"
            }
            for group_key, group_label in group_labels.items():
                group_tasks = [t for t in tasks if t.get("group") == group_key and t.get("status") in ("PLANNED", "RUNNING")]
                if group_tasks:
                    lines.append(f"{group_label}:")
                    for t in group_tasks:
                        bar = "█" * int(t.get("progress", 0) / 10) + "░" * (10 - int(t.get("progress", 0) / 10))
                        lines.append(f"  · {t.get('title','')} [{bar}] {t.get('progress',0):.0f}%")

            # 最近完成
            completed = [t for t in tasks if t.get("status") == "COMPLETED"]
            if completed:
                lines.append("")
                lines.append("✅ 最近完成:")
                for t in completed[-3:]:
                    lines.append(f"  · {t.get('title','')} — {t.get('result_summary','')[:50]}")

        lines += ["━" * 28, "🌐 面板: http://localhost:8082"]

        return send_wecom_notification("\n".join(lines), alert_level="INFO")
    except Exception as e:
        get_logger().error(f"任务雷达卡片推送失败: {e}")
        return False