#!/usr/bin/env python3
"""
紧急告警工具 - 红色❗推送
用于突发事件（OpenD断线/策略异常/风控触发）
"""
import urllib.request, json, smtplib
from email.mime.text import MIMEText
from datetime import datetime
from pathlib import Path

CONFIG = Path(__file__).parent.parent / "config" / "notify_config.json"

def alert(title: str, message: str):
    """发送❗紧急告警（企业微信+QQ邮箱双通道）"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    full = f"❗ {title}\n\n{message}\n\n-- {ts}"
    
    # 企业微信
    try:
        cfg = json.loads(open(CONFIG).read())
        url = cfg.get("wecom_mcp_url", "")
        payload = {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"send_message",
                   "arguments":{"chat_type":1,"chatid":"TongZhuang","msgtype":"text",
                   "text":{"content":f"🚨 {title}\n\n{message}\n\n-- {ts}"}}}}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
        urllib.request.urlopen(req, timeout=10)
        print("[WeCom] ✅ 已发送")
    except Exception as e:
        print(f"[WeCom] ❌ {e}")
    
    # QQ邮箱
    try:
        msg = MIMEText(f"🚨 {title}\n\n{message}", "plain", "utf-8")
        msg["Subject"] = f"🚨 {title}"
        msg["From"] = cfg["email_account"]
        msg["To"] = cfg["to_email"]
        with smtplib.SMTP_SSL(cfg["email_smtp_server"], cfg["email_smtp_port"]) as s:
            s.login(cfg["email_account"], cfg["email_auth_code"])
            s.send_message(msg)
        print("[Email] ✅ 已发送")
    except Exception as e:
        print(f"[Email] ❌ {e}")

if __name__ == "__main__":
    import sys
    title = sys.argv[1] if len(sys.argv) > 1 else "紧急告警"
    msg = sys.argv[2] if len(sys.argv) > 2 else "详情见服务器日志"
    alert(title, msg)
