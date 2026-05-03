# -*- coding: utf-8 -*-
"""
影子模式 Paper Trading 框架
新策略在实盘环境中模拟运行，不执行真实交易
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import json
import time

# UTF-8编码设置
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

try:
    from futu import OpenQuoteContext, RET_OK, KLType, AuType
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    print("[WARN] Futu API not available, using simulation mode")

# 配置
FUTU_HOST = '127.0.0.1'
FUTU_PORT = 11111
PAPER_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司\03_实盘与监测\paper_trading")
PAPER_DIR.mkdir(parents=True, exist_ok=True)

class PaperTradingEngine:
    """影子模式交易引擎"""
    
    def __init__(self, strategy_name, initial_cash=100000):
        self.strategy_name = strategy_name
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions = {}  # {code: {'shares': int, 'avg_cost': float}}
        self.trade_log = []
        self.quote_ctx = None
        
        # Paper Trading 专用目录
        self.log_dir = PAPER_DIR / strategy_name
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
    def connect(self):
        """连接富途OpenD"""
        if FUTU_AVAILABLE:
            self.quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
            print(f"[OK] Connected to Futu OpenD for {self.strategy_name}")
        else:
            print(f"[WARN] No Futu connection, using simulation")
    
    def disconnect(self):
        """断开连接"""
        if self.quote_ctx:
            self.quote_ctx.close()
    
    def get_latest_price(self, code):
        """获取最新价格"""
        if not self.quote_ctx:
            return None
        
        ret_code, ret_msg, data = self.quote_ctx.get_market_snapshot([code])
        if ret_code == RET_OK and data is not None and len(data) > 0:
            return data.iloc[0]['last_price']
        return None
    
    def paper_buy(self, code, shares, price=None, reason=""):
        """模拟买入"""
        if price is None:
            price = self.get_latest_price(code)
        
        if price is None:
            print(f"[FAIL] Cannot get price for {code}")
            return False
        
        cost = shares * price
        if cost > self.cash:
            print(f"[FAIL] Insufficient cash: need ${cost:.2f}, have ${self.cash:.2f}")
            return False
        
        # 执行模拟买入
        self.cash -= cost
        if code in self.positions:
            old_shares = self.positions[code]['shares']
            old_cost = self.positions[code]['avg_cost']
            new_avg = (old_shares * old_cost + shares * price) / (old_shares + shares)
            self.positions[code] = {'shares': old_shares + shares, 'avg_cost': new_avg}
        else:
            self.positions[code] = {'shares': shares, 'avg_cost': price}
        
        # 记录交易
        trade = {
            'timestamp': datetime.now().isoformat(),
            'action': 'BUY',
            'code': code,
            'shares': shares,
            'price': price,
            'cost': cost,
            'reason': reason,
            'cash_after': self.cash
        }
        self.trade_log.append(trade)
        
        print(f"[PAPER BUY] {code} {shares} shares @ ${price:.2f} = ${cost:.2f}")
        print(f"  Reason: {reason}")
        return True
    
    def paper_sell(self, code, shares, price=None, reason=""):
        """模拟卖出"""
        if code not in self.positions:
            print(f"[FAIL] No position in {code}")
            return False
        
        if price is None:
            price = self.get_latest_price(code)
        
        if price is None:
            print(f"[FAIL] Cannot get price for {code}")
            return False
        
        current_shares = self.positions[code]['shares']
        if shares > current_shares:
            shares = current_shares  # 最多卖出持有数量
        
        revenue = shares * price
        self.cash += revenue
        
        # 更新持仓
        if shares == current_shares:
            del self.positions[code]
        else:
            self.positions[code]['shares'] = current_shares - shares
        
        # 记录交易
        trade = {
            'timestamp': datetime.now().isoformat(),
            'action': 'SELL',
            'code': code,
            'shares': shares,
            'price': price,
            'revenue': revenue,
            'reason': reason,
            'cash_after': self.cash
        }
        self.trade_log.append(trade)
        
        print(f"[PAPER SELL] {code} {shares} shares @ ${price:.2f} = ${revenue:.2f}")
        print(f"  Reason: {reason}")
        return True
    
    def get_portfolio_value(self):
        """计算组合总价值"""
        total = self.cash
        for code, pos in self.positions.items():
            price = self.get_latest_price(code)
            if price:
                total += pos['shares'] * price
        return total
    
    def get_pnl(self):
        """计算盈亏"""
        value = self.get_portfolio_value()
        pnl = value - self.initial_cash
        pnl_pct = (pnl / self.initial_cash) * 100
        return pnl, pnl_pct
    
    def save_report(self):
        """保存Paper Trading报告"""
        report = {
            'strategy': self.strategy_name,
            'timestamp': datetime.now().isoformat(),
            'initial_cash': self.initial_cash,
            'cash': self.cash,
            'positions': self.positions,
            'portfolio_value': self.get_portfolio_value(),
            'pnl': self.get_pnl(),
            'trade_count': len(self.trade_log),
            'trades': self.trade_log[-50:]  # 最近50条
        }
        
        report_file = self.log_dir / f"paper_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"[OK] Report saved: {report_file}")
        return report_file

def demo_paper_trading():
    """演示影子模式"""
    print("=" * 60)
    print("Paper Trading Framework Demo")
    print("=" * 60)
    
    engine = PaperTradingEngine("CLSK_Momentum_Test", initial_cash=50000)
    engine.connect()
    
    try:
        # 模拟交易
        engine.paper_buy("US.CLSK", 100, reason="突破20日均线")
        time.sleep(1)
        
        # 模拟卖出
        engine.paper_sell("US.CLSK", 50, reason="止盈测试")
        
        # 保存报告
        engine.save_report()
        
        # 显示盈亏
        pnl, pnl_pct = engine.get_pnl()
        print(f"\n[SUMMARY] P&L: ${pnl:.2f} ({pnl_pct:+.2f}%)")
        
    finally:
        engine.disconnect()

if __name__ == '__main__':
    demo_paper_trading()
