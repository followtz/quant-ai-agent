#!/usr/bin/env python3
"""
QQ 邮箱发送工具 (Linux 适配版)
替代旧 Windows email_gateway.cmd
"""
import smtplib
import json
import sys
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "config" / "notify_config.json"

def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

def send_email(subject: str, content: str, to_email: str = None, alert_level: str = "INFO"):
    """发送 QQ 邮件"""
    config = load_config()
    to = to_email or config["to_email"]
    
    msg = MIMEMultipart('alternative')
    msg['From'] = config["email_account"]
    msg['To'] = to
    msg['Subject'] = f"[{alert_level}] {subject}"
    
    html = f"""<div style="font-family: 'Microsoft YaHei', Arial, sans-serif; padding: 20px;
                background: #f5f5f5; border-radius: 8px;">
        <div style="background: white; padding: 20px; border-radius: 8px;
                    border-left: 4px solid {'#e74c3c' if alert_level=='CRITICAL' else '#f39c12' if alert_level=='WARNING' else '#2ecc71'};">
            <h3 style="margin-top: 0; color: #333;">{'🔴' if alert_level=='CRITICAL' else '🟠' if alert_level=='WARNING' else '🟢'} 量化交易智能体通知</h3>
            <pre style="white-space: pre-wrap; font-size: 14px; line-height: 1.6;">{content}</pre>
            <p style="color: #999; font-size: 12px; margin-top: 20px;">{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </div>
    </div>"""
    
    msg.attach(MIMEText(content, 'plain', 'utf-8'))
    msg.attach(MIMEText(html, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL(config["email_smtp_server"], config["email_smtp_port"]) as server:
            server.login(config["email_account"], config["email_auth_code"])
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Email send failed: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: email_sender.py <subject> [content] [alert_level]")
        sys.exit(1)
    subject = sys.argv[1]
    content = sys.argv[2] if len(sys.argv) > 2 else "(无内容)"
    level = sys.argv[3].upper() if len(sys.argv) > 3 else "INFO"
    success = send_email(subject, content, alert_level=level)
    sys.exit(0 if success else 1)
