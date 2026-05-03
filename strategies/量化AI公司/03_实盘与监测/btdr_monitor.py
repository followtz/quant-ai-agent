# -*- coding: utf-8 -*-
"""
BTDR PrevClose V2 - 实时监控面板
端口: 8080
数据来源: C:/Trading/data/prev_close_v2_state.json
"""
import json, time
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template_string, jsonify
import psutil

app = Flask(__name__)

STATE_FILE = Path(r"C:/Trading/data/prev_close_v2_state.json")
LOG_FILE   = Path(r"C:/Trading/logs/prev_close_v2_20260414.log")

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="5">
    <title>BTDR PrevClose V2 - 监控面板</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0a0e27; color: #fff; padding: 20px; }
        .header { text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 15px; margin-bottom: 20px; }
        .card { background: #1a1f3a; border-radius: 10px; padding: 20px; border: 1px solid #2a3050; }
        .card h3 { color: #8892b0; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 15px; }
        .row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #2a3050; }
        .row:last-child { border-bottom: none; }
        .label { color: #8892b0; }
        .value { font-weight: bold; font-size: 16px; }
        .ok { color: #00d084; }
        .warn { color: #f39c12; }
        .alert { color: #ff4757; }
        .signal { display: inline-block; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
        .signal-ok { background: #00d084; color: #000; }
        .signal-wait { background: #2a3050; color: #8892b0; }
        .footer { text-align: center; color: #8892b0; font-size: 12px; margin-top: 20px; }
        .refresh { text-align: center; color: #8892b0; font-size: 12px; margin-bottom: 15px; }
        .price-box { text-align: center; font-size: 32px; font-weight: bold; color: #667eea; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="header">
        <h1>BTDR PrevClose V2</h1>
        <div>涡轮A + 涡轮B 协同 PrevClose 策略</div>
    </div>
    <div class="refresh">页面每5秒自动刷新 | 更新时间: {{ now }}</div>

    <div class="grid">
        <div class="card">
            <h3>策略状态</h3>
            <div class="row"><span class="label">策略</span><span class="value">PrevClose V2</span></div>
            <div class="row"><span class="label">状态</span><span class="value {{ 'ok' if data.status == 'running' else 'alert' }}">{{ '运行中' if data.status == 'running' else '已停止' }}</span></div>
            <div class="row"><span class="label">持仓</span><span class="value ok">{{ data.shares }} 股</span></div>
            <div class="row"><span class="label">昨收</span><span class="value">${{ "%.4f"|format(data.last_close) }}</span></div>
            <div class="row"><span class="label">当前价</span><span class="value">{{ '$%.4f'|format(data.cur_price) if data.cur_price else 'N/A' }}</span></div>
        </div>

        <div class="card">
            <h3>涡轮A状态</h3>
            <div class="row"><span class="label">状态</span>
                <span class="signal {{ 'signal-ok' if data.turbo_A.active else 'signal-wait' }}">
                    {{ '已卖出持仓中' if data.turbo_A.active else '待命' }}
                </span>
            </div>
            <div class="row"><span class="label">卖出触发</span><span class="value warn">${{ "%.4f"|format(data.sell_trigger) }}</span></div>
            <div class="row"><span class="label">买回目标</span><span class="value">${{ "%.4f"|format(data.buyback_target) if data.turbo_A.active else '待命中' }}</span></div>
            <div class="row"><span class="label">卖出价</span><span class="value">{{ '$%.4f'|format(data.turbo_A.entry_price) if data.turbo_A.active else '-' }}</span></div>
        </div>

        <div class="card">
            <h3>涡轮B状态</h3>
            <div class="row"><span class="label">状态</span>
                <span class="signal {{ 'signal-ok' if data.turbo_B.active else 'signal-wait' }}">
                    {{ '已买入选持中' if data.turbo_B.active else '待命' }}
                </span>
            </div>
            <div class="row"><span class="label">买入触发</span><span class="value warn">${{ "%.4f"|format(data.buy_trigger) }}</span></div>
            <div class="row"><span class="label">卖出目标</span><span class="value">${{ "%.4f"|format(data.sellback_target) if data.turbo_B.active else '待命中' }}</span></div>
            <div class="row"><span class="label">买入价</span><span class="value">{{ '$%.4f'|format(data.turbo_B.entry_price) if data.turbo_B.active else '-' }}</span></div>
        </div>

        <div class="card">
            <h3>盈亏统计</h3>
            <div class="row"><span class="label">今日盈亏</span><span class="value {{ 'ok' if data.today_pnl >= 0 else 'alert' }}">${{ "%+.2f"|format(data.today_pnl) }}</span></div>
            <div class="row"><span class="label">累计盈亏</span><span class="value {{ 'ok' if data.total_pnl >= 0 else 'alert' }}">${{ "%+.2f"|format(data.total_pnl) }}</span></div>
            <div class="row"><span class="label">今日交易</span><span class="value">{{ data.today_trades }} 笔</span></div>
            <div class="row"><span class="label">累计交易</span><span class="value">{{ data.total_trades }} 笔</span></div>
        </div>
    </div>

    <div class="card">
        <h3>关键价位</h3>
        <div class="row"><span class="label">A卖出触发价</span><span class="value warn">${{ "%.4f"|format(data.sell_trigger) }} (+12%)</span></div>
        <div class="row"><span class="label">A买回目标</span><span class="value ok">${{ "%.4f"|format(data.buyback_target) }} (-1%)</span></div>
        <div class="row"><span class="label">B买入触发价</span><span class="value warn">${{ "%.4f"|format(data.buy_trigger) }} (-5%)</span></div>
        <div class="row"><span class="label">B卖出目标</span><span class="value ok">${{ "%.4f"|format(data.sellback_target) }} (+5%)</span></div>
    </div>

    <div class="footer">
        <p>BTDR PrevClose V2 策略监控面板 | 数据来源: prev_close_v2_state.json</p>
        <p>数据仅供参考，投资有风险</p>
    </div>
</body>
</html>
'''

def load_state():
    """加载引擎状态"""
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        price = state.get("last_close", 11.245)
        return {
            "status": "running",
            "shares": state.get("shares", 8894),
            "last_close": state.get("last_close", 11.245),
            "cur_price": price,
            "today_pnl": state.get("pnl", 0),
            "total_pnl": state.get("total_pnl", 0),
            "today_trades": state.get("trades", 0),
            "total_trades": state.get("total_trades", 0),
            "turbo_A": state.get("turbo_A", {}),
            "turbo_B": state.get("turbo_B", {}),
            "sell_trigger": state.get("last_close", 11.245) * 1.12,
            "buyback_target": state.get("last_close", 11.245) * 0.99,
            "buy_trigger": state.get("last_close", 11.245) * 0.95,
            "sellback_target": state.get("last_close", 11.245) * 1.05,
        }
    except:
        return {
            "status": "stopped", "shares": 0, "last_close": 0,
            "cur_price": 0, "today_pnl": 0, "total_pnl": 0,
            "today_trades": 0, "total_trades": 0,
            "turbo_A": {"active": False, "entry_price": 0},
            "turbo_B": {"active": False, "entry_price": 0},
            "sell_trigger": 0, "buyback_target": 0,
            "buy_trigger": 0, "sellback_target": 0,
        }

@app.route("/")
def index():
    data = load_state()
    return render_template_string(HTML, data=data, now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

@app.route("/api/status")
def api_status():
    return jsonify(load_state())

if __name__ == "__main__":
    print("=" * 60)
    print("BTDR PrevClose V2 - 监控面板")
    print("访问地址: http://localhost:8080")
    print("按 Ctrl+C 停止")
    print("=" * 60)
    app.run(host="0.0.0.0", port=8080, debug=False, threaded=True)
