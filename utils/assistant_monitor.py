"""
AI助手保活监控脚本
监控三个AI助手(千问、豆包、元宝)的登录状态，异常时通过企业微信+邮件通知

Author: 量化交易总控智能体
Date: 2026-04-22
"""

import subprocess
import json
import time
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# 添加utils路径
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace')

try:
    from utils.wechat_push import push_report
except ImportError:
    push_report = None
    print("警告: 无法导入wechat_push，通知功能将不可用")


class AssistantMonitor:
    """AI助手状态监控器"""
    
    # 助手配置
    # 登录检测策略：只要标签页存在且URL包含chat/chat/则为已登录
    # 登出特征通常为：引导页/登录页/注册页（无/chat/路径或含login/signup）
    ASSISTANTS = {
        "qianwen": {
            "name": "千问",
            "url_keyword": "qianwen.com",
            "login_url_pattern": "/chat/",   # 有/chat/路径即已登录
            "logged_out_indicators": ["登录", "注册", "aliyun.com/login", "qianwen.com/sign"]  # 明确登出标识
        },
        "doubao": {
            "name": "豆包", 
            "url_keyword": "doubao.com",
            "login_url_pattern": "/chat/",
            "logged_out_indicators": ["login", "signup", "登录", "注册"]
        },
        "yuanbao": {
            "name": "元宝",
            "url_keyword": "yuanbao.tencent.com", 
            "login_url_pattern": "/chat/",
            "logged_out_indicators": ["login", "signup", "登录", "注册"]
        }
    }
    
    def __init__(self, skill_dir: Optional[str] = None):
        self.skill_dir = skill_dir or '/home/ubuntu/.openclaw/workspace'
        self.status_file = Path('/home/ubuntu/.openclaw/workspace/data/dashboard/assistant_status.json')
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.last_status = self._load_last_status()
        
    def _load_last_status(self) -> Dict:
        """加载上次状态"""
        if self.status_file.exists():
            try:
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_status(self, status: Dict):
        """保存状态"""
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump(status, f, ensure_ascii=False, indent=2)
    
    def _run_xb_command(self, command: str, timeout: int = 15) -> Dict[str, Any]:
        """执行xbrowser命令"""
        cmd = [
            "node",
            f"{self.skill_dir}\\scripts\\xb.cjs",
            "run",
            "--browser", "edge",
            command
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8'
            )
            
            if result.returncode != 0:
                return {"success": False, "error": result.stderr}
            
            try:
                output = json.loads(result.stdout)
                return output.get("data", {}).get("result", {"success": True})
            except:
                return {"success": True, "raw_output": result.stdout}
                
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def check_tabs(self) -> Dict[str, Any]:
        """检查所有标签页状态"""
        result = self._run_xb_command("tab", timeout=15)
        if not result.get("success"):
            return {"error": result.get("error", "unknown"), "tabs": []}
        
        return result.get("data", {})
    
    def check_assistant_status(self, tab: Dict) -> Dict[str, bool]:
        """检查单个助手状态 - 基于URL路径判断登录状态"""
        url = tab.get("url", "")
        title = tab.get("title", "")
        
        status = {
            "tab_exists": True,
            "url_match": False,
            "likely_logged_in": False,  # 默认登出，直到确认
            "assistant": None
        }
        
        # 识别助手类型
        for key, config in self.ASSISTANTS.items():
            if config["url_keyword"] in url:
                status["assistant"] = key
                status["url_match"] = True
                
                # 登出指示器检查（优先）：若命中任何登出标识，则确认登出
                for indicator in config.get("logged_out_indicators", []):
                    if indicator.lower() in url.lower() or indicator.lower() in title.lower():
                        status["likely_logged_in"] = False
                        break
                else:
                    # 无登出标识时，检查URL是否符合登录路径
                    login_pattern = config.get("login_url_pattern", "/chat/")
                    status["likely_logged_in"] = login_pattern in url
                break
        
        return status
    
    def monitor(self) -> Dict[str, Any]:
        """执行监控检查"""
        timestamp = datetime.now().isoformat()
        report = {
            "timestamp": timestamp,
            "overall_status": "unknown",
            "assistants": {},
            "alerts": []
        }
        
        # 获取标签页
        tabs_data = self.check_tabs()
        tabs = tabs_data.get("tabs", [])
        
        if "error" in tabs_data:
            report["overall_status"] = "error"
            report["error"] = tabs_data["error"]
            self._send_alert(f"AI助手监控异常: {tabs_data['error']}", "critical")
            return report
        
        # 检查每个助手
        found_assistants = set()
        for tab in tabs:
            status = self.check_assistant_status(tab)
            assistant = status.get("assistant")
            
            if assistant:
                found_assistants.add(assistant)
                report["assistants"][assistant] = {
                    "name": self.ASSISTANTS[assistant]["name"],
                    "tab_index": tab.get("index"),
                    "url": tab.get("url"),
                    "title": tab.get("title"),
                    "logged_in": status["likely_logged_in"],
                    "status": "ok" if status["likely_logged_in"] else "logged_out"
                }
        
        # 检查缺失的助手
        for key, config in self.ASSISTANTS.items():
            if key not in found_assistants:
                report["assistants"][key] = {
                    "name": config["name"],
                    "status": "missing",
                    "logged_in": False
                }
                report["alerts"].append(f"{config['name']} 标签页缺失")
        
        # 检查登录状态变化
        for key, info in report["assistants"].items():
            if info.get("status") == "logged_out":
                # 检查是否是新发生的登出
                last = self.last_status.get("assistants", {}).get(key, {})
                if last.get("logged_in") == True:
                    report["alerts"].append(f"{info['name']} 已登出！")
        
        # 确定整体状态
        if report["alerts"]:
            report["overall_status"] = "alert"
        elif all(a.get("logged_in") for a in report["assistants"].values()):
            report["overall_status"] = "healthy"
        else:
            report["overall_status"] = "warning"
        
        # 保存状态
        self._save_status(report)
        self.last_status = report
        
        # 发送告警
        if report["alerts"]:
            self._send_alerts(report["alerts"])
        
        return report
    
    def _send_alert(self, message: str, level: str = "warning"):
        """发送单个告警"""
        print(f"[{level.upper()}] {message}")
        
        if push_report:
            try:
                push_report(
                    title=f"AI助手监控告警",
                    content=message,
                    level=level
                )
            except Exception as e:
                print(f"发送通知失败: {e}")
    
    def _send_alerts(self, alerts: list):
        """批量发送告警"""
        if not alerts:
            return
        
        message = "检测到以下问题:\n" + "\n".join(f"- {a}" for a in alerts)
        self._send_alert(message, "critical" if any("登出" in a for a in alerts) else "warning")
    
    def print_report(self, report: Dict):
        """打印监控报告"""
        print("\n" + "="*50)
        print(f"AI Assistant Monitor - {report['timestamp']}")
        print(f"Status: {report['overall_status'].upper()}")
        print("="*50)
        
        for key, info in report["assistants"].items():
            status_icon = "[OK]" if info.get("logged_in") else "[FAIL]"
            print(f"{status_icon} {info['name']}: {info.get('status', 'unknown')}")
            if "title" in info:
                print(f"   Title: {info['title'][:40]}...")
        
        if report["alerts"]:
            print("\n[ALERT] Alerts:")
            for alert in report["alerts"]:
                print(f"   - {alert}")
        
        print("="*50)
        sys.stdout.flush()


def main():
    """主函数"""
    monitor = AssistantMonitor()
    report = monitor.monitor()
    monitor.print_report(report)
    
    # 返回退出码供cron使用
    if report["overall_status"] == "healthy":
        return 0
    elif report["overall_status"] == "warning":
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
