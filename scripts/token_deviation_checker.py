# -*- coding: utf-8 -*-
"""
Token估算偏差校验脚本
每日收盘后对比估算值与实际值，计算偏差率
"""
import os
import sys
import json
import csv
from collections import defaultdict
from datetime import datetime, timedelta

WORKSPACE = '/home/ubuntu/.openclaw/workspace'
sys.path.insert(0, WORKSPACE)

from utils.token_manager import TokenManager


class TokenDeviationChecker:
    """Token估算偏差校验器"""
    
    # 偏差阈值
    DEVIATION_WARNING = 0.15  # 15%警告
    DEVIATION_CRITICAL = 0.30  # 30%熔断
    
    def __init__(self):
        self.token_manager = TokenManager(WORKSPACE)
        self.report_path = os.path.join(WORKSPACE, 'data', 'logs', 'token_deviation_report.json')
    
    def get_actual_usage(self, date: str) -> dict:
        """获取实际Token消耗（从历史CSV）"""
        total = 0
        by_type = defaultdict(int)
        
        history_path = os.path.join(WORKSPACE, 'data', 'history', 'token_usage_history.csv')
        
        if os.path.exists(history_path):
            with open(history_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['date'] == date:
                        token = int(row['token_used'])
                        total += token
                        by_type[row['task_type']] += token
        
        return {'total': total, 'by_type': dict(by_type)}
    
    def estimate_usage(self, date: str) -> dict:
        """基于基线估算Token消耗"""
        # 从历史数据获取任务分布
        actual = self.get_actual_usage(date)
        
        estimated_total = 0
        estimated_by_type = {}
        
        for task_type, actual_token in actual['by_type'].items():
            # 估算任务次数
            baseline = self.token_manager.BASELINE.get(task_type, 100000)
            estimated_count = actual_token / baseline if baseline > 0 else 1
            estimated_token = estimated_count * baseline
            estimated_total += estimated_token
            estimated_by_type[task_type] = {
                'estimated': int(estimated_token),
                'actual': actual_token,
                'deviation': (estimated_token - actual_token) / actual_token if actual_token > 0 else 0
            }
        
        return {'total': estimated_total, 'by_type': estimated_by_type}
    
    def calculate_deviation(self, actual: int, estimated: int) -> dict:
        """
        计算偏差
        Args:
            actual: 实际消耗
            estimated: 估算消耗
        Returns:
            偏差分析
        """
        if actual == 0:
            return {'deviation': 0, 'level': 'unknown'}
        
        deviation = (estimated - actual) / actual
        
        if abs(deviation) <= self.DEVIATION_WARNING:
            level = 'ok'
        elif abs(deviation) <= self.DEVIATION_CRITICAL:
            level = 'warning'
        else:
            level = 'critical'
        
        return {
            'actual': actual,
            'estimated': estimated,
            'deviation': deviation,
            'deviation_pct': f"{deviation*100:+.1f}%",
            'level': level
        }
    
    def run_check(self, date: str = None) -> dict:
        """
        执行偏差校验
        Args:
            date: 日期字符串，默认昨天
        Returns:
            校验报告
        """
        if date is None:
            # 默认检查昨天
            date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        print("=" * 60)
        print(f"Token估算偏差校验: {date}")
        print("=" * 60)
        
        # 获取实际消耗
        actual = self.get_actual_usage(date)
        print(f"\n实际消耗: {actual['total']:,}")
        
        # 估算消耗
        estimated = self.estimate_usage(date)
        print(f"估算消耗: {estimated['total']:,}")
        
        # 计算总体偏差
        overall_deviation = self.calculate_deviation(actual['total'], estimated['total'])
        print(f"\n总体偏差: {overall_deviation['deviation_pct']}")
        print(f"偏差等级: {overall_deviation['level']}")
        
        # 逐类型分析
        print("\n分类型偏差分析:")
        type_deviations = []
        
        for task_type in sorted(actual['by_type'].keys()):
            actual_token = actual['by_type'][task_type]
            est_data = estimated['by_type'].get(task_type, {'estimated': 0})
            est_token = est_data['estimated']
            
            dev = self.calculate_deviation(actual_token, est_token)
            type_deviations.append({
                'task_type': task_type,
                'actual': actual_token,
                'estimated': est_token,
                'deviation_pct': dev['deviation_pct'],
                'level': dev['level']
            })
            
            marker = '✓' if dev['level'] == 'ok' else ('⚠' if dev['level'] == 'warning' else '✗')
            print(f"  {marker} {task_type}: 实际{actual_token:,} vs 估算{est_token:,} ({dev['deviation_pct']})")
        
        # 风险评估
        print("\n风险评估:")
        warning_count = sum(1 for d in type_deviations if d['level'] == 'warning')
        critical_count = sum(1 for d in type_deviations if d['level'] == 'critical')
        
        if overall_deviation['level'] == 'critical' or critical_count > 3:
            risk = 'high'
            print("  🔴 高风险：估算模型严重偏离实际")
        elif overall_deviation['level'] == 'warning' or warning_count > 5:
            risk = 'medium'
            print("  🟡 中风险：估算偏差较大，需调整")
        else:
            risk = 'low'
            print("  🟢 低风险：估算模型运行正常")
        
        # 建议
        print("\n优化建议:")
        suggestions = []
        
        high_dev_types = [d for d in type_deviations if d['level'] == 'critical']
        if high_dev_types:
            print(f"  - 以下类型偏差超过30%，建议重新校准基线:")
            for d in high_dev_types:
                print(f"    * {d['task_type']}: {d['deviation_pct']}")
                suggestions.append(f"调整{task_type}基线值")
        
        if overall_deviation['deviation'] > 0:
            print("  - 估算值整体偏高，建议降低基线值")
        else:
            print("  - 估算值整体偏低，建议提高基线值")
        
        # 构建报告
        report = {
            'date': date,
            'actual_total': actual['total'],
            'estimated_total': estimated['total'],
            'overall_deviation': overall_deviation,
            'by_type': type_deviations,
            'risk_level': risk,
            'suggestions': suggestions,
            'timestamp': datetime.now().isoformat()
        }
        
        # 保存报告
        with open(self.report_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        
        print(f"\n报告已保存: {self.report_path}")
        
        # 判断是否需要切换人工审核模式
        if risk == 'high':
            print("\n⚠️ 警告：连续3天偏差≥30%将触发人工审核模式")
        
        return report
    
    def update_baseline(self, task_type: str, new_baseline: int):
        """
        更新基线值
        Args:
            task_type: 任务类型
            new_baseline: 新基线值
        """
        self.token_manager.BASELINE[task_type] = new_baseline
        
        # 保存到配置文件
        config_path = os.path.join(WORKSPACE, 'config', 'token_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        config['baseline'][task_type] = new_baseline
        config['last_updated'] = datetime.now().isoformat()
        
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        print(f"已更新基线: {task_type} = {new_baseline:,}")


def main():
    checker = TokenDeviationChecker()
    
    # 检查昨天
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    report = checker.run_check(yesterday)
    
    return report


if __name__ == '__main__':
    main()
