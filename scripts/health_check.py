#!/usr/bin/env python3
"""
系统健康检查 v1.0
纯代码执行，零LLM消耗
每5分钟运行一次，结果写入 status.json
仅异常时记录，Heartbeat LLM 只读这个文件
"""
import json, os, subprocess, time
from datetime import datetime
from pathlib import Path

STATUS_FILE = Path(__file__).parent.parent / "data" / "dashboard" / "health_status.json"
STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)

def check_open_d():
    """检查Futu OpenD进程"""
    result = subprocess.run(
        ['ps', 'aux'], capture_output=True, text=True, timeout=5
    )
    for line in result.stdout.split('\n'):
        if 'Futu_OpenD' in line and 'grep' not in line:
            parts = line.split()
            return {"running": True, "pid": parts[1], "cpu": parts[2], "mem": parts[3]}
    return {"running": False}

def check_gateway():
    """检查OpenClaw gateway"""
    result = subprocess.run(
        ['systemctl', '--user', 'is-active', 'openclaw-gateway.service'],
        capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip() == 'active'

def check_disk():
    """检查磁盘使用率"""
    result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True, timeout=5)
    line = result.stdout.strip().split('\n')[-1]
    parts = line.split()
    used_pct = int(parts[4].replace('%', ''))
    return {"used_pct": used_pct, "available": parts[3], "ok": used_pct < 85}

def check_memory():
    """检查内存使用率"""
    result = subprocess.run(['free', '-m'], capture_output=True, text=True, timeout=5)
    lines = result.stdout.strip().split('\n')
    parts = lines[1].split()
    total = int(parts[1])
    available = int(parts[6])
    used_pct = round((total - available) / total * 100, 1)
    return {"used_pct": used_pct, "available_mb": available, "ok": used_pct < 80}

def check_firewall():
    """检查防火墙状态"""
    result = subprocess.run(['sudo', 'ufw', 'status'], capture_output=True, text=True, timeout=5)
    return "active" in result.stdout

def run_all():
    """执行全部检查"""
    checks = {
        "timestamp": datetime.now().isoformat(),
        "open_d": check_open_d(),
        "gateway_active": check_gateway(),
        "disk": check_disk(),
        "memory": check_memory(),
        "firewall": check_firewall(),
    }
    
    # 判断是否有异常（只保存异常，正常不写）
    issues = []
    if not checks["open_d"]["running"]:
        issues.append("OpenD 进程未运行!")
    if not checks["gateway_active"]:
        issues.append("Gateway 服务未激活!")
    if not checks["disk"]["ok"]:
        issues.append(f"磁盘使用率{checks['disk']['used_pct']}%!")
    if not checks["memory"]["ok"]:
        issues.append(f"内存使用率{checks['memory']['used_pct']}%!")
    
    checks["issues"] = issues
    checks["healthy"] = len(issues) == 0
    
    # 始终写入（供Heartbeat LLM读取）
    with open(STATUS_FILE, 'w') as f:
        json.dump(checks, f, indent=2)
    
    return checks

if __name__ == "__main__":
    result = run_all()
    if result["healthy"]:
        print("✅ 系统正常")
    else:
        print(f"⚠️ 发现 {len(result['issues'])} 个问题:")
        for i in result["issues"]:
            print(f"   - {i}")