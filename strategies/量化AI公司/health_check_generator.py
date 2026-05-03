# -*- coding: utf-8 -*-
"""
策略健康监测报告生成器
生成时间: 2026-04-14 04:13:00
"""

import json
import time
import psutil
from datetime import datetime
from pathlib import Path

# 配置
WORK_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司")
LOG_DIR = WORK_DIR / "06_龙虾自动运行日志"
LOG_DIR.mkdir(exist_ok=True)

def get_process_info(pid):
    """获取进程信息"""
    try:
        proc = psutil.Process(pid)
        return {
            'pid': pid,
            'name': proc.name(),
            'cpu_seconds': proc.cpu_times().user + proc.cpu_times().system,
            'memory_mb': round(proc.memory_info().rss / 1024 / 1024, 2),
            'status': proc.status(),
            'start_time': proc.create_time()
        }
    except psutil.NoSuchProcess:
        return None
    except Exception as e:
        return {'error': str(e)}

def check_web_service(url, timeout=5):
    """检查Web服务是否可访问"""
    try:
        import urllib.request
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return {
                'accessible': True,
                'status_code': response.status,
                'content_length': len(response.read())
            }
    except Exception as e:
        return {
            'accessible': False,
            'error': str(e)
        }

def check_futu_opend():
    """检查富途OpenD连接"""
    for proc in psutil.process_iter(['pid', 'name']):
        if 'OpenD' in proc.info['name'] or 'Futu' in proc.info['name']:
            return {
                'running': True,
                'pid': proc.info['pid'],
                'name': proc.info['name']
            }
    return {'running': False}

def generate_health_report():
    """生成健康监测报告"""
    timestamp = datetime.now()
    timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')
    date_str = timestamp.strftime('%Y%m%d')
    
    # 检查BTDR策略面板 (PID 608)
    btdr_info = get_process_info(608)
    btdr_web = check_web_service('http://localhost:8080')
    
    # 检查连连数字策略面板 (PID 4468)
    llsz_info = get_process_info(4468)
    llsz_web = check_web_service('http://localhost:8081')
    
    # 检查富途OpenD
    futu_status = check_futu_opend()
    
    # 构建报告
    report = {
        'timestamp': timestamp_str,
        'checks': {
            'btdr_strategy': {
                'name': 'BTDR策略面板',
                'expected_pid': 608,
                'process': btdr_info,
                'web_service': btdr_web,
                'status': '正常' if btdr_info and btdr_web.get('accessible') else '异常'
            },
            'llsz_strategy': {
                'name': '连连数字策略面板',
                'expected_pid': 4468,
                'process': llsz_info,
                'web_service': llsz_web,
                'status': '正常' if llsz_info and llsz_web.get('accessible') else '异常'
            },
            'futu_opend': {
                'name': '富途OpenD',
                'status': futu_status
            }
        },
        'system': {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('C:\\').percent
        }
    }
    
    # 保存JSON报告
    json_file = LOG_DIR / f'health_check_{date_str}.json'
    json_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    
    # 生成文本报告
    text_report = f"""
================================================================================
                    策略健康监测报告
================================================================================
监测时间: {timestamp_str}

【BTDR策略面板 (PID 608)】
状态: {'✅ 正常' if btdr_info and btdr_web.get('accessible') else '❌ 异常'}
进程运行: {'是' if btdr_info else '否'}
Web服务: {'可访问' if btdr_web.get('accessible') else '不可访问'}
{btdr_info and f"CPU时间: {btdr_info['cpu_seconds']:.2f}秒" or ''}
{btdr_info and f"内存占用: {btdr_info['memory_mb']:.2f} MB" or ''}

【连连数字策略面板 (PID 4468)】
状态: {'✅ 正常' if llsz_info and llsz_web.get('accessible') else '❌ 异常'}
进程运行: {'是' if llsz_info else '否'}
Web服务: {'可访问' if llsz_web.get('accessible') else '不可访问'}
{llsz_info and f"CPU时间: {llsz_info['cpu_seconds']:.2f}秒" or ''}
{llsz_info and f"内存占用: {llsz_info['memory_mb']:.2f} MB" or ''}

【富途OpenD连接】
状态: {'✅ 运行中' if futu_status['running'] else '❌ 未运行'}
{futu_status.get('pid') and f"PID: {futu_status['pid']}" or ''}

【系统资源】
CPU使用率: {report['system']['cpu_percent']:.1f}%
内存使用率: {report['system']['memory_percent']:.1f}%
磁盘使用率: {report['system']['disk_percent']:.1f}%

================================================================================
"""
    
    log_file = LOG_DIR / f'health_check_{date_str}_{timestamp.strftime("%H%M%S")}.log'
    log_file.write_text(text_report, encoding='utf-8')
    
    # 如果有异常，生成告警
    has_alert = False
    alert_details = []
    
    if not btdr_info:
        has_alert = True
        alert_details.append("BTDR策略面板进程未运行")
    if not btdr_web.get('accessible'):
        has_alert = True
        alert_details.append("BTDR策略面板Web服务不可访问")
    if not llsz_info:
        has_alert = True
        alert_details.append("连连数字策略面板进程未运行")
    if not llsz_web.get('accessible'):
        has_alert = True
        alert_details.append("连连数字策略面板Web服务不可访问")
    if not futu_status['running']:
        has_alert = True
        alert_details.append("富途OpenD未运行")
    
    if has_alert:
        alert_file = LOG_DIR / f'ALERT_{date_str}_{timestamp.strftime("%H%M%S")}.md'
        alert_content = f"""## 🚨 策略健康监测告警报告

**告警时间**: {timestamp_str}  
**告警级别**: {'🔴 严重' if len(alert_details) > 1 else '🟡 警告'}

---

### 异常检测

| 服务 | 状态 | 详情 |
|------|------|------|
"""
        if not btdr_info or not btdr_web.get('accessible'):
            alert_content += f"| **BTDR策略面板** | ❌ 异常 | {'PID 608 进程未运行' if not btdr_info else 'Web服务不可访问'} |\n"
        else:
            alert_content += f"| BTDR策略面板 | ✅ 正常 | PID 608 |\n"
            
        if not llsz_info or not llsz_web.get('accessible'):
            alert_content += f"| **连连数字策略面板** | ❌ 异常 | {'PID 4468 进程未运行' if not llsz_info else 'Web服务不可访问'} |\n"
        else:
            alert_content += f"| 连连数字策略面板 | ✅ 正常 | PID 4468 |\n"
            
        if not futu_status['running']:
            alert_content += f"| **富途OpenD** | ❌ 异常 | 进程未运行 |\n"
        else:
            alert_content += f"| 富途OpenD | ✅ 正常 | PID {futu_status.get('pid', 'N/A')} |\n"
        
        alert_content += f"""
---

### 系统资源

- CPU: {report['system']['cpu_percent']:.1f}%
- 内存: {report['system']['memory_percent']:.1f}%
- 磁盘: {report['system']['disk_percent']:.1f}%

---

### 建议操作

"""
        if not llsz_info:
            alert_content += """
1. **立即检查连连数字策略面板**
   - 查看日志文件定位崩溃原因
   - 尝试手动重启策略面板: `python v4_monitor_enhanced.py`
   - 检查配置文件是否正确

2. **验证交易影响**
   - 确认连连数字 V4 策略是否已停止交易
   - 检查持仓状态
   - 评估是否需要手动平仓
"""
        
        alert_content += f"""
---

*本报告由策略健康监测守护自动生成*
"""
        alert_file.write_text(alert_content, encoding='utf-8')
        print(f"⚠️  发现异常，已生成告警: {alert_file}")
    
    print(f"✅ 健康监测报告已生成: {log_file}")
    return report

if __name__ == '__main__':
    report = generate_health_report()
    print(json.dumps(report, indent=2, ensure_ascii=False))
