# -*- coding: utf-8 -*-
"""
连连数字V4双重确认策略 - 综合监控面板
监控V4策略运行状态
"""
import json
import time
import psutil
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

def _get_ll_position() -> int:
    """从富途OpenD API查询连连数字(HK.02598)实际持仓"""
    try:
        from futu import OpenSecTradeContext, TrdMarket, SecurityFirm, TrdEnv, RET_OK
        tctx = OpenSecTradeContext(
            filter_trdmarket=TrdMarket.NONE,
            security_firm=SecurityFirm.FUTUSECURITIES)
        ret, df = tctx.position_list_query(trd_env=TrdEnv.REAL)
        tctx.close()
        if ret == RET_OK and df is not None and not df.empty:
            ll = df[df.get('code', '').str.contains('02598|LL', na=False)]
            if not ll.empty:
                return int(ll.iloc[0].get('qty', 0))
    except Exception:
        pass
    return 8000  # 回退默认值

# 监控数据存储
monitor_data = {
    'v4_strategy': {
        'name': '连连数字V4双重确认',
        'status': 'stopped',
        'pid': None,
        'last_update': None,
        'position': 8000,
        'cash': 100000,
        'today_trades': 0,
        'total_trades': 0,
        'signals': {
            'v3': False,
            'mean_reversion': False,
            'ml': False
        },
        'last_signal': None
    },
    'system': {
        'cpu_percent': 0,
        'memory_percent': 0,
        'disk_percent': 0
    }
}

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>连连数字V4双重确认 - 监控面板</title>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="5">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e27;
            color: #fff;
            padding: 20px;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 10px;
        }
        .header h1 { font-size: 28px; margin-bottom: 10px; }
        .header .subtitle { opacity: 0.8; font-size: 14px; }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .card {
            background: #1a1f3a;
            border-radius: 10px;
            padding: 20px;
            border: 1px solid #2a3050;
        }
        .card h2 {
            font-size: 16px;
            color: #8892b0;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-running { background: #00d084; color: #000; }
        .status-stopped { background: #ff4757; color: #fff; }
        
        .metric {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #2a3050;
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #8892b0; }
        .metric-value { font-weight: bold; font-size: 18px; }
        .positive { color: #00d084; }
        .negative { color: #ff4757; }
        
        .signal-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 10px;
        }
        .signal-box {
            padding: 15px;
            border-radius: 8px;
            text-align: center;
            background: #2a3050;
        }
        .signal-box.active {
            background: linear-gradient(135deg, #00d084 0%, #00b894 100%);
            color: #000;
        }
        .signal-box.inactive {
            background: #2a3050;
            color: #8892b0;
        }
        .signal-name { font-size: 12px; margin-bottom: 5px; }
        .signal-status { font-weight: bold; }
        
        .strategy-info {
            background: #1a1f3a;
            border-radius: 10px;
            padding: 20px;
            margin-top: 20px;
        }
        .strategy-info h3 {
            color: #667eea;
            margin-bottom: 15px;
        }
        .param-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #2a3050;
        }
        .param-row:last-child { border-bottom: none; }
        
        .footer {
            text-align: center;
            margin-top: 30px;
            padding: 20px;
            color: #8892b0;
            font-size: 12px;
        }
        
        .refresh-info {
            text-align: center;
            color: #8892b0;
            font-size: 12px;
            margin-bottom: 20px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>连连数字V4双重确认</h1>
        <div class="subtitle">V3涡轮 + ML信号 + 均值回归 | 双重确认策略</div>
    </div>
    
    <div class="refresh-info">页面每5秒自动刷新 | 最后更新: {{ now }}</div>
    
    <div class="grid">
        <!-- 策略状态 -->
        <div class="card">
            <h2>策略状态</h2>
            <div class="metric">
                <span class="metric-label">运行状态</span>
                <span class="status-badge status-{{ 'running' if data.v4_strategy.status == 'running' else 'stopped' }}">
                    {{ '运行中' if data.v4_strategy.status == 'running' else '已停止' }}
                </span>
            </div>
            <div class="metric">
                <span class="metric-label">进程ID</span>
                <span class="metric-value">{{ data.v4_strategy.pid or '-' }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">最后更新</span>
                <span class="metric-value">{{ data.v4_strategy.last_update or '-' }}</span>
            </div>
        </div>
        
        <!-- 持仓信息 -->
        <div class="card">
            <h2>持仓信息</h2>
            <div class="metric">
                <span class="metric-label">当前持仓</span>
                <span class="metric-value">{{ data.v4_strategy.position }} 股</span>
            </div>
            <div class="metric">
                <span class="metric-label">可用现金</span>
                <span class="metric-value">${{ "%.2f"|format(data.v4_strategy.cash) }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">持仓范围</span>
                <span class="metric-value">6,000 - 10,000 股</span>
            </div>
        </div>
        
        <!-- 交易统计 -->
        <div class="card">
            <h2>交易统计</h2>
            <div class="metric">
                <span class="metric-label">今日交易</span>
                <span class="metric-value">{{ data.v4_strategy.today_trades }} 笔</span>
            </div>
            <div class="metric">
                <span class="metric-label">累计交易</span>
                <span class="metric-value">{{ data.v4_strategy.total_trades }} 笔</span>
            </div>
            <div class="metric">
                <span class="metric-label">日交易上限</span>
                <span class="metric-value">2 笔</span>
            </div>
        </div>
    </div>
    
    <!-- 信号状态 -->
    <div class="card">
        <h2>实时信号状态 (需2个确认才交易)</h2>
        <div class="signal-grid">
            <div class="signal-box {{ 'active' if data.v4_strategy.signals.v3 else 'inactive' }}">
                <div class="signal-name">V3涡轮</div>
                <div class="signal-status">{{ '触发' if data.v4_strategy.signals.v3 else '未触发' }}</div>
            </div>
            <div class="signal-box {{ 'active' if data.v4_strategy.signals.mean_reversion else 'inactive' }}">
                <div class="signal-name">均值回归</div>
                <div class="signal-status">{{ '触发' if data.v4_strategy.signals.mean_reversion else '未触发' }}</div>
            </div>
            <div class="signal-box {{ 'active' if data.v4_strategy.signals.ml else 'inactive' }}">
                <div class="signal-name">ML预测</div>
                <div class="signal-status">{{ '触发' if data.v4_strategy.signals.ml else '未触发' }}</div>
            </div>
        </div>
    </div>
    
    <!-- 策略参数 -->
    <div class="strategy-info">
        <h3>V4策略参数配置</h3>
        <div class="param-row">
            <span>V3阈值</span>
            <span>价格偏离20日均线 ±5%</span>
        </div>
        <div class="param-row">
            <span>均值回归</span>
            <span>Z-Score > |2.0|</span>
        </div>
        <div class="param-row">
            <span>ML置信度</span>
            <span>> 50%</span>
        </div>
        <div class="param-row">
            <span>确认机制</span>
            <span>双重确认 (任意2个信号)</span>
        </div>
        <div class="param-row">
            <span>单笔交易量</span>
            <span>1,000 股</span>
        </div>
    </div>
    
    <!-- 回测表现 -->
    <div class="strategy-info">
        <h3>回测表现 (2025-04-11 ~ 2026-04-10)</h3>
        <div class="param-row">
            <span>策略收益</span>
            <span class="positive">+3.67%</span>
        </div>
        <div class="param-row">
            <span>超额收益 (vs Buy&Hold)</span>
            <span class="positive">+40.28%</span>
        </div>
        <div class="param-row">
            <span>最大回撤</span>
            <span class="negative">-16.99%</span>
        </div>
        <div class="param-row">
            <span>总交易次数</span>
            <span>43 笔</span>
        </div>
    </div>
    
    <div class="footer">
        <p>连连数字V4双重确认策略监控面板 | 端口: 8081</p>
        <p>数据仅供参考，投资有风险</p>
    </div>
</body>
</html>
'''


def update_system_stats():
    """更新系统状态"""
    monitor_data['system']['cpu_percent'] = psutil.cpu_percent()
    monitor_data['system']['memory_percent'] = psutil.virtual_memory().percent
    monitor_data['system']['disk_percent'] = psutil.disk_usage('/').percent


def check_strategy_status():
    """检查策略运行状态"""
    # 检查v4_live_engine.py是否在运行
    v4_running = False
    v4_pid = None
    
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if 'v4_live_engine.py' in cmdline:
                v4_running = True
                v4_pid = proc.info['pid']
                break
        except:
            pass
    
    monitor_data['v4_strategy']['status'] = 'running' if v4_running else 'stopped'
    monitor_data['v4_strategy']['pid'] = v4_pid
    # 动态持仓
    monitor_data['v4_strategy']['position'] = _get_ll_position()


@app.route('/')
def index():
    """主页"""
    update_system_stats()
    check_strategy_status()
    
    return render_template_string(
        HTML_TEMPLATE,
        data=monitor_data,
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )


@app.route('/api/status')
def api_status():
    """API状态"""
    update_system_stats()
    check_strategy_status()
    return jsonify(monitor_data)


@app.route('/api/signals', methods=['POST'])
def update_signals():
    """更新信号状态 (由策略引擎调用)"""
    data = request.json
    if 'v4_strategy' in data:
        monitor_data['v4_strategy'].update(data['v4_strategy'])
    return jsonify({'status': 'ok'})


def main():
    """主函数"""
    print("="*70)
    print("连连数字V4双重确认策略 - 监控面板")
    print("="*70)
    print("访问地址: http://localhost:8081")
    print("按 Ctrl+C 停止")
    print("="*70)
    
    app.run(host='0.0.0.0', port=8081, debug=False)


if __name__ == '__main__':
    from flask import request
    main()
