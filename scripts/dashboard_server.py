#!/usr/bin/env python3
"""
量化监控面板 v2.0 - 可在本地浏览器查看
端口: 8083（仅内网访问）
数据: 实时读取 data/dashboard/ 下的JSON + Futu API
"""
import json, os, sys
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, render_template_string

WORKSPACE = Path(__file__).parent.parent
app = Flask(__name__)

HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="10">
    <title>量化交易监控面板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
               background: #0a0e27; color: #e0e0e0; padding: 20px; }
        .header { background: linear-gradient(135deg, #667eea, #764ba2); 
                  padding: 20px; border-radius: 12px; margin-bottom: 20px; 
                  display: flex; justify-content: space-between; align-items: center; }
        .header h1 { font-size: 22px; color: #fff; }
        .header .time { font-size: 13px; color: rgba(255,255,255,0.7); }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 15px; }
        .card { background: #1a1f3a; border-radius: 12px; padding: 20px; border: 1px solid #2a3050; }
        .card h3 { color: #8892b0; font-size: 12px; text-transform: uppercase; 
                   letter-spacing: 1px; margin-bottom: 15px; display: flex; align-items: center; 
                   justify-content: space-between; }
        .row { display: flex; justify-content: space-between; padding: 8px 0; 
               border-bottom: 1px solid #1e2340; font-size: 14px; }
        .row:last-child { border-bottom: none; }
        .label { color: #8892b0; }
        .value { font-weight: 600; }
        .green { color: #00d084; }
        .red { color: #ff4757; }
        .yellow { color: #f39c12; }
        .blue { color: #667eea; }
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; 
                       margin-right: 6px; }
        .dot-ok { background: #00d084; }
        .dot-warn { background: #f39c12; }
        .dot-err { background: #ff4757; }
        .full-width { grid-column: 1 / -1; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="header">
        <h1>🦞 量化交易监控面板</h1>
        <span class="time" id="time"></span>
    </div>

    <div class="grid">
        <div class="card">
            <h3>📈 BTDR PrevClose V2</h3>
            <div class="row"><span class="label">状态</span>
                <span class="value"><span class="status-dot {{ 'dot-ok' if btdr.status == 'running' else 'dot-err' }}"></span>{{ '运行中' if btdr.status == 'running' else '已停止' }}</span></div>
            <div class="row"><span class="label">策略</span><span class="value blue">ATR×1.2/×0.4</span></div>
            <div class="row"><span class="label">价格</span><span class="value">${{ "%.2f"|format(btdr.price) }}</span></div>
            <div class="row"><span class="label">持仓</span><span class="value">{{ btdr.shares }} 股</span></div>
            <div class="row"><span class="label">累计P&L</span>
                <span class="value {{ 'green' if btdr.pnl >= 0 else 'red' }}">${{ "%+.0f"|format(btdr.pnl) }}</span></div>
            <div class="row"><span class="label">涡轮A</span>
                <span class="value {{ 'green' if btdr.turbo_a else 'yellow' }}">{{ '🟢 持有中' if btdr.turbo_a else '⚪ 待命' }}</span></div>
            <div class="row"><span class="label">涡轮B</span>
                <span class="value {{ 'green' if btdr.turbo_b else 'yellow' }}">{{ '🟢 持有中' if btdr.turbo_b else '⚪ 待命' }}</span></div>
        </div>

        <div class="card">
            <h3>📊 连连数字V4</h3>
            <div class="row"><span class="label">策略</span><span class="value blue">V3+MR·ATR×0.7</span></div>
            <div class="row"><span class="label">持仓</span><span class="value">{{ ll.shares }} 股 ({{ ll.stock_code }})</span></div>
            <div class="row"><span class="label">最新信号</span>
                <span class="value {{ 'green' if ll.signal == 'buy' else ('red' if ll.signal == 'sell' else '') }}">
                    {{ ll.signal|upper if ll.signal else '等待' }}</span></div>
            <div class="row"><span class="label">Z-Score</span><span class="value">{{ ll.zscore }}</span></div>
            <div class="row"><span class="label">V3</span>
                <span class="value {{ 'green' if ll.v3_buy else ('red' if ll.v3_sell else '') }}">
                    {{ '买入' if ll.v3_buy else ('卖出' if ll.v3_sell else '中性') }}</span></div>
            <div class="row"><span class="label">MR</span>
                <span class="value {{ 'green' if ll.mr_buy else ('red' if ll.mr_sell else '') }}">
                    {{ '买入' if ll.mr_buy else ('卖出' if ll.mr_sell else '中性') }}</span></div>
        </div>
    </div>

    <div class="card full-width">
        <h3>🔧 系统状态 <span id="health-icon"></span></h3>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px">
            <div class="row"><span class="label">OpenD</span>
                <span class="value"><span class="status-dot {{ 'dot-ok' if health.open_d.running else 'dot-err' }}"></span>{{ '运行中' if health.open_d.running else '已停止' }}</span></div>
            <div class="row"><span class="label">Gateway</span>
                <span class="value"><span class="status-dot {{ 'dot-ok' if health.gateway_active else 'dot-err' }}"></span>{{ '正常' if health.gateway_active else '异常' }}</span></div>
            <div class="row"><span class="label">磁盘</span><span class="value">{{ health.disk.available }}</span></div>
            <div class="row"><span class="label">内存</span><span class="value">{{ health.memory.available_mb }}MB 可用</span></div>
        </div>
    </div>

    <div style="text-align:center;color:#555;font-size:12px;margin-top:15px">
        数据每10秒刷新 · 仅供监控参考
    </div>

    <script>
        document.getElementById('time').textContent = new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
        setInterval(()=>{
            document.getElementById('time').textContent = new Date().toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
        },1000);
    </script>
</body>
</html>
'''

def load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}

@app.route("/")
def index():
    health = load_json(WORKSPACE / "data" / "dashboard" / "health_status.json")
    golden = load_json(WORKSPACE / "data" / "dashboard" / "golden_state.json")
    
    btdr = {
        "status": golden.get("strategy_status", "unknown"),
        "price": golden.get("current_price", 0),
        "shares": golden.get("btdr_shares", 0),
        "pnl": golden.get("btdr_pnl", 0),
        "turbo_a": golden.get("turbo_a_active", False),
        "turbo_b": golden.get("turbo_b_active", False),
    }
    ll = {
        "stock_code": golden.get("ll_stock_code", "HK.02598"),
        "shares": golden.get("ll_shares", 8000),
        "signal": golden.get("ll_signal", ""),
        "zscore": golden.get("ll_zscore", ""),
        "v3_buy": golden.get("ll_v3_buy", False),
        "v3_sell": golden.get("ll_v3_sell", False),
        "mr_buy": golden.get("ll_mr_buy", False),
        "mr_sell": golden.get("ll_mr_sell", False),
    }
    
    return render_template_string(HTML, btdr=btdr, ll=ll, health=health)

@app.route("/api/status")
def api():
    return jsonify({
        "health": load_json(WORKSPACE / "data" / "dashboard" / "health_status.json"),
        "golden": load_json(WORKSPACE / "data" / "dashboard" / "golden_state.json"),
        "time": datetime.now().isoformat()
    })

if __name__ == "__main__":
    print(f"监控面板: http://0.0.0.0:8083")
    print(f"API接口: http://0.0.0.0:8083/api/status")
    app.run(host="0.0.0.0", port=8083, debug=False, threaded=True)
