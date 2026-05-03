"""
AI Assistant Bridge - 网页版AI助手桥接模块 V2
用于通过CDP控制Edge浏览器与千问、豆包、元宝三个AI助手交互

Author: 量化交易总控智能体
Date: 2026-04-22
Version: 2.0

更新记录:
- V2.0: 基于实际DOM测试优化元素选择器
"""

import subprocess
import json
import time
import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from enum import Enum


class AIAssistant(Enum):
    """支持的AI助手类型"""
    QIANWEN = "qianwen"      # 千问 - 阿里
    DOUBAO = "doubao"        # 豆包 - 字节
    YUANBAO = "yuanbao"      # 元宝 - 腾讯


@dataclass
class AssistantConfig:
    """助手配置"""
    name: str
    url: str
    input_ref: str           # 输入框元素引用 (通过snapshot -i获取)
    send_ref: str            # 发送按钮元素引用
    copy_ref: Optional[str]  # 复制按钮元素引用（千问/豆包在e164）
    response_wait_time: int  # 等待回复时间(秒)
    

# 助手配置映射 - 基于实际DOM测试（2026-04-23验证）
# 重要：永远使用xb tab N切换到对应标签，不要用open重新打开（会创建未登录标签页）
# DOM元素引用来自2026-04-23实测验证
ASSISTANT_CONFIGS = {
    AIAssistant.QIANWEN: AssistantConfig(
        name="千问",
        url="https://www.qianwen.com",
        input_ref="e166",     # textbox "向千问提问"
        send_ref="e167",      # button "发送消息"（fill后从disabled变为enabled，需重新snapshot）
        copy_ref="e164",      # button "复制复制"（回复内容左下方）
        response_wait_time=20
    ),
    AIAssistant.DOUBAO: AssistantConfig(
        name="豆包",
        url="https://www.doubao.com",
        input_ref="e538",     # textbox "发消息..."
        send_ref="e539",      # button（fill后需重新snapshot获取enabled状态）
        copy_ref="e164",      # button "复制复制"（回复内容左下方）
        response_wait_time=20
    ),
    AIAssistant.YUANBAO: AssistantConfig(
        name="元宝",
        url="https://yuanbao.tencent.com",
        input_ref="e40",      # contenteditable div（可编辑区域，fill后按Enter发送）
        send_ref="ENTER",    # 元宝无发送按钮，需用press Enter
        copy_ref=None,       # 待验证
        response_wait_time=20
    )
}


class AIAssistantBridge:
    """
    AI助手桥接类
    
    通过xbrowser CDP接口控制Edge浏览器与三个AI助手交互
    """
    
    def __init__(self, browser: str = "edge", skill_dir: Optional[str] = None):
        """
        初始化桥接器
        
        Args:
            browser: 浏览器类型 (edge)
            skill_dir: xbrowser skill目录路径
        """
        self.browser = browser
        self.skill_dir = skill_dir or r"C:\Program Files\QClaw\resources\openclaw\config\skills\xbrowser"
        self.current_tab = None
        self._last_snapshot = None
        
    def _run_xb_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """
        执行xbrowser命令
        
        Args:
            command: xb命令字符串
            timeout: 超时时间(秒)
            
        Returns:
            命令执行结果字典
        """
        cmd = [
            "node",
            f"{self.skill_dir}\\scripts\\xb.cjs",
            "run",
            "--browser", self.browser,
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
                return {
                    "success": False,
                    "error": result.stderr or "Unknown error"
                }
            
            # 解析JSON输出
            try:
                output = json.loads(result.stdout)
                return output.get("data", {}).get("result", {})
            except json.JSONDecodeError:
                return {
                    "success": True,
                    "raw_output": result.stdout
                }
                
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"Command timeout after {timeout}s"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def _get_fresh_snapshot(self) -> Dict[str, Any]:
        """获取最新的DOM快照"""
        result = self._run_xb_command("snapshot -i", timeout=15)
        if result.get("success"):
            self._last_snapshot = result.get("data", {})
        return self._last_snapshot or {}
    
    def _find_element_by_role(self, role: str, name: Optional[str] = None) -> Optional[str]:
        """在快照中查找元素引用"""
        snapshot = self._get_fresh_snapshot()
        refs = snapshot.get("refs", {})
        
        for ref_id, info in refs.items():
            if info.get("role") == role:
                if name is None or name in info.get("name", ""):
                    return ref_id
        return None
    
    def open_assistant(self, assistant: AIAssistant) -> bool:
        """
        打开指定AI助手页面
        
        Args:
            assistant: AI助手类型
            
        Returns:
            是否成功打开
        """
        config = ASSISTANT_CONFIGS[assistant]
        result = self._run_xb_command(f"open {config.url}", timeout=30)
        
        if result.get("success"):
            self.current_tab = assistant
            print(f"[AI Bridge] 已打开 {config.name}")
            return True
        else:
            print(f"[AI Bridge] 打开 {config.name} 失败: {result.get('error')}")
            return False
    
    def switch_tab(self, assistant: AIAssistant) -> bool:
        """
        切换到指定助手的标签页
        
        Args:
            assistant: AI助手类型
            
        Returns:
            是否成功切换
        """
        # 获取所有标签页
        result = self._run_xb_command("tab", timeout=15)
        if not result.get("success"):
            print(f"[AI Bridge] 获取标签页失败: {result.get('error')}")
            return False
        
        tabs = result.get("data", {}).get("tabs", [])
        config = ASSISTANT_CONFIGS[assistant]
        
        # 查找匹配的URL
        for tab in tabs:
            if config.url.replace("https://", "").replace("http://", "") in tab.get("url", ""):
                tab_index = tab.get("index")
                switch_result = self._run_xb_command(f"tab {tab_index}", timeout=15)
                if switch_result.get("success"):
                    self.current_tab = assistant
                    print(f"[AI Bridge] 已切换到 {config.name} (标签页 {tab_index})")
                    return True
        
        print(f"[AI Bridge] 未找到 {config.name} 标签页，尝试重新打开")
        return self.open_assistant(assistant)
    
    def send_message(self, message: str, assistant: Optional[AIAssistant] = None) -> Dict[str, Any]:
        """
        向AI助手发送消息
        
        Args:
            message: 要发送的消息内容
            assistant: 目标助手(默认使用当前标签页)
            
        Returns:
            包含success和response的字典
        """
        target = assistant or self.current_tab
        if not target:
            return {"success": False, "error": "未指定AI助手且当前无活动标签页"}
        
        # 确保在正确的标签页
        if not self.switch_tab(target):
            return {"success": False, "error": f"无法切换到 {target.value}"}
        
        config = ASSISTANT_CONFIGS[target]
        
        try:
            # 1. 获取最新快照以获取准确的元素引用
            snapshot = self._get_fresh_snapshot()
            
            # 2. 查找输入框 (优先使用配置，否则动态查找)
            input_ref = config.input_ref
            # 尝试查找textbox
            if not input_ref or input_ref not in snapshot.get("refs", {}):
                input_ref = self._find_element_by_role("textbox")
                if not input_ref:
                    return {"success": False, "error": "未找到输入框"}
            
            # 3. 填充消息 (使用fill命令)
            fill_result = self._run_xb_command(f"fill {input_ref} \"{message}\"", timeout=15)
            if not fill_result.get("success"):
                # 填充消息失败时返回详细错误
            if not fill_result.get("success"):
                return {"success": False, "error": f"填充消息失败: {fill_result.get('error')}"}
            
            time.sleep(0.5)  # 短暂等待
            
            # 4. 获取最新快照查找发送按钮
            snapshot = self._get_fresh_snapshot()
            send_ref = config.send_ref
            
            # 如果配置的发送按钮不可用，动态查找
            if not send_ref or send_ref not in snapshot.get("refs", {}):
                # 查找包含"发送"的按钮
                for ref_id, info in snapshot.get("refs", {}).items():
                    if info.get("role") == "button" and "发送" in info.get("name", ""):
                        send_ref = ref_id
                        break
            
            if not send_ref:
                # 使用Enter键发送
                send_result = self._run_xb_command("press Enter", timeout=15)
            else:
                # 点击发送按钮
                send_result = self._run_xb_command(f"click {send_ref}", timeout=15)
            
            if not send_result.get("success"):
                return {"success": False, "error": f"发送消息失败: {send_result.get('error')}"}
            
            # 5. 等待回复
            print(f"[AI Bridge] 等待 {config.name} 回复...")
            time.sleep(config.response_wait_time)
            
            return {
                "success": True,
                "message": "消息已发送",
                "assistant": config.name,
                "sent_text": message
            }
            
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def _read_clipboard(self) -> str:
        """
        通过PowerShell读取剪贴板内容
        
        Returns:
            剪贴板文本内容
        """
        try:
            result = subprocess.run(
                ["powershell", "-Command", "Get-Clipboard -Format Text"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip() if result.stdout else ""
        except Exception:
            return ""

    def _find_copy_button(self) -> Optional[str]:
        """
        查找复制按钮元素
        
        Returns:
            复制按钮的引用ID，若未找到则返回None
        """
        snapshot = self._get_fresh_snapshot()
        refs = snapshot.get("refs", {})
        
        # 策略1：查找名称包含"复制"的按钮
        for ref_id, info in refs.items():
            name = info.get("name", "")
            if "复制" in name:
                print(f"[AI Bridge] 找到复制按钮: {ref_id} ({name})")
                return ref_id
        
        # 策略2：查找通用的复制图标按钮
        for ref_id, info in refs.items():
            role = info.get("role", "")
            if role == "button" or role == "generic":
                name = info.get("name", "")
                if "copy" in name.lower() or "复制" in name:
                    print(f"[AI Bridge] 找到复制按钮(策略2): {ref_id} ({name})")
                    return ref_id
        
        return None

    def get_response(self, assistant: Optional[AIAssistant] = None, use_copy: bool = True) -> Dict[str, Any]:
        """
        获取AI助手的最新回复
        
        Args:
            assistant: 目标助手(默认使用当前标签页)
            use_copy: 是否优先使用复制按钮(true=高效, false=截图OCR)
            
        Returns:
            包含回复内容的字典
        """
        target = assistant or self.current_tab
        if not target:
            return {"success": False, "error": "未指定AI助手"}

        # 方法1：复制按钮 + 剪贴板（高效，约5K tokens）
        if use_copy:
            copy_ref = self._find_copy_button()
            if copy_ref:
                try:
                    # 清空剪贴板
                    subprocess.run(
                        ["powershell", "-Command", "Set-Clipboard -Value ''"],
                        capture_output=True, timeout=3
                    )
                    
                    # 点击复制按钮
                    click_result = self._run_xb_command(f"click {copy_ref}", timeout=10)
                    if click_result.get("success"):
                        time.sleep(1)  # 等待复制完成
                        clipboard_text = self._read_clipboard()
                        if clipboard_text:
                            print(f"[AI Bridge] 复制读取成功，内容长度: {len(clipboard_text)}")
                            return {
                                "success": True,
                                "response": clipboard_text,
                                "method": "copy",
                                "assistant": ASSISTANT_CONFIGS[target].name
                            }
                except Exception as e:
                    print(f"[AI Bridge] 复制读取失败: {e}")
            else:
                print(f"[AI Bridge] 未找到复制按钮")

        # 方法2：截图OCR（低效，约50K tokens）
        screenshot_result = self._run_xb_command("screenshot", timeout=15)
        if screenshot_result.get("success"):
            path = screenshot_result.get("data", {}).get("path")
            return {
                "success": True,
                "screenshot_path": path,
                "method": "screenshot",
                "assistant": ASSISTANT_CONFIGS[target].name
            }
        else:
            return {"success": False, "error": screenshot_result.get("error")}
    
    def query(self, message: str, assistant: AIAssistant) -> Dict[str, Any]:
        """
        向指定助手发送查询并获取回复
        
        Args:
            message: 查询内容
            assistant: 目标助手
            
        Returns:
            完整的查询结果
        """
        print(f"[AI Bridge] 向 {ASSISTANT_CONFIGS[assistant].name} 查询: {message[:50]}...")
        
        # 发送消息
        send_result = self.send_message(message, assistant)
        if not send_result.get("success"):
            return send_result
        
        # 获取回复
        return self.get_response(assistant)
    
    def multi_query(self, message: str, assistants: List[AIAssistant] = None) -> Dict[str, Any]:
        """
        向多个助手发送相同查询，收集所有回复
        
        Args:
            message: 查询内容
            assistants: 助手列表(默认全部三个)
            
        Returns:
            各助手的回复汇总
        """
        if assistants is None:
            assistants = [AIAssistant.QIANWEN, AIAssistant.DOUBAO, AIAssistant.YUANBAO]
        
        results = {}
        for assistant in assistants:
            result = self.query(message, assistant)
            results[assistant.value] = result
            time.sleep(2)  # 助手间间隔
        
        return {
            "success": True,
            "query": message,
            "results": results
        }
    
    def vote_consensus(self, message: str) -> Dict[str, Any]:
        """
        多助手投票仲裁模式
        
        Args:
            message: 需要仲裁的问题
            
        Returns:
            包含各助手回复和综合结论的字典
        """
        print(f"[AI Bridge] 启动多助手投票仲裁: {message[:50]}...")
        
        multi_result = self.multi_query(message)
        if not multi_result.get("success"):
            return multi_result
        
        # 返回原始结果供人工判断
        return {
            "success": True,
            "mode": "vote_consensus",
            "query": message,
            "responses": multi_result["results"],
            "note": "请人工审查各助手回复，提取共识或判断分歧"
        }


# 便捷函数接口
def query_qianwen(message: str) -> Dict[str, Any]:
    """向千问发送查询"""
    bridge = AIAssistantBridge()
    return bridge.query(message, AIAssistant.QIANWEN)


def query_doubao(message: str) -> Dict[str, Any]:
    """向豆包发送查询"""
    bridge = AIAssistantBridge()
    return bridge.query(message, AIAssistant.DOUBAO)


def query_yuanbao(message: str) -> Dict[str, Any]:
    """向元宝发送查询"""
    bridge = AIAssistantBridge()
    return bridge.query(message, AIAssistant.YUANBAO)


def multi_assistants_query(message: str) -> Dict[str, Any]:
    """向所有助手发送查询"""
    bridge = AIAssistantBridge()
    return bridge.multi_query(message)


def vote_arbitration(message: str) -> Dict[str, Any]:
    """多助手投票仲裁"""
    bridge = AIAssistantBridge()
    return bridge.vote_consensus(message)


if __name__ == "__main__":
    # 测试代码
    print("="*60)
    print("AI Assistant Bridge V2.0 测试")
    print("="*60)
    
    bridge = AIAssistantBridge()
    
    # 测试向千问发送消息
    print("\n[Test] 向千问发送测试消息...")
    result = bridge.send_message("你好，这是AI桥接模块的测试消息。请回复'收到'。", AIAssistant.QIANWEN)
    
    if result.get("success"):
        print(f"[Test] 消息发送成功!")
        # 获取回复
        response = bridge.get_response(AIAssistant.QIANWEN)
        print(f"[Test] 截图保存至: {response.get('screenshot_path')}")
    else:
        print(f"[Test] 发送失败: {result.get('error')}")
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)
