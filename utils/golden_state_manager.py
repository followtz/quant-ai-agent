# -*- coding: utf-8 -*-
"""
黄金状态变量同步模块
从富途API桥接数据，同步更新golden_state.json
"""
import os
import json
import datetime
from typing import Dict, Optional

WORKSPACE = '/home/ubuntu/.openclaw/workspace'


class GoldenStateManager:
    """黄金状态变量管理器"""
    
    def __init__(self):
        self.golden_path = os.path.join(WORKSPACE, 'data', 'dashboard', 'golden_state.json')
        self.data = self._load()
    
    def _load(self) -> dict:
        """加载黄金状态"""
        if os.path.exists(self.golden_path):
            with open(self.golden_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return self._init_default()
    
    def _init_default(self) -> dict:
        """初始化默认状态"""
        return {
            "timestamp": datetime.datetime.now().isoformat(),
            "Current_Position": {},
            "Today_PNL": {
                "realized": 0,
                "unrealized": None,
                "total": None
            },
            "Strategy_Version": {
                "BTDR_PrevClose": "V2",
                "LianLian_V4": "V4"
            },
            "Strategy_Status": {
                "BTDR_PrevClose": "ACTIVE",
                "LianLian_V4": "ACTIVE"
            },
            "Account_Info": {
                "total_asset": None,
                "available_cash": None,
                "margin_used": None
            },
            "Risk_Status": {
                "daily_loss_rate": None,
                "max_drawdown": None,
                "circuit_breaker": "NORMAL"
            },
            "Token_Status": {
                "daily_used": None,
                "remaining": None,
                "usage_rate": None
            }
        }
    
    def _save(self):
        """保存黄金状态"""
        self.data['timestamp'] = datetime.datetime.now().isoformat()
        os.makedirs(os.path.dirname(self.golden_path), exist_ok=True)
        with open(self.golden_path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def update_position(self, symbol: str, shares: Optional[int], avg_cost: Optional[float], 
                        current_price: Optional[float] = None):
        """
        更新持仓信息
        Args:
            symbol: 股票代码
            shares: 持股数
            avg_cost: 平均成本
            current_price: 当前价格
        """
        if symbol not in self.data['Current_Position']:
            self.data['Current_Position'][symbol] = {}
        
        self.data['Current_Position'][symbol].update({
            'shares': shares,
            'avg_cost': avg_cost,
            'current_price': current_price
        })
        
        # 计算未实现盈亏
        if shares and avg_cost and current_price:
            unrealized = (current_price - avg_cost) * shares
            self.data['Current_Position'][symbol]['unrealized_pnl'] = unrealized
        
        self._save()
    
    def update_pnl(self, realized: float = None, unrealized: float = None):
        """
        更新盈亏信息
        Args:
            realized: 已实现盈亏
            unrealized: 未实现盈亏
        """
        if realized is not None:
            self.data['Today_PNL']['realized'] = realized
        if unrealized is not None:
            self.data['Today_PNL']['unrealized'] = unrealized
        
        # 计算总盈亏
        r = self.data['Today_PNL']['realized'] or 0
        u = self.data['Today_PNL']['unrealized'] or 0
        self.data['Today_PNL']['total'] = r + u
        
        self._save()
    
    def update_account(self, total_asset: float = None, available_cash: float = None, 
                       margin_used: float = None):
        """
        更新账户信息
        Args:
            total_asset: 总资产
            available_cash: 可用资金
            margin_used: 已用保证金
        """
        if total_asset is not None:
            self.data['Account_Info']['total_asset'] = total_asset
        if available_cash is not None:
            self.data['Account_Info']['available_cash'] = available_cash
        if margin_used is not None:
            self.data['Account_Info']['margin_used'] = margin_used
        
        self._save()
    
    def update_strategy_status(self, strategy: str, status: str):
        """
        更新策略状态
        Args:
            strategy: 策略名称 (BTDR_PrevClose / LianLian_V4)
            status: 状态 (ACTIVE / DISABLED / SUSPENDED)
        """
        if strategy in self.data['Strategy_Status']:
            self.data['Strategy_Status'][strategy] = status
            self._save()
    
    def update_risk_status(self, daily_loss_rate: float = None, max_drawdown: float = None,
                          circuit_breaker: str = None):
        """
        更新风控状态
        Args:
            daily_loss_rate: 当日亏损率
            max_drawdown: 最大回撤
            circuit_breaker: 熔断状态 (NORMAL / L1 / L2 / L3)
        """
        if daily_loss_rate is not None:
            self.data['Risk_Status']['daily_loss_rate'] = daily_loss_rate
        if max_drawdown is not None:
            self.data['Risk_Status']['max_drawdown'] = max_drawdown
        if circuit_breaker is not None:
            self.data['Risk_Status']['circuit_breaker'] = circuit_breaker
        
        self._save()
    
    def update_token_status(self, daily_used: int = None, remaining: int = None, 
                           usage_rate: float = None):
        """
        更新Token状态
        Args:
            daily_used: 今日已用
            remaining: 剩余
            usage_rate: 使用率
        """
        if daily_used is not None:
            self.data['Token_Status']['daily_used'] = daily_used
        if remaining is not None:
            self.data['Token_Status']['remaining'] = remaining
        if usage_rate is not None:
            self.data['Token_Status']['usage_rate'] = usage_rate
        
        self._save()
    
    def sync_from_futu_bridge(self, futu_data: dict):
        """
        从富途桥接数据同步
        Args:
            futu_data: 富途桥接返回的数据
        """
        # 更新账户信息
        if 'account' in futu_data:
            acc = futu_data['account']
            self.update_account(
                total_asset=acc.get('total_asset'),
                available_cash=acc.get('available_cash'),
                margin_used=acc.get('margin')
            )
        
        # 更新持仓
        if 'positions' in futu_data:
            for pos in futu_data['positions']:
                symbol = pos.get('symbol')
                if symbol:
                    self.update_position(
                        symbol=symbol,
                        shares=pos.get('shares'),
                        avg_cost=pos.get('avg_cost'),
                        current_price=pos.get('current_price')
                    )
        
        # 更新未实现盈亏
        if 'total_unrealized_pnl' in futu_data:
            self.update_pnl(unrealized=futu_data['total_unrealized_pnl'])
    
    def trigger_circuit_breaker(self, level: str, reason: str = None):
        """
        触发熔断
        Args:
            level: L1/L2/L3
            reason: 原因
        """
        self.update_risk_status(circuit_breaker=level)
        
        # 禁用所有策略
        for strategy in self.data['Strategy_Status']:
            self.data['Strategy_Status'][strategy] = 'DISABLED'
        
        self.data['circuit_breaker_reason'] = reason
        self._save()
    
    def reset(self):
        """重置为默认值"""
        self.data = self._init_default()
        self._save()
    
    def get_status(self) -> dict:
        """获取完整状态"""
        return self.data.copy()
    
    def is_stale(self, max_age_seconds: int = 900) -> bool:
        """
        检查数据是否过期
        Args:
            max_age_seconds: 最大过期秒数（默认15分钟，调整自原来的300秒）
        Returns:
            是否过期
        """
        if 'timestamp' not in self.data:
            return True
        
        last_update = datetime.datetime.fromisoformat(self.data['timestamp'])
        diff = (datetime.datetime.now() - last_update).total_seconds()
        return diff > max_age_seconds


def sync_golden_state():
    """从富途桥接同步黄金状态"""
    try:
        # 导入富途桥接
        sys.path.insert(0, WORKSPACE)
        from utils.futu_dashboard_bridge import sync_all_data
        
        # 获取富途数据
        futu_data = sync_all_data()
        
        # 更新黄金状态
        gsm = GoldenStateManager()
        gsm.sync_from_futu_bridge(futu_data)
        
        return {'status': 'ok', 'golden_state': gsm.get_status()}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


if __name__ == '__main__':
    gsm = GoldenStateManager()
    print("当前黄金状态:")
    print(json.dumps(gsm.get_status(), indent=2, ensure_ascii=False))
    
    # 检查是否过期
    print(f"\n数据过期: {gsm.is_stale()}")
