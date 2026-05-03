# -*- coding: utf-8 -*-
"""
Token资源估算与分配模块
基于历史数据估算Token消耗，进行配额分配与预警
"""
import os
import csv
import json
from datetime import datetime, timedelta
from collections import defaultdict

class TokenManager:
    """Token资源管理器"""
    
    # 硬编码上限
    DAILY_LIMIT = 40_000_000  # 4000万
    WARNING_THRESHOLD = 35_000_000  # 3500万预警
    CRITICAL_THRESHOLD = 38_000_000  # 3800万红色预警
    
    # 配额划分
    QUOTA = {
        'core': 0.30,      # 核心任务（风控/交易）
        'research': 0.40,  # 策略研究/AI学习
        'evolution': 0.20, # 进化/审计/规划
        'emergency': 0.10  # 应急配额
    }
    
    # Token消耗基线（基于历史数据实测）
    BASELINE = {
        'task': 394696,
        'strategy': 498419,
        'evolution': 387138,
        'ops': 374359,
        'backtest': 871587,
        'exec': 189535,
        'planning': 708395,
        'research': 602689,
        'cron': 107924,
        'internal': 141111,
        'error': 119678,
        'subagent': 133369,
        'summary': 15828,
        'heartbeat': 130417,
        'memory': 27680
    }
    
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.history_path = os.path.join(workspace_path, 'data', 'history', 'token_usage_history.csv')
        self.config_path = os.path.join(workspace_path, 'config', 'token_config.json')
        self.dashboard_path = os.path.join(workspace_path, 'data', 'dashboard', 'token_usage.json')
        
        # 确保目录存在
        os.makedirs(os.path.dirname(self.history_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.dashboard_path), exist_ok=True)
        
        # 加载配置
        self.config = self._load_config()
        
    def _load_config(self) -> dict:
        """加载Token配置"""
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            'daily_limit': self.DAILY_LIMIT,
            'warning_threshold': self.WARNING_THRESHOLD,
            'critical_threshold': self.CRITICAL_THRESHOLD,
            'quota': self.QUOTA,
            'baseline': self.BASELINE
        }
    
    def estimate_task_token(self, task_type: str, complexity: float = 1.0, time_factor: float = 1.0) -> int:
        """
        估算任务Token消耗
        Args:
            task_type: 任务类型
            complexity: 复杂度系数（默认1.0）
            time_factor: 时段系数（交易时段1.2，非交易时段0.8）
        Returns:
            估算的Token消耗
        """
        baseline = self.BASELINE.get(task_type, 100000)
        return int(baseline * complexity * time_factor)
    
    def get_daily_usage(self, date: str = None) -> dict:
        """
        获取指定日期的Token使用情况
        Args:
            date: 日期字符串（YYYY-MM-DD），默认今天
        Returns:
            使用情况字典
        """
        if date is None:
            date = datetime.now().strftime('%Y-%m-%d')
        
        total = 0
        by_type = defaultdict(int)
        by_hour = defaultdict(int)
        
        if os.path.exists(self.history_path):
            with open(self.history_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['date'] == date:
                        token = int(row['token_used'])
                        total += token
                        by_type[row['task_type']] += token
                        by_hour[row['hour']] += token
        
        return {
            'date': date,
            'total': total,
            'remaining': self.DAILY_LIMIT - total,
            'usage_rate': total / self.DAILY_LIMIT,
            'by_type': dict(by_type),
            'by_hour': dict(by_hour)
        }
    
    def check_threshold(self, current_usage: int) -> dict:
        """
        检查Token使用阈值
        Args:
            current_usage: 当前使用量
        Returns:
            阈值检查结果
        """
        if current_usage >= self.CRITICAL_THRESHOLD:
            return {
                'level': 'critical',
                'message': f'Token使用已达{current_usage:,}，触发红色预警',
                'action': '仅保留风控/交易类核心操作'
            }
        elif current_usage >= self.WARNING_THRESHOLD:
            return {
                'level': 'warning',
                'message': f'Token使用已达{current_usage:,}，触发橙色预警',
                'action': '暂停非核心任务'
            }
        else:
            return {
                'level': 'normal',
                'message': f'Token使用正常：{current_usage:,}',
                'action': None
            }
    
    def allocate_quota(self, task_type: str) -> dict:
        """
        分配Token配额
        Args:
            task_type: 任务类型
        Returns:
            配额分配结果
        """
        # 核心任务类型
        core_types = ['task', 'strategy', 'ops', 'heartbeat']
        research_types = ['research', 'backtest', 'evolution']
        evolution_types = ['planning', 'summary', 'memory']
        
        if task_type in core_types:
            quota_type = 'core'
        elif task_type in research_types:
            quota_type = 'research'
        elif task_type in evolution_types:
            quota_type = 'evolution'
        else:
            quota_type = 'research'  # 默认归入研究类
        
        quota_amount = int(self.DAILY_LIMIT * self.QUOTA[quota_type])
        
        return {
            'task_type': task_type,
            'quota_type': quota_type,
            'quota_amount': quota_amount,
            'estimated': self.BASELINE.get(task_type, 100000)
        }
    
    def record_usage(self, timestamp: str, task_name: str, token_used: int, task_type: str):
        """
        记录Token使用
        Args:
            timestamp: 时间戳
            task_name: 任务名称
            token_used: Token消耗
            task_type: 任务类型
        """
        dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        date = dt.strftime('%Y-%m-%d')
        hour = dt.strftime('%H')
        
        # 追加写入CSV
        with open(self.history_path, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            # 检查是否需要写入表头
            if os.path.getsize(self.history_path) == 0:
                writer.writerow(['timestamp', 'task_name', 'token_used', 'task_type', 'date', 'hour'])
            writer.writerow([timestamp, task_name, token_used, task_type, date, hour])
    
    def update_dashboard(self, usage_data: dict):
        """
        更新Dashboard状态文件
        Args:
            usage_data: 使用数据
        """
        with open(self.dashboard_path, 'w', encoding='utf-8') as f:
            json.dump(usage_data, f, ensure_ascii=False, indent=2)
    
    def generate_daily_report(self, date: str = None) -> dict:
        """
        生成每日Token使用报告
        Args:
            date: 日期字符串，默认今天
        Returns:
            报告字典
        """
        usage = self.get_daily_usage(date)
        threshold = self.check_threshold(usage['total'])
        
        # 计算估算偏差（需要实际数据对比）
        # 这里简化处理，实际需要对比估算值与实际值
        
        report = {
            'date': usage['date'],
            'total_used': usage['total'],
            'remaining': usage['remaining'],
            'usage_rate': f"{usage['usage_rate']*100:.1f}%",
            'threshold_status': threshold,
            'by_type': usage['by_type'],
            'recommendations': []
        }
        
        # 生成建议
        if usage['usage_rate'] > 0.8:
            report['recommendations'].append('建议减少非核心任务，优先保障风控/交易')
        if usage['by_type'].get('evolution', 0) > 2_000_000:
            report['recommendations'].append('进化类任务消耗较高，建议优化外脑协同')
        
        return report


if __name__ == '__main__':
    # 测试
    workspace = '/home/ubuntu/.openclaw/workspace'
    tm = TokenManager(workspace)
    
    # 获取今日使用情况
    today_usage = tm.get_daily_usage()
    print(f"今日Token使用: {today_usage['total']:,}")
    print(f"剩余: {today_usage['remaining']:,}")
    
    # 检查阈值
    threshold = tm.check_threshold(today_usage['total'])
    print(f"阈值状态: {threshold['level']} - {threshold['message']}")
    
    # 估算任务Token
    estimated = tm.estimate_task_token('strategy', complexity=1.2, time_factor=1.0)
    print(f"策略分析任务估算: {estimated:,}")
