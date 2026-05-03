#!/usr/bin/env python3
"""
策略统一运行接口 v1.0
标准化所有策略的输入/输出格式
使用 backtrader 作为回测引擎

接口规范:
  input:  {"strategy": "strategy_name", "action": "backtest|live|signal", "params": {...}}
  output: {"status": "ok|error", "data": {...}, "timestamp": "..."}
"""
import json, sys, os, importlib
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE))

class StrategyRunner:
    def __init__(self):
        self.strategies_dir = WORKSPACE / "strategies"
        self.result_dir = WORKSPACE / "data" / "backtest_results"
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self._load_strategies()

    def _load_strategies(self):
        """自动发现所有注册的策略"""
        registry_file = self.strategies_dir / "registry.json"
        if registry_file.exists():
            with open(registry_file) as f:
                self.registry = json.load(f)
        else:
            self.registry = {}

    def run(self, strategy_name: str, action: str = "signal", params: dict = None):
        """统一运行入口"""
        if strategy_name not in self.registry:
            return {"status": "error", "error": f"策略 {strategy_name} 未注册"}

        info = self.registry[strategy_name]
        try:
            module = importlib.import_module(info["module"])
            strategy_class = getattr(module, info["class"])
            
            if action == "backtest":
                result = self._backtest(strategy_class, params or {})
            elif action == "live":
                result = self._live(strategy_class, params or {})
            else:  # signal
                result = self._signal(strategy_class, params or {})

            return {"status": "ok", "data": result, "timestamp": datetime.now().isoformat()}
        except Exception as e:
            return {"status": "error", "error": str(e), "timestamp": datetime.now().isoformat()}

    def _backtest(self, strategy_class, params):
        """使用 backtrader 回测"""
        import backtrader as bt
        cerebro = bt.Cerebro()
        # 添加策略和数据
        cerebro.addstrategy(strategy_class)
        # TODO: 接入 Futu OpenD 数据源
        return {"message": "backtest queued", "params": params}

    def _live(self, strategy_class, params):
        return {"message": "live trading not implemented", "params": params}

    def _signal(self, strategy_class, params):
        return {"message": "signal generated", "params": params}

# CLI 入口
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python strategy_runner.py <strategy_name> [action] [params_json]")
        sys.exit(1)
    
    runner = StrategyRunner()
    name = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else "signal"
    params = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    
    result = runner.run(name, action, params)
    print(json.dumps(result, indent=2, ensure_ascii=False))
