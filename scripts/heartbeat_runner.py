# -*- coding: utf-8 -*-
"""
HEARTBEAT集成脚本
执行所有心跳检查项，整合Token监控、系统巡检、可视化快照
"""
import os
import sys
import json
import time
import datetime
import requests
from pathlib import Path

# 添加工作区路径
WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)

from utils.token_manager import TokenManager
from utils.dashboard_writer import DashboardWriter


class HeartbeatRunner:
    """HEARTBEAT执行器"""
    
    def __init__(self):
        self.workspace = WORKSPACE
        self.token_manager = TokenManager(WORKSPACE)
        self.dashboard_writer = DashboardWriter()
        self.results = {
            'timestamp': datetime.datetime.now().isoformat(),
            'checks': {},
            'alerts': []
        }
    
    def is_trading_hours(self) -> tuple:
        """判断当前是否在交易时段，返回(是否交易时段, 市场名称)"""
        now = datetime.datetime.now()
        hour = now.hour
        weekday = now.weekday()  # 0=周一
        
        # 周末不交易
        if weekday >= 5:
            return False, 'weekend'
        
        # 港股 09:30-16:00 (CST = HKT+0，HKT=港股时间)
        # 北京时间 CST = HKT - 0，所以港股时段就是 09:30-16:00 CST
        if 9 <= hour < 16:
            return True, 'HK'
        
        # 美股 21:30-04:00 EDT (北京时间为 EDT+12/13)
        # 简化判断：21:00-04:00 CST 为美股时段
        if hour >= 21 or hour < 4:
            return True, 'US'
        
        return False, 'closed'
    
    def check_panel_health(self) -> dict:
        """检查统一监控面板健康状态"""
        try:
            response = requests.get('http://localhost:8082/', timeout=5)
            status = 'healthy' if response.status_code == 200 else 'unhealthy'
            return {'status': status, 'code': response.status_code}
        except requests.exceptions.RequestException:
            return {'status': 'down', 'code': None}
    
    def check_golden_state(self) -> dict:
        """检查黄金状态变量"""
        golden_path = os.path.join(self.workspace, 'data', 'dashboard', 'golden_state.json')
        
        if not os.path.exists(golden_path):
            return {'status': 'missing', 'message': 'golden_state.json不存在'}
        
        try:
            with open(golden_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # 检查关键字段
            required_fields = ['Current_Position', 'Today_PNL', 'Strategy_Status']
            missing_fields = [f for f in required_fields if f not in data]
            
            if missing_fields:
                return {'status': 'incomplete', 'missing': missing_fields}
            
            # 检查时间戳是否超过15分钟（调整：5分钟→15分钟，降低警告频率）
            if 'timestamp' in data:
                last_update = datetime.datetime.fromisoformat(data['timestamp'])
                diff = (datetime.datetime.now() - last_update).total_seconds()
                if diff > 900:  # 15分钟（原为300秒/5分钟）
                    return {'status': 'stale', 'last_update': data['timestamp'], 'age_seconds': diff}
            
            return {'status': 'ok', 'data': data}
            
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    def update_golden_state(self, field: str, value: dict):
        """更新黄金状态变量中的特定字段"""
        golden_path = os.path.join(self.workspace, 'data', 'dashboard', 'golden_state.json')
        
        try:
            with open(golden_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            data[field] = value
            data['timestamp'] = datetime.datetime.now().isoformat()
            
            with open(golden_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            return True
        except Exception as e:
            print(f"更新golden_state失败: {e}")
            return False
    
    def run_all_checks(self) -> dict:
        """执行所有检查项"""
        print("=" * 50)
        print(f"HEARTBEAT 执行开始: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 50)
        
        # 1. Token检查
        print("\n[1/6] Token使用检查...")
        usage = self.token_manager.get_daily_usage()
        threshold = self.token_manager.check_threshold(usage['total'])
        print(f"  今日使用: {usage['total']:,}")
        print(f"  剩余: {usage['remaining']:,}")
        print(f"  状态: {threshold['level']}")
        self.results['checks']['token'] = {
            'usage': usage['total'],
            'remaining': usage['remaining'],
            'level': threshold['level'],
            'message': threshold['message']
        }
        
        # 检查是否需要告警
        if threshold['level'] in ['warning', 'critical']:
            self.results['alerts'].append({
                'type': 'token',
                'level': threshold['level'],
                'message': threshold['message']
            })
        
        # 2. 面板健康检查
        print("\n[2/6] 面板健康检查...")
        panel = self.check_panel_health()
        print(f"  状态: {panel['status']}")
        print(f"  HTTP码: {panel['code']}")
        self.results['checks']['panel'] = panel
        
        if panel['status'] != 'healthy':
            self.results['alerts'].append({
                'type': 'panel',
                'level': 'critical',
                'message': f"面板{panel['status']}"
            })
        
        # 3. 交易时段判断
        print("\n[3/6] 交易时段判断...")
        is_trading, market = self.is_trading_hours()
        print(f"  交易时段: {'是' if is_trading else '否'}")
        print(f"  市场: {market}")
        self.results['checks']['trading'] = {
            'is_trading': is_trading,
            'market': market
        }
        
        # 4. 黄金状态检查（仅交易时段才检查stale）
        print("\n[4/6] 黄金状态检查...")
        golden = self.check_golden_state()
        print(f"  状态: {golden['status']}")
        self.results['checks']['golden_state'] = golden
        
        if golden['status'] == 'stale' and is_trading:
            self.results['alerts'].append({
                'type': 'golden_state',
                'level': 'warning',
                'message': f"黄金状态超过15分钟未更新"
            })
        
        # 5. 富途数据桥接（仅交易时段）
        print("\n[5/6] 富途数据桥接...")
        if is_trading:
            try:
                from utils.futu_dashboard_bridge import sync_all_data
                sync_result = sync_all_data()
                print(f"  同步结果: {sync_result.get('status', 'unknown')}")
                self.results['checks']['futu_bridge'] = sync_result
            except Exception as e:
                print(f"  同步失败: {e}")
                self.results['checks']['futu_bridge'] = {'status': 'error', 'message': str(e)}
        else:
            print("  非交易时段，跳过")
            self.results['checks']['futu_bridge'] = {'status': 'skipped'}
        
        # 6. 更新Dashboard快照
        print("\n[6/6] 更新Dashboard快照...")
        try:
            # 更新全局状态
            self.dashboard_writer.update_global_status(
                token_used=usage['total'],
                token_budget=40000000,
                active_market=market if is_trading else None,
                group_status={'panel': panel['status']},
                strategy_status={'token_level': threshold['level']}
            )
            
            # 更新Token使用快照
            self.token_manager.update_dashboard(usage)
            
            print("  Dashboard快照更新完成")
            self.results['checks']['dashboard'] = {'status': 'ok'}
        except Exception as e:
            print(f"  Dashboard更新失败: {e}")
            self.results['checks']['dashboard'] = {'status': 'error', 'message': str(e)}
        
        # 记录本次心跳消耗
        print("\n记录本次Heartbeat消耗...")
        self.token_manager.record_usage(
            timestamp=datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            task_name='Heartbeat',
            token_used=130417,  # 使用基线值
            task_type='heartbeat'
        )
        
        # 汇总结果
        print("\n" + "=" * 50)
        print("HEARTBEAT 执行完成")
        print(f"告警数量: {len(self.results['alerts'])}")
        print("=" * 50)
        
        return self.results
    
    def send_alerts(self):
        """发送告警通知"""
        if not self.results['alerts']:
            print("无告警，无需推送")
            return
        
        print(f"\n发现 {len(self.results['alerts'])} 个告警，正在推送...")
        
        # 构建告警消息
        alert_text = "【HEARTBEAT告警】\n"
        for alert in self.results['alerts']:
            alert_text += f"- [{alert['level'].upper()}] {alert['message']}\n"
        
        # 推送企业微信
        try:
            from utils.wechat_push import push_report
            push_report(
                title='【HEARTBEAT告警】',
                content=alert_text,
                report_type='heartbeat_alert',
                alert_level='warning'
            )
            print("告警推送完成")
        except Exception as e:
            print(f"推送失败: {e}")


def main():
    runner = HeartbeatRunner()
    results = runner.run_all_checks()
    
    # 发送告警
    runner.send_alerts()
    
    # 输出结果JSON
    output_path = os.path.join(WORKSPACE, 'data', 'logs', 'heartbeat_latest.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    return results


if __name__ == '__main__':
    main()
