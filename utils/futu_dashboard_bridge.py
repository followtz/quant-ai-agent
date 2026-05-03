# -*- coding: utf-8 -*-
"""
富途数据桥接 → Dashboard 快照 (futu_dashboard_bridge.py)
龙虾总控智能体 · P1 阶段
版本: v1.0 | 2026-04-22

职责：
  - 从富途OpenD获取账户资产、持仓、订单数据
  - 自动写入 /data/dashboard/ 的 trade_risk.json 和 global_status.json
  - 供 Heartbeat / Cron / 手动调用

调用方式：
  python -m utils.futu_dashboard_bridge
  或
  from utils.futu_dashboard_bridge import FutuDashboardBridge
  bridge = FutuDashboardBridge()
  bridge.sync_all()
"""

import json
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# 富途API
try:
    import futu as ft
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False

# 本地模块
WORKSPACE = Path(__file__).parent.parent
sys.path.insert(0, str(WORKSPACE))
from utils.dashboard_writer import DashboardWriter

FUTU_HOST = "127.0.0.1"
FUTU_PORT = 11111

_logger = logging.getLogger("futu_bridge")
_logger.setLevel(logging.INFO)
if not _logger.handlers:
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter("%(asctime)s [futu-bridge] %(message)s", datefmt="%H:%M:%S"))
    _logger.addHandler(sh)


class FutuDashboardBridge:
    """富途OpenD → Dashboard 数据桥接"""

    def __init__(self, host: str = FUTU_HOST, port: int = FUTU_PORT):
        self.host = host
        self.port = port
        self.dw = DashboardWriter()
        self.quote_ctx = None
        self.trade_ctx = None

    def _connect(self) -> bool:
        """建立富途连接"""
        if not FUTU_AVAILABLE:
            _logger.error("futu-api 未安装，无法桥接")
            return False
        try:
            self.quote_ctx = ft.OpenQuoteContext(host=self.host, port=self.port)
            self.trade_ctx = ft.OpenSecTradeContext(
                filter_trdmarket=ft.TrdMarket.US,
                host=self.host, port=self.port
            )
            _logger.info(f"富途连接成功: {self.host}:{self.port}")
            return True
        except Exception as e:
            _logger.error(f"富途连接失败: {e}")
            return False

    def _close(self):
        """关闭富途连接"""
        try:
            if self.quote_ctx:
                self.quote_ctx.close()
            if self.trade_ctx:
                self.trade_ctx.close()
        except Exception:
            pass

    # ----------------------------------------------------------
    # 账户资产 → global_status.json
    # ----------------------------------------------------------
    def sync_account(self) -> Optional[Dict]:
        """同步账户总资产和当日盈亏到 global_status.json"""
        if not self.trade_ctx:
            return None

        try:
            # 获取账户资产概览
            ret, data = self.trade_ctx.accinfo_query()
            if ret != ft.RET_OK:
                _logger.warning(f"accinfo_query 失败: {data}")
                return None

            if len(data) == 0:
                _logger.warning("accinfo_query 返回空数据")
                return None

            row = data.iloc[0]
            total_assets = float(row.get("total_assets", 0))
            daily_pnl = float(row.get("pl_val", 0))
            power = float(row.get("power", 0))

            result = self.dw.update_global_status(
                total_capital=total_assets,
                daily_pnl=daily_pnl,
            )

            _logger.info(f"账户同步: 总资产={total_assets:.2f}, 当日盈亏={daily_pnl:.2f}")
            return result

        except Exception as e:
            _logger.error(f"账户同步异常: {e}")
            return None

    # ----------------------------------------------------------
    # 持仓 → trade_risk.json (drawdown_monitor)
    # ----------------------------------------------------------
    def sync_positions(self) -> Optional[Dict]:
        """同步持仓信息，计算单票回撤写入 trade_risk.json"""
        if not self.trade_ctx:
            return None

        try:
            ret, data = self.trade_ctx.position_list_query()
            if ret != ft.RET_OK:
                _logger.warning(f"position_list_query 失败: {data}")
                return None

            drawdown = {}
            order_count = 0

            for _, row in data.iterrows():
                symbol = row.get("code", "")
                cost_price = float(row.get("cost_price", 0))
                market_price = float(row.get("market_price", 0))
                qty = float(row.get("qty", 0))
                pl_ratio = float(row.get("pl_ratio", 0))

                # 单票回撤百分比（负值表示浮亏）
                drawdown[symbol] = round(pl_ratio, 2)
                order_count += 1

            result = self.dw.update_trade_risk(drawdown=drawdown)
            _logger.info(f"持仓同步: {order_count} 只股票, 回撤数据已写入")
            return result

        except Exception as e:
            _logger.error(f"持仓同步异常: {e}")
            return None

    # ----------------------------------------------------------
    # 当日订单 → trade_risk.json (recent_orders)
    # ----------------------------------------------------------
    def sync_orders(self) -> List[Dict]:
        """同步当日订单到 trade_risk.json"""
        if not self.trade_ctx:
            return []

        try:
            ret, data = self.trade_ctx.order_list_query()
            if ret != ft.RET_OK:
                _logger.warning(f"order_list_query 失败: {data}")
                return []

            orders = []
            for _, row in data.iterrows():
                order = {
                    "timestamp": str(row.get("create_time", "")),
                    "symbol": str(row.get("code", "")),
                    "action": str(row.get("trd_side", "")),
                    "price": float(row.get("price", 0)),
                    "volume": float(row.get("qty", 0)),
                    "status": str(row.get("order_status", "")),
                    "strategy": "manual"  # 富途API无法区分策略来源
                }
                self.dw.update_trade_risk(order=order)
                orders.append(order)

            _logger.info(f"订单同步: {len(orders)} 笔")
            return orders

        except Exception as e:
            _logger.error(f"订单同步异常: {e}")
            return []

    # ----------------------------------------------------------
    # 市场状态 → global_status.json (active_market)
    # ----------------------------------------------------------
    def detect_market(self) -> str:
        """根据当前时间判断活跃市场"""
        now = datetime.now()
        hour = now.hour
        minute = now.minute
        weekday = now.weekday()

        if weekday >= 5:  # 周末
            return "none"

        # 港股 09:30-16:00 HKT
        if 9 <= hour < 16 or (hour == 9 and minute >= 30):
            return "hk_stock"
        # 美股 21:30-04:00 HKT (跨日)
        if hour >= 21 or hour <= 4:
            return "us_stock"

        return "none"

    # ----------------------------------------------------------
    # 一键全量同步
    # ----------------------------------------------------------
    def sync_all(self) -> Dict[str, Any]:
        """全量同步：账户+持仓+订单+市场状态"""
        result = {
            "timestamp": datetime.now().isoformat(),
            "connected": False,
            "account": None,
            "positions": None,
            "orders": [],
            "market": "none",
            "golden_state": None
        }

        # 市场状态（不需要连接）
        market = self.detect_market()
        result["market"] = market
        self.dw.update_global_status(active_market=market)

        # 富途连接
        if not self._connect():
            _logger.warning("富途连接失败，仅同步市场状态")
            return result

        result["connected"] = True

        try:
            # 依次同步
            result["account"] = self.sync_account()
            result["positions"] = self.sync_positions()
            result["orders"] = self.sync_orders()
            
            # 同步黄金状态变量
            result["golden_state"] = self._sync_golden_state(result)
        finally:
            self._close()

        _logger.info(f"全量同步完成: market={market}, connected=True")
        return result

    def _sync_golden_state(self, sync_result: Dict) -> Optional[Dict]:
        """同步数据到黄金状态变量"""
        try:
            from utils.golden_state_manager import GoldenStateManager
            gsm = GoldenStateManager()
            
            # 同步账户信息
            if sync_result.get("account"):
                acc = sync_result["account"]
                if acc and isinstance(acc, dict):
                    # 从global_status中提取账户数据
                    pass
            
            # 同步持仓信息
            if sync_result.get("positions"):
                positions = sync_result["positions"]
                if positions and isinstance(positions, dict) and "drawdown" in positions:
                    # 持仓数据已写入trade_risk.json
                    pass
            
            # 同步当日盈亏
            if sync_result.get("account"):
                acc_data = sync_result["account"]
                if acc_data and isinstance(acc_data, dict):
                    daily_pnl = acc_data.get("daily_pnl")
                    if daily_pnl is not None:
                        gsm.update_pnl(realized=daily_pnl)
            
            # 同步总资产
            if sync_result.get("account"):
                acc_data = sync_result["account"]
                if acc_data and isinstance(acc_data, dict):
                    total_assets = acc_data.get("total_assets")
                    if total_assets is not None:
                        gsm.update_account(total_asset=total_assets)
            
            _logger.info("黄金状态变量同步完成")
            return gsm.get_status()
        except Exception as e:
            _logger.warning(f"黄金状态同步失败: {e}")
            return None

    # ----------------------------------------------------------
    # 快速健康检查（不消耗太多资源）
    # ----------------------------------------------------------
    def health_check(self) -> Dict[str, Any]:
        """快速检查富途OpenD连通性"""
        result = {
            "opend_port": self.port,
            "opend_reachable": False,
            "market": self.detect_market(),
            "timestamp": datetime.now().isoformat()
        }

        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            s.connect((self.host, self.port))
            s.close()
            result["opend_reachable"] = True
        except Exception:
            pass

        return result


# ============================================================
# 命令行入口
# ============================================================
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="富途数据桥接 → Dashboard")
    parser.add_argument("--mode", choices=["sync", "health"], default="sync",
                        help="sync=全量同步, health=快速健康检查")
    parser.add_argument("--push", action="store_true",
                        help="同步后推送指挥舱卡片")
    args = parser.parse_args()

    bridge = FutuDashboardBridge()

    if args.mode == "health":
        result = bridge.health_check()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        result = bridge.sync_all()
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        if args.push:
            from utils.wechat_push import push_dashboard_from_snapshot
            push_dashboard_from_snapshot("富途数据桥接同步")
            print("指挥舱卡片已推送")
