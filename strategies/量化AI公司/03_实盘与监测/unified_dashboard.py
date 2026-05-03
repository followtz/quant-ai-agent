# -*- coding: utf-8 -*-
"""
龙虾量化交易 - 统一监控面板 v1.0
整合: BTDR PrevClose V2 + 连连数字V4双重确认
端口: 8082 (替代原有的8080和8081)

功能:
- 双策略实时监控
- 持仓/盈亏/信号状态
- Token消耗监控
- 系统资源监控
- 交易日志实时显示
"""
import json
import time
import psutil
from datetime import datetime, date
from pathlib import Path
from flask import Flask, render_template_string, jsonify
import threading

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

# ========== 配置文件路径 ==========
BTDR_STATE_FILE = Path(r"C:/Trading/data/prev_close_v2_state.json")
BTDR_LOG_DIR = Path(r"C:/Trading/logs")
LL_STATE_FILE = Path(r"C:/Trading/data/lianlian_v4_state.json")
LL_LOG_DIR = Path(r"C:/Trading/data")

# 实盘账户配置
REAL_ACCOUNT_ID = 281756477947279377

# ========== 全局监控数据 ==========
dashboard_data = {
    'timestamp': None,
    'btdr': {
        'name': 'BTDR PrevClose V2',
        'market': '美股',
        'code': 'US.BTDR',
        'status': 'stopped',
        'pid': None,
        'shares': 8894,
        'last_close': 11.245,
        'cur_price': None,
        'today_pnl': 0,
        'total_pnl': 0,
        'today_trades': 0,
        'total_trades': 0,
        'turbo_A': {'active': False, 'entry_price': 0, 'pending_qty': 0, 'days_held': 0},
        'turbo_B': {'active': False, 'entry_price': 0, 'pending_qty': 0, 'days_held': 0},
        'signals': {'btc': '稳', 'volatility': '中', 'day': 'Other', 'session': '盘中'},
        'aggression': 1.0,
        'sell_trigger': 12.59,
        'buyback_target': 11.13,
        'buy_trigger': 10.68,
        'sellback_target': 11.81,
    },
    'lianlian': {
        'name': '连连数字V4双重确认',
        'market': '港股',
        'code': 'HK.02598',
        'status': 'stopped',
        'pid': None,
        'position': 8000,
        'cost_price': 0,
        'cash': 100000,
        'total_assets': 0,
        'market_value': 0,
        'today_trades': 0,
        'total_trades': 0,
        'signals': {'v3': False, 'mean_reversion': False, 'ml': False},
        'last_signal': None,
        'v3_threshold': 0.05,
        'mr_threshold': 2.0,
        'ml_confidence': 0.5,
    },
    'system': {
        'cpu_percent': 0,
        'memory_percent': 0,
        'disk_percent': 0,
        'token_used': 0,  # 万
        'token_remaining': 100,  # %
    },
    'logs': []
}

# ========== 数据更新函数 ==========
def _get_process_pid(process_name):
    """获取进程PID"""
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = ' '.join(proc.info['cmdline'] or [])
            if process_name in cmdline:
                return proc.info['pid']
        except:
            pass
    return None

def _load_btdr_state():
    """加载BTDR策略状态"""
    try:
        if BTDR_STATE_FILE.exists():
            state = json.loads(BTDR_STATE_FILE.read_text(encoding="utf-8"))
            dashboard_data['btdr'].update({
                'shares': state.get('shares', 8894),
                'last_close': state.get('last_close', 11.245),
                'today_pnl': state.get('pnl', 0),
                'total_pnl': state.get('total_pnl', 0),
                'today_trades': state.get('trades', 0),
                'total_trades': state.get('total_trades', 0),
                'turbo_A': state.get('turbo_A', {'active': False}),
                'turbo_B': state.get('turbo_B', {'active': False}),
            })
            # 计算触发价位
            lc = state.get('last_close', 11.245)
            dashboard_data['btdr']['sell_trigger'] = lc * 1.12
            dashboard_data['btdr']['buyback_target'] = lc * 0.99
            dashboard_data['btdr']['buy_trigger'] = lc * 0.95
            dashboard_data['btdr']['sellback_target'] = lc * 1.05
    except Exception as e:
        print(f"[ERROR] 加载BTDR状态失败: {e}")

def _get_real_account_info():
    """从富途API获取实盘账户数据（账户资金 + 所有持仓）"""
    if not FUTU_AVAILABLE:
        return
    
    ctx = OpenSecTradeContext(host='127.0.0.1', port=11111)
    try:
        # ---- 账户资金 ----
        ret1, data1 = ctx.accinfo_query(trd_env=TrdEnv.REAL, acc_id=REAL_ACCOUNT_ID)
        if ret1 == RET_OK and data1 is not None and not data1.empty:
            row = data1.iloc[0]
            dashboard_data['lianlian']['cash'] = float(row.get('hk_cash', 0))
            dashboard_data['lianlian']['total_assets'] = float(row.get('total_assets', 0))
        
        # ---- 所有持仓（一次查出，同时更新 BTDR 和连连） ----
        ret2, data2 = ctx.position_list_query(trd_env=TrdEnv.REAL, acc_id=REAL_ACCOUNT_ID)
        if ret2 == RET_OK and data2 is not None and not data2.empty:
            for _, row in data2.iterrows():
                code = str(row.get('code', ''))
                qty          = int(float(row.get('qty', 0)))
                cost_price   = float(row.get('cost_price', 0))
                market_price = float(row.get('nominal_price', 0))   # 市价用 nominal_price
                market_val   = float(row.get('market_val', 0))
                pl_ratio     = float(row.get('pl_ratio', 0))          # 浮亏比例 %

                if 'BTDR' in code:
                    # BTDR 持仓 → 更新 dashboard_data['btdr']
                    dashboard_data['btdr']['shares']      = qty
                    dashboard_data['btdr']['cur_price']   = market_price
                    dashboard_data['btdr']['total_pnl']  = round(market_val * pl_ratio / 100, 2) if market_val else 0

                elif '02598' in code:
                    # 连连数字
                    dashboard_data['lianlian']['position']    = qty
                    dashboard_data['lianlian']['cost_price']  = cost_price
                    dashboard_data['lianlian']['market_value'] = market_val

                elif '09611' in code:
                    # 09611（其他持仓，汇总到连连显示区）
                    dashboard_data['lianlian']['market_value'] += market_val

    except Exception as e:
        print(f"[ERROR] 获取实盘账户数据失败: {e}")
    finally:
        ctx.close()

def _load_lianlian_state():
    """加载连连数字策略状态 - 优先使用富途API实时数据"""
    # 先尝试从富途API获取实时数据
    _get_real_account_info()
    
    # 如果状态文件存在，补充其他信息（如信号状态、交易次数）
    try:
        if LL_STATE_FILE.exists():
            state = json.loads(LL_STATE_FILE.read_text(encoding="utf-8"))
            # 只更新交易统计数据，持仓和现金使用实时API数据
            dashboard_data['lianlian'].update({
                'today_trades': state.get('today_trades', 0),
                'total_trades': state.get('total_trades', 0),
                'signals': state.get('signals', {'v3': False, 'mean_reversion': False, 'ml': False}),
            })
    except Exception as e:
        print(f"[ERROR] 加载连连状态失败: {e}")

def _update_system_stats():
    """更新系统状态"""
    dashboard_data['system']['cpu_percent'] = psutil.cpu_percent()
    dashboard_data['system']['memory_percent'] = psutil.virtual_memory().percent
    dashboard_data['system']['disk_percent'] = psutil.disk_usage('/').percent

def _check_process_status():
    """检查策略进程状态"""
    # BTDR引擎
    btdr_pid = _get_process_pid('prev_close_v2_engine.py')
    dashboard_data['btdr']['status'] = 'running' if btdr_pid else 'stopped'
    dashboard_data['btdr']['pid'] = btdr_pid
    
    # 连连引擎
    ll_pid = _get_process_pid('v4_live_engine.py')
    dashboard_data['lianlian']['status'] = 'running' if ll_pid else 'stopped'
    dashboard_data['lianlian']['pid'] = ll_pid

def _read_latest_logs():
    """读取最新日志"""
    logs = []
    today = date.today().strftime('%Y%m%d')
    
    # BTDR日志
    btdr_log = BTDR_LOG_DIR / f"prev_close_v2_{today}.log"
    if btdr_log.exists():
        try:
            lines = btdr_log.read_text(encoding='utf-8').strip().split('\n')
            for line in lines[-10:]:
                logs.append({'time': line[1:9] if line.startswith('[') else '', 'source': 'BTDR', 'msg': line})
        except:
            pass
    
    dashboard_data['logs'] = logs[-20:]  # 保留最近20条

def update_all_data():
    """更新所有数据"""
    _update_system_stats()
    _check_process_status()
    _load_btdr_state()
    _load_lianlian_state()
    _read_latest_logs()
    dashboard_data['timestamp'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ========== HTML模板 ==========
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>龙虾量化交易 - 统一监控面板</title>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="300">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0a0e27;
            color: #fff;
            padding: 20px;
            min-height: 100vh;
        }
        
        /* 头部 */
        .header {
            text-align: center;
            padding: 25px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            border-radius: 15px;
            margin-bottom: 20px;
            box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
        }
        .header h1 { font-size: 32px; margin-bottom: 8px; }
        .header .subtitle { opacity: 0.9; font-size: 14px; }
        .header .timestamp { 
            margin-top: 10px; 
            font-size: 12px; 
            opacity: 0.7;
            background: rgba(0,0,0,0.2);
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
        }
        
        /* 网格布局 */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        
        /* 卡片 */
        .card {
            background: #1a1f3a;
            border-radius: 12px;
            padding: 20px;
            border: 1px solid #2a3050;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0,0,0,0.3);
        }
        .card h2 {
            font-size: 16px;
            color: #8892b0;
            margin-bottom: 15px;
            text-transform: uppercase;
            letter-spacing: 1px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .card h2 .icon { font-size: 18px; }
        
        /* 状态徽章 */
        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: bold;
        }
        .status-running { background: #00d084; color: #000; }
        .status-stopped { background: #ff4757; color: #fff; }
        .status-dot { width: 8px; height: 8px; border-radius: 50%; }
        .status-running .status-dot { background: #000; animation: pulse 2s infinite; }
        .status-stopped .status-dot { background: #fff; }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        /* 指标行 */
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #2a3050;
        }
        .metric:last-child { border-bottom: none; }
        .metric-label { color: #8892b0; font-size: 14px; }
        .metric-value { font-weight: bold; font-size: 16px; }
        .positive { color: #00d084; }
        .negative { color: #ff4757; }
        .neutral { color: #667eea; }
        
        /* 策略卡片特殊样式 */
        .strategy-card { border-left: 4px solid; }
        .strategy-btdr { border-left-color: #667eea; }
        .strategy-ll { border-left-color: #00d084; }
        
        .strategy-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 1px solid #2a3050;
        }
        .strategy-title { font-size: 18px; font-weight: bold; }
        .strategy-code { 
            font-size: 12px; 
            color: #8892b0; 
            background: #0a0e27;
            padding: 2px 8px;
            border-radius: 4px;
        }
        
        /* 信号网格 */
        .signal-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-top: 10px;
        }
        .signal-box {
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            transition: all 0.2s;
        }
        .signal-box.active {
            background: linear-gradient(135deg, #00d084 0%, #00b894 100%);
            color: #000;
        }
        .signal-box.inactive {
            background: #2a3050;
            color: #8892b0;
        }
        .signal-name { font-size: 11px; margin-bottom: 4px; text-transform: uppercase; }
        .signal-status { font-weight: bold; font-size: 13px; }
        
        /* 涡轮状态 */
        .turbo-row {
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }
        .turbo-box {
            flex: 1;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
            background: #2a3050;
        }
        .turbo-box.active {
            background: linear-gradient(135deg, #f39c12 0%, #e67e22 100%);
            color: #000;
        }
        .turbo-label { font-size: 11px; margin-bottom: 4px; }
        .turbo-status { font-weight: bold; font-size: 13px; }
        
        /* 价格标签 */
        .price-tag {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: bold;
        }
        .price-sell { background: rgba(255, 71, 87, 0.2); color: #ff4757; }
        .price-buy { background: rgba(0, 208, 132, 0.2); color: #00d084; }
        
        /* 系统状态条 */
        .system-bar {
            display: flex;
            gap: 20px;
            justify-content: center;
            flex-wrap: wrap;
        }
        .system-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
        }
        .system-item .label { color: #8892b0; }
        .system-item .value { font-weight: bold; }
        
        /* 进度条 */
        .progress-bar {
            width: 100%;
            height: 6px;
            background: #2a3050;
            border-radius: 3px;
            overflow: hidden;
            margin-top: 8px;
        }
        .progress-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s;
        }
        .progress-green { background: #00d084; }
        .progress-yellow { background: #f39c12; }
        .progress-red { background: #ff4757; }
        
        /* 日志区域 */
        .log-container {
            max-height: 300px;
            overflow-y: auto;
            background: #0a0e27;
            border-radius: 8px;
            padding: 15px;
            font-family: 'Consolas', monospace;
            font-size: 12px;
        }
        .log-entry {
            padding: 4px 0;
            border-bottom: 1px solid #1a1f3a;
            display: flex;
            gap: 10px;
        }
        .log-time { color: #667eea; min-width: 70px; }
        .log-source { 
            min-width: 60px; 
            padding: 1px 6px; 
            border-radius: 4px; 
            font-size: 10px;
            text-align: center;
        }
        .log-btdr { background: rgba(102, 126, 234, 0.2); color: #667eea; }
        .log-ll { background: rgba(0, 208, 132, 0.2); color: #00d084; }
        .log-msg { color: #ccc; flex: 1; }
        
        /* 底部 */
        .footer {
            text-align: center;
            margin-top: 30px;
            padding: 20px;
            color: #8892b0;
            font-size: 12px;
            border-top: 1px solid #2a3050;
        }
        
        /* 响应式 */
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .signal-grid { grid-template-columns: 1fr; }
            .turbo-row { flex-direction: column; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🦞 龙虾量化交易</h1>
        <div class="subtitle">统一监控面板 | BTDR PrevClose V2 + 连连数字V4双重确认</div>
        <div class="timestamp">🕐 更新时间: {{ data.timestamp }}</div>
    </div>
    
    <!-- 系统状态 -->
    <div class="card">
        <h2><span class="icon">💻</span>系统状态</h2>
        <div class="system-bar">
            <div class="system-item">
                <span class="label">CPU</span>
                <span class="value {{ 'positive' if data.system.cpu_percent < 50 else 'negative' }}">{{ "%.1f"|format(data.system.cpu_percent) }}%</span>
            </div>
            <div class="system-item">
                <span class="label">内存</span>
                <span class="value {{ 'positive' if data.system.memory_percent < 70 else 'negative' }}">{{ "%.1f"|format(data.system.memory_percent) }}%</span>
            </div>
            <div class="system-item">
                <span class="label">磁盘</span>
                <span class="value">{{ "%.1f"|format(data.system.disk_percent) }}%</span>
            </div>
            <div class="system-item">
                <span class="label">Token已用</span>
                <span class="value {{ 'positive' if data.system.token_used < 3500 else 'negative' }}">{{ "%.0f"|format(data.system.token_used) }}万</span>
            </div>
            <div class="system-item">
                <span class="label">Token剩余</span>
                <span class="value {{ 'positive' if data.system.token_remaining > 20 else 'negative' }}">{{ "%.0f"|format(data.system.token_remaining) }}%</span>
            </div>
        </div>
        <div class="progress-bar">
            <div class="progress-fill {{ 'progress-green' if data.system.token_remaining > 30 else 'progress-yellow' if data.system.token_remaining > 15 else 'progress-red' }}" 
                 style="width: {{ data.system.token_remaining }}%"></div>
        </div>
    </div>
    
    <div class="grid">
        <!-- BTDR策略 -->
        <div class="card strategy-card strategy-btdr">
            <div class="strategy-header">
                <div>
                    <div class="strategy-title">{{ data.btdr.name }}</div>
                    <div style="font-size: 12px; color: #8892b0; margin-top: 4px;">{{ data.btdr.market }} | 涡轮A+B协同</div>
                </div>
                <span class="status-badge status-{{ 'running' if data.btdr.status == 'running' else 'stopped' }}">
                    <span class="status-dot"></span>
                    {{ '运行中' if data.btdr.status == 'running' else '已停止' }}
                </span>
            </div>
            
            <div class="metric">
                <span class="metric-label">股票代码</span>
                <span class="strategy-code">{{ data.btdr.code }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">当前持仓</span>
                <span class="metric-value neutral">{{ data.btdr.shares }} 股</span>
            </div>
            <div class="metric">
                <span class="metric-label">昨日收盘价</span>
                <span class="metric-value">${{ "%.4f"|format(data.btdr.last_close) }}</span>
            </div>
            
            <div style="margin: 15px 0; padding: 15px; background: #0a0e27; border-radius: 8px;">
                <div style="font-size: 12px; color: #8892b0; margin-bottom: 10px;">关键价位</div>
                <div style="display: flex; flex-wrap: wrap; gap: 8px;">
                    <span class="price-tag price-sell">A卖出 ${{ "%.2f"|format(data.btdr.sell_trigger) }}</span>
                    <span class="price-tag price-buy">A买回 ${{ "%.2f"|format(data.btdr.buyback_target) }}</span>
                    <span class="price-tag price-buy">B买入 ${{ "%.2f"|format(data.btdr.buy_trigger) }}</span>
                    <span class="price-tag price-sell">B卖出 ${{ "%.2f"|format(data.btdr.sellback_target) }}</span>
                </div>
            </div>
            
            <div class="turbo-row">
                <div class="turbo-box {{ 'active' if data.btdr.turbo_A.active }}">
                    <div class="turbo-label">涡轮A</div>
                    <div class="turbo-status">{{ '持仓中' if data.btdr.turbo_A.active else '待命' }}</div>
                </div>
                <div class="turbo-box {{ 'active' if data.btdr.turbo_B.active }}">
                    <div class="turbo-label">涡轮B</div>
                    <div class="turbo-status">{{ '持仓中' if data.btdr.turbo_B.active else '待命' }}</div>
                </div>
            </div>
            
            <div class="metric" style="margin-top: 15px;">
                <span class="metric-label">今日盈亏</span>
                <span class="metric-value {{ 'positive' if data.btdr.today_pnl >= 0 else 'negative' }}">${{ "%+.2f"|format(data.btdr.today_pnl) }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">累计盈亏</span>
                <span class="metric-value {{ 'positive' if data.btdr.total_pnl >= 0 else 'negative' }}">${{ "%+.2f"|format(data.btdr.total_pnl) }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">今日交易</span>
                <span class="metric-value">{{ data.btdr.today_trades }} 笔</span>
            </div>
        </div>
        
        <!-- 连连数字策略 -->
        <div class="card strategy-card strategy-ll">
            <div class="strategy-header">
                <div>
                    <div class="strategy-title">{{ data.lianlian.name }}</div>
                    <div style="font-size: 12px; color: #8892b0; margin-top: 4px;">{{ data.lianlian.market }} | 双重确认机制</div>
                </div>
                <span class="status-badge status-{{ 'running' if data.lianlian.status == 'running' else 'stopped' }}">
                    <span class="status-dot"></span>
                    {{ '运行中' if data.lianlian.status == 'running' else '已停止' }}
                </span>
            </div>
            
            <!-- 实盘账户标识 -->
            <div style="margin-bottom: 15px; padding: 10px; background: linear-gradient(135deg, rgba(0,208,132,0.1) 0%, rgba(0,184,148,0.1) 100%); border-radius: 8px; border: 1px solid rgba(0,208,132,0.3);">
                <div style="font-size: 12px; color: #00d084; font-weight: bold;">💰 实盘账户数据（富途API实时）</div>
            </div>
            
            <div class="metric">
                <span class="metric-label">股票代码</span>
                <span class="strategy-code">{{ data.lianlian.code }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">当前持仓</span>
                <span class="metric-value neutral">{{ data.lianlian.position }} 股</span>
            </div>
            <div class="metric">
                <span class="metric-label">成本价</span>
                <span class="metric-value">HKD {{ "%.3f"|format(data.lianlian.cost_price) }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">可用现金</span>
                <span class="metric-value">HKD {{ "%.2f"|format(data.lianlian.cash) }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">持仓市值</span>
                <span class="metric-value">HKD {{ "%.2f"|format(data.lianlian.market_value) }}</span>
            </div>
            <div class="metric">
                <span class="metric-label">总资产</span>
                <span class="metric-value" style="color: #00d084;">HKD {{ "%.2f"|format(data.lianlian.total_assets) }}</span>
            </div>
            
            <div style="margin: 15px 0;">
                <div style="font-size: 12px; color: #8892b0; margin-bottom: 10px;">实时信号 (需2个确认才交易)</div>
                <div class="signal-grid">
                    <div class="signal-box {{ 'active' if data.lianlian.signals.v3 else 'inactive' }}">
                        <div class="signal-name">V3涡轮</div>
                        <div class="signal-status">{{ '触发' if data.lianlian.signals.v3 else '未触发' }}</div>
                    </div>
                    <div class="signal-box {{ 'active' if data.lianlian.signals.mean_reversion else 'inactive' }}">
                        <div class="signal-name">均值回归</div>
                        <div class="signal-status">{{ '触发' if data.lianlian.signals.mean_reversion else '未触发' }}</div>
                    </div>
                    <div class="signal-box {{ 'active' if data.lianlian.signals.ml else 'inactive' }}">
                        <div class="signal-name">ML预测</div>
                        <div class="signal-status">{{ '触发' if data.lianlian.signals.ml else '未触发' }}</div>
                    </div>
                </div>
            </div>
            
            <div class="metric" style="margin-top: 15px;">
                <span class="metric-label">今日交易</span>
                <span class="metric-value">{{ data.lianlian.today_trades }} 笔</span>
            </div>
            <div class="metric">
                <span class="metric-label">累计交易</span>
                <span class="metric-value">{{ data.lianlian.total_trades }} 笔</span>
            </div>
            <div class="metric">
                <span class="metric-label">日交易上限</span>
                <span class="metric-value">2 笔</span>
            </div>
        </div>
    </div>
    
    <!-- 实时日志 -->
    <div class="card">
        <h2><span class="icon">📋</span>实时日志</h2>
        <div class="log-container">
            {% if data.logs %}
                {% for log in data.logs %}
                <div class="log-entry">
                    <span class="log-time">{{ log.time }}</span>
                    <span class="log-source log-{{ 'btdr' if log.source == 'BTDR' else 'll' }}">{{ log.source }}</span>
                    <span class="log-msg">{{ log.msg }}</span>
                </div>
                {% endfor %}
            {% else %}
                <div style="color: #8892b0; text-align: center; padding: 20px;">暂无日志数据</div>
            {% endif %}
        </div>
    </div>
    
    <div class="footer">
        <p>龙虾量化交易统一监控面板 v1.0 | 端口: 8082</p>
        <p>BTDR PrevClose V2 (美股) + 连连数字V4双重确认 (港股)</p>
        <p style="margin-top: 8px; opacity: 0.7;">数据仅供参考，投资有风险</p>
    </div>
</body>
</html>
'''

# ========== 路由 ==========
@app.route('/')
def index():
    """主页"""
    update_all_data()
    return render_template_string(HTML_TEMPLATE, data=dashboard_data)

@app.route('/api/status')
def api_status():
    """API状态"""
    update_all_data()
    return jsonify(dashboard_data)

@app.route('/api/btdr')
def api_btdr():
    """BTDR策略API"""
    _load_btdr_state()
    _check_process_status()
    return jsonify(dashboard_data['btdr'])

@app.route('/api/lianlian')
def api_lianlian():
    """连连数字策略API"""
    _load_lianlian_state()
    _check_process_status()
    return jsonify(dashboard_data['lianlian'])

# ========== 主函数 ==========
def main():
    """主函数"""
    print("=" * 70)
    print("[龙虾量化交易] 统一监控面板 v1.0")
    print("=" * 70)
    print("整合策略:")
    print("  [1] BTDR PrevClose V2 (美股) - 原端口8080")
    print("  [2] 连连数字V4双重确认 (港股) - 原端口8081")
    print("-" * 70)
    print("访问地址: http://localhost:8082")
    print("API端点:")
    print("  /api/status - 完整状态")
    print("  /api/btdr - BTDR策略状态")
    print("  /api/lianlian - 连连数字策略状态")
    print("=" * 70)
    print("按 Ctrl+C 停止")
    print("=" * 70)
    
    app.run(host='0.0.0.0', port=8082, debug=False, threaded=True)

if __name__ == '__main__':
    main()
