# -*- coding: utf-8 -*-
"""
策略健康检查与面板监测脚本
- 检查BTDR和连连数字进程状态
- 检查监控面板可访问性
- 检查日志文件更新时间
- 如发现异常则生成告警文件

使用方法: python health_check.py
"""
import sys, json, time, subprocess
from pathlib import Path
from datetime import datetime

WORK_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司")
LOG_DIR  = WORK_DIR / "06_龙虾自动运行日志"
CHECK_TIME = datetime.now()
LOG_FILE   = LOG_DIR / f"health_check_{CHECK_TIME.strftime('%Y%m%d_%H%M%S')}.log"
ALERT_FILE = LOG_DIR / "ALERT_latest.json"

# emoji 替换
OK  = "[OK] "
ERR = "[FAIL] "
WARN= "[WARN] "

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def save_alert(alert_data):
    alert_data["timestamp"] = CHECK_TIME.isoformat()
    ALERT_FILE.write_text(json.dumps(alert_data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"{WARN}Alert file saved: {ALERT_FILE}")

def run_ps(script, timeout=30):
    """Run PowerShell and return stdout"""
    try:
        r = subprocess.run(["powershell", "-Command", script],
                           capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception as e:
        log(f"{ERR}PS error: {e}")
        return None

def check_processes():
    log("=" * 60)
    log("[PROCESS CHECK]")

    out = run_ps(
        "Get-Process python -ErrorAction SilentlyContinue | "
        "Select-Object Id, CPU, WorkingSet | ConvertTo-Json -Compress"
    )
    procs = []
    if out:
        try:
            d = json.loads(out)
            procs = [d] if isinstance(d, dict) else d
        except:
            procs = []

    ports_out = run_ps(
        "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object {$_.LocalPort -in @(8080,8081,11111)} | "
        "Select-Object LocalPort,OwningProcess | ConvertTo-Json -Compress"
    )
    ports = {}
    if ports_out:
        try:
            pd = json.loads(ports_out)
            if isinstance(pd, dict):
                ports[pd["LocalPort"]] = pd["OwningProcess"]
            else:
                for p in pd:
                    ports[p["LocalPort"]] = p["OwningProcess"]
        except:
            pass

    btdr_pid = ll_pid = None
    for proc in procs:
        pid = proc.get("Id")
        cpu = round(proc.get("CPU", 0), 1)
        mem = round(proc.get("WorkingSet", 0) / 1024 / 1024, 1)
        if pid == ports.get(8080):
            btdr_pid = pid
            log(f"  {OK}BTDR Panel (8080): PID={pid} CPU={cpu}s MEM={mem}MB")
        if pid == ports.get(8081):
            ll_pid = pid
            log(f"  {OK}Lianlian Panel (8081): PID={pid} CPU={cpu}s MEM={mem}MB")

    if not btdr_pid and ports.get(8080):
        log(f"  {OK}BTDR Panel (8080): PID={ports[8080]}")
    if not ll_pid and ports.get(8081):
        log(f"  {OK}Lianlian Panel (8081): PID={ports[8081]}")

    log(f"  {'OK' if ports.get(8080) else 'FAIL'} Panel8080 port: {'PID ' + str(ports.get(8080)) if ports.get(8080) else 'NOT LISTENING'}")
    log(f"  {'OK' if ports.get(8081) else 'FAIL'} Panel8081 port: {'PID ' + str(ports.get(8081)) if ports.get(8081) else 'NOT LISTENING'}")
    log(f"  {'OK' if ports.get(11111) else 'FAIL'} FutuOpenD:    {'PID ' + str(ports.get(11111)) if ports.get(11111) else 'NOT LISTENING'}")

    return {
        "panel_8080": ports.get(8080),
        "panel_8081": ports.get(8081),
        "opend": ports.get(11111),
        "all_ok": ports.get(8080) and ports.get(8081) and ports.get(11111)
    }

def check_panels():
    log("=" * 60)
    log("[PANEL HEALTH CHECK]")
    results = {}
    for port in [8080, 8081]:
        out = run_ps(
            f"(try {{(Invoke-WebRequest -Uri 'http://localhost:{port}/api/status' "
            f"-TimeoutSec 5 -UseBasicParsing).StatusCode}} catch {{'ERR'}})."
            f"Replace('ERR','FAIL')",
            timeout=10
        )
        ok = out and "200" in str(out)
        results[port] = ok
        log(f"  {'OK' if ok else 'FAIL'} localhost:{port} -> {out}")
    return results

def check_log_freshness():
    log("=" * 60)
    log("[LOG FRESHNESS CHECK]")
    now = datetime.now()
    log_dirs = [Path(r"C:\Trading\logs"), LOG_DIR]
    patterns = {"btdr": "prev_close_v2*", "ll": "v4_live*"}
    results = {}
    for name, pat in patterns.items():
        found = False
        for ld in log_dirs:
            files = list(ld.glob(pat))
            if files:
                latest = max(files, key=lambda f: f.stat().st_mtime)
                age_min = (now - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds() / 60
                status = "OK" if age_min < 60 else "STALE"
                log(f"  [{status}] {name}: {latest.name} ({age_min:.0f}min ago)")
                results[name] = {"ok": age_min < 60, "file": str(latest), "age_min": round(age_min, 1)}
                found = True
                break
        if not found:
            log(f"  [STALE] {name}: No log file found")
            results[name] = {"ok": False, "file": None, "age_min": None}
    return results

def check_state_files():
    log("=" * 60)
    log("[STATE FILE CHECK]")
    state_files = {
        "btdr_v2": Path(r"C:\Trading\data\prev_close_v2_state.json"),
        "ll_v4": WORK_DIR / "01_策略库/连连数字/实盘策略核心文件/连连数字V4策略全套文件/v4_live_state.json",
    }
    now = datetime.now()
    results = {}
    for name, path in state_files.items():
        if path.exists():
            age_min = (now - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 60
            status = "OK" if age_min < 120 else "STALE"
            log(f"  [{status}] {name}: {path.name} ({age_min:.0f}min ago)")
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                shares = data.get("shares", data.get("position", "?"))
                date_s = data.get("date", "?")
                log(f"        shares={shares}, date={date_s}")
            except:
                pass
            results[name] = {"ok": True, "file": str(path), "age_min": round(age_min, 1)}
        else:
            log(f"  [STALE] {name}: {path.name} NOT FOUND")
            results[name] = {"ok": False, "file": str(path), "age_min": None}
    return results

def main():
    log("=" * 60)
    log("  Quant-AI Company - Strategy Health Check")
    log(f"  Time: {CHECK_TIME.strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    issues = []
    alert_data = {"level": "OK", "issues": [], "details": {}}

    proc = check_processes()
    alert_data["details"]["processes"] = proc
    if not proc.get("all_ok"):
        issues.append("Some processes not running")

    panels = check_panels()
    alert_data["details"]["panels"] = panels
    for port, ok in panels.items():
        if not ok:
            issues.append(f"Panel {port} not responding")

    logs = check_log_freshness()
    alert_data["details"]["logs"] = logs

    states = check_state_files()
    alert_data["details"]["state_files"] = states

    log("=" * 60)
    if not issues:
        log(f"{OK}All checks passed")
    else:
        alert_data["level"] = "WARNING"
        alert_data["issues"] = issues
        log(f"{WARN}Found {len(issues)} issue(s):")
        for issue in issues:
            log(f"  - {issue}")
        save_alert(alert_data)

    log(f"Log: {LOG_FILE}")
    log(f"Alert: {ALERT_FILE}")
    return 0 if not issues else 1

if __name__ == "__main__":
    sys.exit(main())
