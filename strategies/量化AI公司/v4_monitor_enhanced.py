# -*- coding: utf-8 -*-
"""
V4 Monitor 增强版 - 添加实时账户数据API
"""
import json
import time
import psutil
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, jsonify, request

# 富途API导入
try:
    from futu import OpenSecTradeContext, OpenQuoteContext, RET_OK, TrdEnv, KLType, AuType
    from datetime import datetime as dt
    from datetime import timedelta
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    print("[警告] 富途API未安装，无法获取实时账户数据")

app = Flask(__name__)

# 实盘账户配置
REAL_ACCOUNT_ID = 281756477947279377

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
    'real_account': {
        'total_assets': 0,
        'cash_hk': 0,
        'cash_us': 0,
        'market_value': 0,
        'buying_power': 0,
        'positions': [],
        'last_update': None
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

        .real-account-card {
            background: linear-gradient(135deg, #1a1f3a 0%, #2a3050 100%);
            border: 2px solid #667eea;
        }
        .real-account-card h2 {
            color: #667eea;
        }

        .position-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #2a3050;
            font-size: 14px;
        }
        .position-code { font-weight: bold; }
        .position-pl { font-weight: bold; }

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

        .account-summary {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin-bottom: 15px;
        }
        .account-item {
            background: #2a3050;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
        }
        .account-item .label { font-size: 12px; color: #8892b0; }
        .account-item .value { font-size: 16px; font-weight: bold; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>连连数字V4双重确认</h1>
        <div class="subtitle">V3涡轮 + ML信号 + 均值回归 | 实盘账户数据</div>
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

        <!-- 配置持仓（旧） -->
        <div class="card">
            <h2>策略配置持仓</h2>
            <div class="metric">
                <span class="metric-label">配置持仓</span>
                <span class="metric-value">{{ data.v4_strategy.position }} 股</span>
            </div>
            <div class="metric">
                <span class="metric-label">配置现金</span>
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

    <!-- 实盘账户数据（新） -->
    <div class="card real-account-card">
        <h2>💰 实盘账户数据 (富途实盘)</h2>
        <div class="account-summary">
            <div class="account-item">
                <div class="label">总资产</div>
                <div class="value">HKD {{ "%.2f"|format(data.real_account.total_assets) }}</div>
            </div>
            <div class="account-item">
                <div class="label">市值</div>
                <div class="value">HKD {{ "%.2f"|format(data.real_account.market_value) }}</div>
            </div>
            <div class="account-item">
                <div class="label">港股现金</div>
                <div class="value {{ 'negative' if data.real_account.cash_hk < 5000 else '' }}">HKD {{ "%.2f"|format(data.real_account.cash_hk) }}</div>
            </div>
            <div class="account-item">
                <div class="label">美股现金</div>
                <div class="value">USD {{ "%.2f"|format(data.real_account.cash_us) }}</div>
            </div>
        </div>

        <h3 style="color: #8892b0; margin: 15px 0 10px; font-size: 14px;">实盘持仓</h3>
        {% for pos in data.real_account.positions %}
        <div class="position-row">
            <span class="position-code">{{ pos.code }} {{ pos.name }}</span>
            <span>{{ pos.qty }}股</span>
            <span>{{ "%.2f"|format(pos.cost_price) }}</span>
            <span class="position-pl {{ 'negative' if pos.pl_ratio < 0 else 'positive' }}">
                {{ "%.1f"|format(pos.pl_ratio) }}% ({{ "%.0f"|format(pos.pl_val) }})
            </span>
        </div>
        {% endfor %}

        <div style="text-align: right; margin-top: 10px; font-size: 12px; color: #8892b0;">
            更新时间: {{ data.real_account.last_update or '未连接' }}
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

    <!-- 系统资源 -->
    <div class="card">
        <h2>系统资源</h2>
        <div class="metric">
            <span class="metric-label">CPU</span>
            <span class="metric-value">{{ "%.1f"|format(data.system.cpu_percent) }}%</span>
        </div>
        <div class="metric">
            <span class="metric-label">内存</span>
            <span class="metric-value {{ 'negative' if data.system.memory_percent > 90 else '' }}">{{ "%.1f"|format(data.system.memory_percent) }}%</span>
        </div>
        <div class="metric">
            <span class="metric-label">磁盘</span>
            <span class="metric-value">{{ "%.1f"|format(data.system.disk_percent) }}%</span>
        </div>
    </div>

    <div class="footer">
        <p>连连数字V4双重确认策略监控面板 | 端口: 8081</p>
        <p>实盘账户: {{ real_acc_id }} | 数据仅供参考</p>
    </div>
</body>
</html>
'''


def update_system_stats():
    """更新系统状态"""
    monitor_data['system']['cpu_percent'] = psutil.cpu_percent()
    monitor_data['system']['memory_percent'] = psutil.virtual_memory().percent
    monitor_data['system']['disk_percent'] = psutil.disk_usage('C:\\').percent


def check_strategy_status():
    """检查策略运行状态"""
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


def get_real_account_info():
    """从富途API获取实盘账户数据"""
    if not FUTU_AVAILABLE:
        return None

    ctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
    try:
        # 获取账户资金
        ret1, data1 = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=REAL_ACCOUNT_ID)
        if ret1 == RET_OK and data1 is not None and not data1.empty:
            row = data1.iloc[0]
            monitor_data['real_account']['total_assets'] = float(row.get('total_assets', 0))
            monitor_data['real_account']['market_value'] = float(row.get('market_val', 0))
            monitor_data['real_account']['cash_hk'] = float(row.get('hk_cash', 0))
            monitor_data['real_account']['cash_us'] = float(row.get('us_cash', 0))
            monitor_data['real_account']['buying_power'] = float(row.get('power', 0))

        # 获取持仓
        ret2, data2 = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=REAL_ACCOUNT_ID)
        positions = []
        if ret2 == RET_OK and data2 is not None and not data2.empty:
            for _, row in data2.iterrows():
                positions.append({
                    'code': row.get('code', ''),
                    'name': row.get('stock_name', ''),
                    'qty': int(row.get('qty', 0)),
                    'cost_price': float(row.get('cost_price', 0)),
                    'market_val': float(row.get('market_val', 0)),
                    'pl_ratio': float(row.get('pl_ratio', 0)) if row.get('pl_ratio_valid', False) else 0,
                    'pl_val': float(row.get('pl_val', 0)) if row.get('pl_val_valid', False) else 0
                })
        monitor_data['real_account']['positions'] = positions
        monitor_data['real_account']['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return True
    except Exception as e:
        print(f"[错误] 获取账户数据失败: {e}")
        return False
    finally:
        ctx.close()


@app.route('/')
def index():
    """主页"""
    update_system_stats()
    check_strategy_status()
    get_real_account_info()

    return render_template_string(
        HTML_TEMPLATE,
        data=monitor_data,
        now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        real_acc_id=REAL_ACCOUNT_ID
    )


@app.route('/api/status')
def api_status():
    """API状态"""
    update_system_stats()
    check_strategy_status()
    return jsonify(monitor_data)


@app.route('/api/account')
def api_account():
    """实盘账户API - 实时数据"""
    update_system_stats()
    success = get_real_account_info()
    return jsonify({
        'success': success,
        'account_id': REAL_ACCOUNT_ID,
        'data': monitor_data['real_account'],
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })


@app.route('/api/signals', methods=['POST'])
def update_signals():
    """更新信号状态 (由策略引擎调用)"""
    data = request.json
    if 'v4_strategy' in data:
        monitor_data['v4_strategy'].update(data['v4_strategy'])
    return jsonify({'status': 'ok'})


def main():
    """主函数"""
    print("=" * 70)
    print("连连数字V4双重确认策略 - 监控面板 (增强版)")
    print("=" * 70)
    print(f"访问地址: http://localhost:8081")
    print(f"实盘账户: {REAL_ACCOUNT_ID}")
    print(f"富途API: {'已连接' if FUTU_AVAILABLE else '未安装'}")
    print("按 Ctrl+C 停止")
    print("=" * 70)

    app.run(host='0.0.0.0', port=8081, debug=False)


if __name__ == '__main__':
    main()
