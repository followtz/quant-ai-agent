# -*- coding: utf-8 -*-
"""
外脑Token占比监控脚本
监控外脑调用效率，生成外脑任务分配建议
"""
import os
import sys
import json
import datetime
from collections import defaultdict

WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)


class ExternalBrainMonitor:
    """外脑Token占比监控"""
    
    # 外脑Token占比要求
    RATIO_REQUIREMENTS = {
        'trading_hours': 0.40,   # 交易时段 ≥40%
        'non_trading_hours': 0.70  # 非交易时段 ≥70%
    }
    
    def __init__(self):
        self.history_path = os.path.join(WORKSPACE, 'data', 'history', 'token_usage_history.csv')
        self.report_path = os.path.join(WORKSPACE, 'data', 'logs', 'external_brain_report.json')
    
    def is_trading_hours(self) -> tuple:
        """判断当前是否在交易时段"""
        now = datetime.datetime.now()
        hour = now.hour
        weekday = now.weekday()
        
        if weekday >= 5:
            return False, 'weekend'
        
        # 港股 09:30-16:00
        if 9 <= hour < 16:
            return True, 'HK'
        
        # 美股 21:00-04:00
        if hour >= 21 or hour < 4:
            return True, 'US'
        
        return False, 'closed'
    
    def get_external_brain_usage(self, date: str = None) -> dict:
        """
        获取外脑使用统计
        Args:
            date: 日期字符串，默认今天
        Returns:
            外脑使用统计
        """
        if date is None:
            date = datetime.datetime.now().strftime('%Y-%m-%d')
        
        # 模拟外脑任务类型（需要实际接入ai_assistant_bridge.py获取）
        # 暂时基于历史数据估算
        external_types = ['research', 'planning']  # 假设这些类型使用外脑
        
        total = 0
        external_total = 0
        by_hour = defaultdict(lambda: {'total': 0, 'external': 0})
        
        if os.path.exists(self.history_path):
            import csv
            with open(self.history_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['date'] == date:
                        token = int(row['token_used'])
                        hour = row['hour']
                        total += token
                        by_hour[hour]['total'] += token
                        
                        if row['task_type'] in external_types:
                            external_total += token
                            by_hour[hour]['external'] += token
        
        ratio = external_total / total if total > 0 else 0
        
        return {
            'date': date,
            'total': total,
            'external': external_total,
            'internal': total - external_total,
            'ratio': ratio,
            'by_hour': dict(by_hour)
        }
    
    def check_ratio_compliance(self, usage: dict) -> dict:
        """
        检查占比合规性
        Args:
            usage: 外脑使用统计
        Returns:
            合规检查结果
        """
        is_trading, market = self.is_trading_hours()
        
        if is_trading:
            required_ratio = self.RATIO_REQUIREMENTS['trading_hours']
            period = 'trading_hours'
        else:
            required_ratio = self.RATIO_REQUIREMENTS['non_trading_hours']
            period = 'non_trading_hours'
        
        actual_ratio = usage['ratio']
        compliant = actual_ratio >= required_ratio
        gap = actual_ratio - required_ratio
        
        return {
            'period': period,
            'market': market,
            'required_ratio': required_ratio,
            'actual_ratio': actual_ratio,
            'gap': gap,
            'compliant': compliant,
            'status': 'ok' if compliant else ('warning' if gap > -0.1 else 'critical')
        }
    
    def generate_task_suggestions(self, compliance: dict) -> list:
        """
        生成外脑任务分配建议
        Args:
            compliance: 合规检查结果
        Returns:
            任务建议列表
        """
        suggestions = []
        
        if compliance['status'] == 'ok':
            suggestions.append({
                'type': 'success',
                'message': f'外脑占比{compliance["actual_ratio"]*100:.1f}%符合要求'
            })
        elif compliance['status'] == 'warning':
            suggestions.append({
                'type': 'warning',
                'message': f'外脑占比{compliance["actual_ratio"]*100:.1f}%低于要求{compliance["required_ratio"]*100:.0f}%，建议增加外脑任务'
            })
            suggestions.append({
                'type': 'action',
                'tasks': [
                    '信息检索类任务优先分配给外脑（豆包搜索）',
                    '长文本处理优先分配给外脑（元宝长文本）',
                    '代码review优先分配给外脑（千问代码）'
                ]
            })
        else:
            suggestions.append({
                'type': 'critical',
                'message': f'外脑占比严重不足，仅{compliance["actual_ratio"]*100:.1f}%'
            })
            suggestions.append({
                'type': 'action',
                'priority': 'high',
                'tasks': [
                    '立即将所有非核心任务切换至外脑执行',
                    '暂停自有算力执行research/planning类任务',
                    '检查ai_assistant_bridge.py连接状态'
                ]
            })
        
        return suggestions
    
    def run_monitoring(self) -> dict:
        """
        执行外脑监控
        Returns:
            监控报告
        """
        print("=" * 50)
        print(f"外脑Token占比监控: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)
        
        # 获取使用统计
        usage = self.get_external_brain_usage()
        print(f"\n今日Token使用: {usage['total']:,}")
        print(f"外脑消耗: {usage['external']:,} ({usage['ratio']*100:.1f}%)")
        print(f"自有消耗: {usage['internal']:,} ({(1-usage['ratio'])*100:.1f}%)")
        
        # 检查合规性
        compliance = self.check_ratio_compliance(usage)
        print(f"\n时段: {compliance['period']} ({compliance['market']})")
        print(f"要求占比: {compliance['required_ratio']*100:.0f}%")
        print(f"实际占比: {compliance['actual_ratio']*100:.1f}%")
        print(f"合规状态: {compliance['status']}")
        
        # 生成建议
        suggestions = self.generate_task_suggestions(compliance)
        print("\n任务建议:")
        for s in suggestions:
            print(f"  [{s['type']}] {s['message']}")
            if 'tasks' in s:
                for task in s['tasks']:
                    print(f"    - {task}")
        
        # 构建报告
        report = {
            'timestamp': datetime.datetime.now().isoformat(),
            'usage': usage,
            'compliance': compliance,
            'suggestions': suggestions
        }
        
        # 保存报告
        with open(self.report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n报告已保存: {self.report_path}")
        
        return report


def main():
    monitor = ExternalBrainMonitor()
    report = monitor.run_monitoring()
    return report


if __name__ == '__main__':
    main()
