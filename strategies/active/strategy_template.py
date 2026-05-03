"""
策略标准化模板 v1.0
所有策略必须继承此基类，实现以下接口。

使用 backtrader 回测引擎：
  https://github.com/mementum/backtrader

标准接口:
  - generate_signal(data) -> dict   # 生成交易信号
  - get_params() -> dict             # 获取当前参数
  - set_params(params) -> None       # 更新参数
"""
import backtrader as bt
from typing import Dict, Optional

class BaseStrategy(bt.Strategy):
    """所有策略的基类"""
    
    params = (
        # 标准参数（可被策略覆盖）
        ('name', 'base_strategy'),
        ('version', '1.0'),
    )

    def log(self, txt):
        print(f'[{self.params.name}] {txt}')

    def __init__(self):
        self.order = None
        self.entry_price = None

    def generate_signal(self, data: Dict) -> Dict:
        """
        生成交易信号
        input:  data = {"open": [...], "high": [...], "low": [...], "close": [...], "volume": [...]}
        output: {"action": "buy|sell|hold", "price": float, "size": float, "confidence": 0-1}
        """
        raise NotImplementedError

    def next(self):
        """backtrader 回调 - 每个bar执行一次"""
        signal = self.generate_signal({})
        if signal.get("action") == "buy":
            self.order = self.buy()
        elif signal.get("action") == "sell":
            self.order = self.sell()

    def get_params(self) -> Dict:
        return {k: v for k, v in self.params._getitems() if k not in ('name',)}


# ==========================================
# 使用示例（BTDR PrevClose V2 骨架）
# ==========================================
class ExampleStrategy(BaseStrategy):
    params = (
        ('name', 'example'),
        ('version', '1.0'),
        ('prev_close_offset', 0.01),     # 前收盘价偏移%
        ('position_size', 0.2),           # 仓位比例
    )

    def generate_signal(self, data: Dict) -> Dict:
        # TODO: 从 data 计算信号
        return {"action": "hold", "price": 0, "size": 0, "confidence": 0.0}
