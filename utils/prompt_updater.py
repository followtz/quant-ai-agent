# -*- coding: utf-8 -*-
"""
SYSTEM_PROMPT自动更新脚本
从SOUL.md提取核心指令，生成精简版SYSTEM_PROMPT.txt
"""
import os
import re
import hashlib
import json
from datetime import datetime

class PromptUpdater:
    """SYSTEM_PROMPT更新器"""
    
    MAX_CHARS = 8000  # 最大字符数
    
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.soul_path = os.path.join(workspace_path, 'SOUL.md')
        self.prompt_path = os.path.join(workspace_path, 'prompt', 'SYSTEM_PROMPT.txt')
        self.backup_path = os.path.join(workspace_path, 'backup', 'prompt')
        self.log_path = os.path.join(workspace_path, 'data', 'logs', 'prompt_update.log')
        self.confirm_path = os.path.join(workspace_path, 'config', 'prompt_confirm.json')
        
        # 确保目录存在
        os.makedirs(os.path.dirname(self.prompt_path), exist_ok=True)
        os.makedirs(self.backup_path, exist_ok=True)
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.confirm_path), exist_ok=True)
    
    def _get_md5(self, content: str) -> str:
        """计算MD5校验值"""
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def _load_soul(self) -> tuple:
        """
        加载SOUL.md
        Returns:
            (内容, MD5校验值)
        """
        if not os.path.exists(self.soul_path):
            raise FileNotFoundError(f'SOUL.md不存在: {self.soul_path}')
        
        with open(self.soul_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return content, self._get_md5(content)
    
    def _extract_core_rules(self, soul_content: str) -> str:
        """
        从SOUL.md提取核心规则
        Args:
            soul_content: SOUL.md内容
        Returns:
            提取的核心规则文本
        """
        sections = []
        
        # 1. 提取黄金状态变量
        golden_match = re.search(r'黄金状态变量[：:].+?(?=（|$)', soul_content)
        if golden_match:
            sections.append(f"# 1. 黄金状态变量（最高优先级）\n{golden_match.group()}\n")
        
        # 2. 提取核心风控规则
        risk_match = re.search(r'## 4\. 风险控制体系.+?(?=## 5\.|$)', soul_content, re.DOTALL)
        if risk_match:
            risk_text = risk_match.group()
            # 精简：只保留硬编码规则
            risk_lines = []
            for line in risk_text.split('\n'):
                if any(kw in line for kw in ['硬编码', '立即', '严禁', '禁止', '熔断', '切断']):
                    risk_lines.append(line)
            if risk_lines:
                sections.append(f"# 2. 核心风控规则（硬编码执行）\n" + '\n'.join(risk_lines[:10]) + "\n")
        
        # 3. 提取角色职责摘要
        role_match = re.search(r'### 2\.2 各角色核心职责.+?(?=## 3\.|$)', soul_content, re.DOTALL)
        if role_match:
            role_text = role_match.group()
            # 提取表格内容
            role_lines = []
            for line in role_text.split('\n'):
                if '|' in line and '风控官' in line or '交易执行官' in line or 'Token资源管理员' in line:
                    role_lines.append(line)
            if role_lines:
                sections.append(f"# 3. 核心角色职责\n" + '\n'.join(role_lines[:5]) + "\n")
        
        # 4. 提取运行时序
        time_match = re.search(r'### 9\.1 核心运行时序.+?(?=### 9\.2|$)', soul_content, re.DOTALL)
        if time_match:
            time_text = time_match.group()
            # 只保留关键时段
            time_lines = []
            for line in time_text.split('\n'):
                if any(kw in line for kw in ['港股时段', '美股时段', 'Token资源利用', '每日']):
                    time_lines.append(line)
            if time_lines:
                sections.append(f"# 4. 核心运行时序\n" + '\n'.join(time_lines[:8]) + "\n")
        
        # 5. 提取Token监控方式
        monitor_match = re.search(r'### 9\.3 Token监控方式.+?(?=### 9\.4|## 10\.|$)', soul_content, re.DOTALL)
        if monitor_match:
            monitor_text = monitor_match.group()
            # 提取表格
            monitor_lines = []
            in_table = False
            for line in monitor_text.split('\n'):
                if '|' in line and '监控方式' in line:
                    in_table = True
                if in_table and '|' in line:
                    monitor_lines.append(line)
                if in_table and not line.strip():
                    break
            if monitor_lines:
                sections.append(f"# 5. Token监控方式\n" + '\n'.join(monitor_lines[:6]) + "\n")
        
        # 6. 提取熔断分级
        fuse_match = re.search(r'### 5\.2 熔断分级.+?(?=## 6\.|$)', soul_content, re.DOTALL)
        if fuse_match:
            fuse_text = fuse_match.group()
            # 提取表格
            fuse_lines = []
            for line in fuse_text.split('\n'):
                if '|' in line and ('L1' in line or 'L2' in line or 'L3' in line or '等级' in line):
                    fuse_lines.append(line)
            if fuse_lines:
                sections.append(f"# 6. 熔断分级（强制执行）\n" + '\n'.join(fuse_lines) + "\n")
        
        # 7. 提取Token配额规则
        quota_match = re.search(r'### 10\.1 核心配额规则.+?(?=### 10\.2|$)', soul_content, re.DOTALL)
        if quota_match:
            quota_text = quota_match.group()
            quota_lines = []
            for line in quota_text.split('\n'):
                if any(kw in line for kw in ['总配额上限', '核心任务', '策略研究', '进化', '应急']):
                    quota_lines.append(line)
            if quota_lines:
                sections.append(f"# 7. Token配额规则\n" + '\n'.join(quota_lines[:6]) + "\n")
        
        # 合并所有部分
        core_rules = '\n'.join(sections)
        
        # 添加头部
        header = f"""# SYSTEM_PROMPT - 核心执行规则
# 自动生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# 来源: SOUL.md
# 字符数: {len(core_rules)}
# ================================

"""
        return header + core_rules
    
    def _check_confirmation_needed(self, new_md5: str) -> bool:
        """
        检查是否需要人工确认
        Args:
            new_md5: 新内容MD5
        Returns:
            是否需要确认
        """
        if not os.path.exists(self.confirm_path):
            return True
        
        with open(self.confirm_path, 'r', encoding='utf-8') as f:
            confirm_data = json.load(f)
        
        # 如果MD5相同，不需要确认
        return confirm_data.get('last_md5') != new_md5
    
    def _save_confirmation(self, md5: str, confirmed: bool):
        """
        保存确认状态
        Args:
            md5: MD5校验值
            confirmed: 是否已确认
        """
        confirm_data = {
            'last_md5': md5,
            'confirmed': confirmed,
            'update_time': datetime.now().isoformat()
        }
        with open(self.confirm_path, 'w', encoding='utf-8') as f:
            json.dump(confirm_data, f, ensure_ascii=False, indent=2)
    
    def _backup_old_prompt(self):
        """备份旧版SYSTEM_PROMPT"""
        if os.path.exists(self.prompt_path):
            timestamp = datetime.now().strftime('%Y%m%d')
            backup_file = os.path.join(self.backup_path, f'{timestamp}_SYSTEM_PROMPT.txt')
            with open(self.prompt_path, 'r', encoding='utf-8') as f:
                old_content = f.read()
            with open(backup_file, 'w', encoding='utf-8') as f:
                f.write(old_content)
    
    def _log_update(self, success: bool, message: str):
        """
        记录更新日志
        Args:
            success: 是否成功
            message: 日志消息
        """
        log_entry = f"{datetime.now().isoformat()} | {'SUCCESS' if success else 'FAILED'} | {message}\n"
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    def update(self, force: bool = False) -> dict:
        """
        执行SYSTEM_PROMPT更新
        Args:
            force: 是否强制更新（跳过确认检查）
        Returns:
            更新结果
        """
        try:
            # 1. 加载SOUL.md
            soul_content, soul_md5 = self._load_soul()
            
            # 2. 检查是否需要确认
            if not force and self._check_confirmation_needed(soul_md5):
                return {
                    'status': 'need_confirm',
                    'message': 'SOUL.md已变更，需要人工确认首次生效',
                    'md5': soul_md5
                }
            
            # 3. 提取核心规则
            core_rules = self._extract_core_rules(soul_content)
            
            # 4. 检查字符数
            if len(core_rules) > self.MAX_CHARS:
                core_rules = core_rules[:self.MAX_CHARS]
                self._log_update(False, f'内容超限，已截断至{self.MAX_CHARS}字符')
            
            # 5. 备份旧版
            self._backup_old_prompt()
            
            # 6. 写入新版
            with open(self.prompt_path, 'w', encoding='utf-8') as f:
                f.write(core_rules)
            
            # 7. 保存确认状态
            self._save_confirmation(soul_md5, True)
            
            # 8. 记录日志
            self._log_update(True, f'SYSTEM_PROMPT更新成功，字符数{len(core_rules)}')
            
            return {
                'status': 'success',
                'message': 'SYSTEM_PROMPT更新成功',
                'chars': len(core_rules),
                'md5': soul_md5
            }
            
        except Exception as e:
            self._log_update(False, str(e))
            return {
                'status': 'failed',
                'message': str(e)
            }
    
    def confirm(self, md5: str) -> dict:
        """
        人工确认更新
        Args:
            md5: 要确认的MD5
        Returns:
            确认结果
        """
        # 执行强制更新
        result = self.update(force=True)
        
        if result['status'] == 'success':
            self._save_confirmation(md5, True)
            return {
                'status': 'confirmed',
                'message': '已确认并更新SYSTEM_PROMPT'
            }
        else:
            return result


if __name__ == '__main__':
    # 测试
    workspace = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
    updater = PromptUpdater(workspace)
    
    result = updater.update()
    print(f"更新状态: {result['status']}")
    print(f"消息: {result['message']}")
    
    if result['status'] == 'need_confirm':
        print(f"\n需要确认MD5: {result['md5']}")
        # 模拟确认
        # confirm_result = updater.confirm(result['md5'])
        # print(f"确认结果: {confirm_result}")
