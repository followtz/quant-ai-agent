# -*- coding: utf-8 -*-
"""
影子模式验证框架
================
版本: 1.0
创建时间: 2026-04-21
功能: 规范新策略纳入实盘前的验证流程

影子模式流程:
1. 入池评估（评分≥60）
2. 影子模式运行（≥2周）
3. 验证报告评估
4. 总控审批
5. 小仓位试运行（1/3标准仓位）
6. 正式纳入实盘

验证标准:
- 胜率 > 55%
- 最大回撤 < 8%
- 信号准确率 > 60%
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
import logging
import os
from pathlib import Path

# ============================================================================
# 日志配置
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# 枚举定义
# ============================================================================

class VerificationPhase(Enum):
    """验证阶段"""
    PENDING = "待验证"
    SHADOW_RUNNING = "影子模式运行中"
    SHADOW_COMPLETED = "影子模式完成"
    EVALUATION_PENDING = "待评估"
    APPROVED = "已批准"
    REJECTED = "已拒绝"
    LIVE_TEST = "小仓位试运行"
    LIVE_ACTIVE = "正式实盘"
    ARCHIVED = "已归档"


class VerificationResult(Enum):
    """验证结果"""
    PASS = "通过"
    CONDITIONAL = "有条件通过"
    FAIL = "不通过"
    PENDING = "待定"


class RiskLevel(Enum):
    """风险等级"""
    LOW = "低风险"
    MEDIUM = "中风险"
    HIGH = "高风险"
    EXTREME = "高风险"


# ============================================================================
# 数据类定义
# ============================================================================

@dataclass
class SignalRecord:
    """信号记录"""
    timestamp: str
    signal: str              # BUY, SELL, HOLD
    confidence: float        # 置信度 0-1
    price: float             # 信号产生时价格
    reason: str              # 原因说明
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "signal": self.signal,
            "confidence": self.confidence,
            "price": self.price,
            "reason": self.reason
        }


@dataclass
class TradeRecord:
    """交易记录"""
    timestamp: str
    signal_timestamp: str    # 对应信号时间
    action: str              # BUY, SELL
    price: float              # 成交价格
    volume: int              # 成交量
    pnl: float               # 盈亏（如果已平仓）
    status: str               # PENDING, FILLED, CANCELLED
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "signal_timestamp": self.signal_timestamp,
            "action": self.action,
            "price": self.price,
            "volume": self.volume,
            "pnl": self.pnl,
            "status": self.status
        }


@dataclass
class StrategyMetrics:
    """策略指标"""
    # 基础指标
    total_signals: int = 0
    buy_signals: int = 0
    sell_signals: int = 0
    hold_signals: int = 0
    
    # 执行指标
    total_trades: int = 0
    filled_trades: int = 0
    cancelled_trades: int = 0
    
    # 收益指标
    total_return: float = 0      # 总收益率
    avg_return: float = 0        # 平均收益率
    win_rate: float = 0          # 胜率
    profit_factor: float = 0     # 盈利因子
    
    # 风险指标
    max_drawdown: float = 0     # 最大回撤
    max_consecutive_loss: int = 0  # 最大连续亏损次数
    avg_holding_period: float = 0  # 平均持仓时间
    
    # 质量指标
    signal_accuracy: float = 0    # 信号准确率
    false_signal_rate: float = 0  # 假信号率
    missed_signal_rate: float = 0  # 漏信号率
    
    def calculate_from_records(self, signals: List[SignalRecord], trades: List[TradeRecord]):
        """从记录计算指标"""
        # 基础统计
        self.total_signals = len(signals)
        self.buy_signals = sum(1 for s in signals if s.signal == "BUY")
        self.sell_signals = sum(1 for s in signals if s.signal == "SELL")
        self.hold_signals = sum(1 for s in signals if s.signal == "HOLD")
        
        # 交易统计
        self.total_trades = len(trades)
        self.filled_trades = sum(1 for t in trades if t.status == "FILLED")
        self.cancelled_trades = sum(1 for t in trades if t.status == "CANCELLED")
        
        # 计算盈亏
        filled_trades = [t for t in trades if t.status == "FILLED"]
        if filled_trades:
            pnls = [t.pnl for t in filled_trades if t.pnl is not None]
            if pnls:
                wins = [p for p in pnls if p > 0]
                losses = [p for p in pnls if p < 0]
                
                self.total_return = sum(pnls)
                self.avg_return = np.mean(pnls)
                self.win_rate = len(wins) / len(pnls) * 100 if pnls else 0
                self.profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 0
        
        # 计算最大回撤
        if filled_trades:
            cumulative = np.cumsum([t.pnl for t in filled_trades if t.pnl is not None])
            if len(cumulative) > 0:
                running_max = np.maximum.accumulate(cumulative)
                drawdowns = running_max - cumulative
                self.max_drawdown = np.max(drawdowns) if len(drawdowns) > 0 else 0
        
        # 信号准确率（信号后价格上涨/下跌的正确性）
        # 需要有信号后的价格数据来计算
        self.signal_accuracy = 0  # 需要实际数据计算
    
    def to_dict(self) -> Dict:
        return {
            "total_signals": self.total_signals,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "hold_signals": self.hold_signals,
            "total_trades": self.total_trades,
            "filled_trades": self.filled_trades,
            "cancelled_trades": self.cancelled_trades,
            "total_return": self.total_return,
            "avg_return": self.avg_return,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "max_drawdown": self.max_drawdown,
            "max_consecutive_loss": self.max_consecutive_loss,
            "avg_holding_period": self.avg_holding_period,
            "signal_accuracy": self.signal_accuracy,
            "false_signal_rate": self.false_signal_rate,
            "missed_signal_rate": self.missed_signal_rate
        }


@dataclass
class ShadowModeReport:
    """影子模式报告"""
    strategy_name: str
    symbol: str
    start_date: str
    end_date: str
    phase: VerificationPhase
    
    metrics: StrategyMetrics = field(default_factory=StrategyMetrics)
    signals: List[SignalRecord] = field(default_factory=list)
    trades: List[TradeRecord] = field(default_factory=list)
    
    # 评估结果
    result: VerificationResult = VerificationResult.PENDING
    result_reason: str = ""
    risk_level: RiskLevel = RiskLevel.MEDIUM
    
    # 建议
    recommendations: List[str] = field(default_factory=list)
    
    # 审批
    approved_by: str = ""
    approved_at: str = ""
    approval_notes: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "phase": self.phase.value,
            "metrics": self.metrics.to_dict(),
            "signals": [s.to_dict() for s in self.signals],
            "trades": [t.to_dict() for t in self.trades],
            "result": self.result.value,
            "result_reason": self.result_reason,
            "risk_level": self.risk_level.value,
            "recommendations": self.recommendations,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
            "approval_notes": self.approval_notes
        }


# ============================================================================
# 影子模式验证器
# ============================================================================

class ShadowModeValidator:
    """
    影子模式验证器
    """
    
    def __init__(self, base_dir: str = None):
        self.logger = logging.getLogger("ShadowModeValidator")
        
        # 设置保存目录
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(__file__).parent.parent / "data" / "shadow_mode"
        
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # 验证配置
        self.min_shadow_days = 14       # 最少影子模式天数
        self.min_signals = 20            # 最少信号数量
        self.win_rate_threshold = 55     # 胜率阈值55%
        self.max_drawdown_threshold = 8   # 最大回撤阈值8%
        self.signal_accuracy_threshold = 60  # 信号准确率阈值60%
        
        # 活跃的影子模式
        self.active_shadow_modes: Dict[str, ShadowModeReport] = {}
    
    def start_shadow_mode(
        self,
        strategy_name: str,
        symbol: str,
        initial_params: Dict = None
    ) -> str:
        """
        启动影子模式
        
        Args:
            strategy_name: 策略名称
            symbol: 交易标的
            initial_params: 初始参数
        
        Returns:
            影子模式ID
        """
        shadow_id = f"{strategy_name}_{symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        report = ShadowModeReport(
            strategy_name=strategy_name,
            symbol=symbol,
            start_date=datetime.now().isoformat(),
            end_date="",
            phase=VerificationPhase.SHADOW_RUNNING
        )
        
        self.active_shadow_modes[shadow_id] = report
        
        self.logger.info(f"启动影子模式: {shadow_id}")
        self.logger.info(f"  策略: {strategy_name}")
        self.logger.info(f"  标的: {symbol}")
        self.logger.info(f"  开始日期: {report.start_date}")
        
        # 保存到文件
        self._save_report(shadow_id, report)
        
        return shadow_id
    
    def record_signal(
        self,
        shadow_id: str,
        signal: SignalRecord
    ):
        """记录信号"""
        if shadow_id not in self.active_shadow_modes:
            self.logger.error(f"影子模式不存在: {shadow_id}")
            return
        
        report = self.active_shadow_modes[shadow_id]
        report.signals.append(signal)
        
        self.logger.info(f"记录信号: {signal.signal} @ ${signal.price:.2f} ({signal.confidence:.0%})")
        
        # 实时检查是否达到评估条件
        if len(report.signals) >= self.min_signals:
            self._check_evaluation_ready(shadow_id)
        
        self._save_report(shadow_id, report)
    
    def record_trade(
        self,
        shadow_id: str,
        trade: TradeRecord
    ):
        """记录交易"""
        if shadow_id not in self.active_shadow_modes:
            self.logger.error(f"影子模式不存在: {shadow_id}")
            return
        
        report = self.active_shadow_modes[shadow_id]
        report.trades.append(trade)
        
        status_icon = "✓" if trade.status == "FILLED" else "✗" if trade.status == "CANCELLED" else "○"
        self.logger.info(f"记录交易: {status_icon} {trade.action} {trade.volume}@{trade.price:.2f} PnL=${trade.pnl:.2f}")
        
        self._save_report(shadow_id, report)
    
    def complete_shadow_mode(self, shadow_id: str) -> ShadowModeReport:
        """
        完成影子模式并生成报告
        
        Args:
            shadow_id: 影子模式ID
        
        Returns:
            影子模式报告
        """
        if shadow_id not in self.active_shadow_modes:
            self.logger.error(f"影子模式不存在: {shadow_id}")
            return None
        
        report = self.active_shadow_modes[shadow_id]
        report.end_date = datetime.now().isoformat()
        report.phase = VerificationPhase.SHADOW_COMPLETED
        
        # 计算指标
        report.metrics.calculate_from_records(report.signals, report.trades)
        
        # 评估结果
        self._evaluate_report(report)
        
        self.logger.info(f"影子模式完成: {shadow_id}")
        self.logger.info(f"  结束日期: {report.end_date}")
        self.logger.info(f"  信号数量: {report.metrics.total_signals}")
        self.logger.info(f"  交易数量: {report.metrics.total_trades}")
        self.logger.info(f"  胜率: {report.metrics.win_rate:.1f}%")
        self.logger.info(f"  最大回撤: {report.metrics.max_drawdown:.2f}%")
        self.logger.info(f"  评估结果: {report.result.value}")
        
        self._save_report(shadow_id, report)
        
        return report
    
    def _check_evaluation_ready(self, shadow_id: str):
        """检查是否达到评估条件"""
        report = self.active_shadow_modes[shadow_id]
        
        days_running = (datetime.now() - datetime.fromisoformat(report.start_date)).days
        
        ready = True
        reasons = []
        
        if days_running < self.min_shadow_days:
            ready = False
            reasons.append(f"运行天数不足: {days_running} < {self.min_shadow_days}")
        
        if len(report.signals) < self.min_signals:
            ready = False
            reasons.append(f"信号数量不足: {len(report.signals)} < {self.min_signals}")
        
        if ready:
            report.phase = VerificationPhase.EVALUATION_PENDING
            self.logger.info(f"影子模式已达到评估条件: {shadow_id}")
        else:
            reasons_text = ", ".join(reasons)
            self.logger.info(f"影子模式评估条件: {reasons_text}")
    
    def _evaluate_report(self, report: ShadowModeReport):
        """评估影子模式报告"""
        metrics = report.metrics
        
        # 检查各项指标
        checks = []
        
        # 胜率检查
        if metrics.win_rate >= self.win_rate_threshold:
            checks.append(("胜率", True, f"{metrics.win_rate:.1f}% >= {self.win_rate_threshold}%"))
        else:
            checks.append(("胜率", False, f"{metrics.win_rate:.1f}% < {self.win_rate_threshold}%"))
        
        # 最大回撤检查
        if metrics.max_drawdown <= self.max_drawdown_threshold:
            checks.append(("最大回撤", True, f"{metrics.max_drawdown:.2f}% <= {self.max_drawdown_threshold}%"))
        else:
            checks.append(("最大回撤", False, f"{metrics.max_drawdown:.2f}% > {self.max_drawdown_threshold}%"))
        
        # 信号准确率检查
        if metrics.signal_accuracy >= self.signal_accuracy_threshold:
            checks.append(("信号准确率", True, f"{metrics.signal_accuracy:.1f}% >= {self.signal_accuracy_threshold}%"))
        else:
            checks.append(("信号准确率", False, f"{metrics.signal_accuracy:.1f}% < {self.signal_accuracy_threshold}%"))
        
        # 综合评估
        passed_checks = sum(1 for _, result, _ in checks if result)
        total_checks = len(checks)
        
        if passed_checks == total_checks:
            report.result = VerificationResult.PASS
            report.result_reason = f"所有指标达标 ({passed_checks}/{total_checks})"
        elif passed_checks >= total_checks * 0.5:
            report.result = VerificationResult.CONDITIONAL
            report.result_reason = f"部分指标达标 ({passed_checks}/{total_checks})，需改进后重新验证"
        else:
            report.result = VerificationResult.FAIL
            report.result_reason = f"多数指标未达标 ({passed_checks}/{total_checks})"
        
        # 风险等级评估
        if metrics.max_drawdown > 15 or metrics.win_rate < 45:
            report.risk_level = RiskLevel.HIGH
        elif metrics.max_drawdown > 8 or metrics.win_rate < 50:
            report.risk_level = RiskLevel.MEDIUM
        else:
            report.risk_level = RiskLevel.LOW
        
        # 生成建议
        self._generate_recommendations(report, checks)
    
    def _generate_recommendations(self, report: ShadowModeReport, checks: List):
        """生成建议"""
        report.recommendations = []
        
        for name, passed, detail in checks:
            if not passed:
                if name == "胜率":
                    report.recommendations.append("优化信号生成逻辑，提高胜率")
                elif name == "最大回撤":
                    report.recommendations.append("增加止损机制，控制回撤")
                elif name == "信号准确率":
                    report.recommendations.append("改进预测模型，提高准确率")
        
        if report.result == VerificationResult.PASS:
            report.recommendations.append("可提交总控审批，启动小仓位试运行")
        
        if report.risk_level == RiskLevel.HIGH:
            report.recommendations.append("⚠️ 风险等级较高，建议谨慎审批")
    
    def approve_report(
        self,
        shadow_id: str,
        approved_by: str = "总控官",
        notes: str = ""
    ) -> bool:
        """
        审批影子模式报告
        
        Args:
            shadow_id: 影子模式ID
            approved_by: 审批人
            notes: 审批备注
        
        Returns:
            是否审批通过
        """
        if shadow_id not in self.active_shadow_modes:
            self.logger.error(f"影子模式不存在: {shadow_id}")
            return False
        
        report = self.active_shadow_modes[shadow_id]
        
        if report.result == VerificationResult.FAIL:
            self.logger.warning(f"影子模式未通过评估: {shadow_id}")
            report.phase = VerificationPhase.REJECTED
            return False
        
        if report.result == VerificationResult.CONDITIONAL:
            report.phase = VerificationPhase.LIVE_TEST
        else:
            report.phase = VerificationPhase.LIVE_TEST
        
        report.approved_by = approved_by
        report.approved_at = datetime.now().isoformat()
        report.approval_notes = notes
        
        self.logger.info(f"影子模式已批准: {shadow_id}")
        self.logger.info(f"  审批人: {approved_by}")
        self.logger.info(f"  审批时间: {report.approved_at}")
        self.logger.info(f"  下一步: 小仓位试运行")
        
        self._save_report(shadow_id, report)
        
        return True
    
    def _save_report(self, shadow_id: str, report: ShadowModeReport):
        """保存报告"""
        # 保存JSON
        json_path = self.base_dir / f"{shadow_id}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
        
        # 保存信号CSV
        if report.signals:
            signals_df = pd.DataFrame([s.to_dict() for s in report.signals])
            signals_path = self.base_dir / f"{shadow_id}_signals.csv"
            signals_df.to_csv(signals_path, index=False, encoding='utf-8-sig')
        
        # 保存交易CSV
        if report.trades:
            trades_df = pd.DataFrame([t.to_dict() for t in report.trades])
            trades_path = self.base_dir / f"{shadow_id}_trades.csv"
            trades_df.to_csv(trades_path, index=False, encoding='utf-8-sig')
    
    def get_active_modes(self) -> List[Dict]:
        """获取活跃的影子模式列表"""
        return [
            {
                "shadow_id": sid,
                "strategy_name": r.strategy_name,
                "symbol": r.symbol,
                "start_date": r.start_date,
                "phase": r.phase.value,
                "signals": len(r.signals),
                "trades": len(r.trades),
                "days_running": (datetime.now() - datetime.fromisoformat(r.start_date)).days
            }
            for sid, r in self.active_shadow_modes.items()
        ]
    
    def generate_summary_report(self) -> pd.DataFrame:
        """生成汇总报告"""
        data = []
        
        for shadow_id, report in self.active_shadow_modes.items():
            row = {
                "影子模式ID": shadow_id,
                "策略": report.strategy_name,
                "标的": report.symbol,
                "阶段": report.phase.value,
                "评估结果": report.result.value,
                "风险等级": report.risk_level.value,
                "运行天数": (datetime.now() - datetime.fromisoformat(report.start_date)).days,
                "信号数": len(report.signals),
                "交易数": len(report.trades),
                "胜率": f"{report.metrics.win_rate:.1f}%",
                "最大回撤": f"{report.metrics.max_drawdown:.2f}%",
                "总收益": f"{report.metrics.total_return:.2f}%"
            }
            data.append(row)
        
        return pd.DataFrame(data)


# ============================================================================
# 快速启动函数
# ============================================================================

def quick_start_shadow_mode(
    strategy_name: str,
    symbol: str,
    base_dir: str = None
) -> Tuple[str, ShadowModeValidator]:
    """
    快速启动影子模式
    
    Args:
        strategy_name: 策略名称
        symbol: 交易标的
        base_dir: 保存目录
    
    Returns:
        (shadow_id, validator)
    
    Example:
        shadow_id, validator = quick_start_shadow_mode(
            "BTDR PrevClose V2", "MSTR"
        )
        
        # 记录信号
        validator.record_signal(shadow_id, SignalRecord(
            timestamp=datetime.now().isoformat(),
            signal="BUY",
            confidence=0.75,
            price=150.0,
            reason="PrevClose信号 + VIX正常"
        ))
        
        # 记录交易
        validator.record_trade(shadow_id, TradeRecord(
            timestamp=datetime.now().isoformat(),
            signal_timestamp=datetime.now().isoformat(),
            action="BUY",
            price=150.5,
            volume=100,
            pnl=None,
            status="FILLED"
        ))
        
        # 完成验证
        report = validator.complete_shadow_mode(shadow_id)
        print(f"评估结果: {report.result.value}")
    """
    validator = ShadowModeValidator(base_dir)
    shadow_id = validator.start_shadow_mode(strategy_name, symbol)
    
    return shadow_id, validator


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("影子模式验证框架测试")
    print("=" * 60)
    
    # 创建验证器
    validator = ShadowModeValidator()
    
    # 启动影子模式
    print("\n【启动影子模式】")
    shadow_id = validator.start_shadow_mode(
        strategy_name="BTDR PrevClose V2.1",
        symbol="MSTR"
    )
    
    # 模拟信号记录
    print("\n【记录模拟信号】")
    np.random.seed(42)
    
    base_price = 150.0
    for i in range(25):
        signal_time = datetime.now() - timedelta(days=25-i)
        
        # 随机生成信号
        rand = np.random.random()
        if rand < 0.4:
            signal = "BUY"
            confidence = 0.6 + np.random.random() * 0.3
        elif rand < 0.7:
            signal = "SELL"
            confidence = 0.6 + np.random.random() * 0.3
        else:
            signal = "HOLD"
            confidence = 0.5 + np.random.random() * 0.3
        
        # 价格变动
        price_change = np.random.normal(0, 0.02)
        base_price *= (1 + price_change)
        
        validator.record_signal(shadow_id, SignalRecord(
            timestamp=signal_time.isoformat(),
            signal=signal,
            confidence=confidence,
            price=round(base_price, 2),
            reason=f"模拟信号 #{i+1}"
        ))
    
    # 模拟交易记录
    print("\n【记录模拟交易】")
    buy_signals = [s for s in validator.active_shadow_modes[shadow_id].signals if s.signal == "BUY"]
    
    for i, sig in enumerate(buy_signals[:5]):
        trade_time = datetime.fromisoformat(sig.timestamp) + timedelta(hours=1)
        
        # 随机盈亏
        pnl = np.random.normal(50, 30)
        
        validator.record_trade(shadow_id, TradeRecord(
            timestamp=trade_time.isoformat(),
            signal_timestamp=sig.timestamp,
            action="BUY",
            price=round(sig.price * 1.001, 2),  # 略高买入价
            volume=100,
            pnl=pnl,
            status="FILLED"
        ))
    
    # 完成影子模式
    print("\n【完成影子模式验证】")
    report = validator.complete_shadow_mode(shadow_id)
    
    # 打印评估结果
    print("\n" + "=" * 60)
    print("影子模式评估报告")
    print("=" * 60)
    print(f"策略: {report.strategy_name}")
    print(f"标的: {report.symbol}")
    print(f"运行时间: {report.start_date[:10]} ~ {report.end_date[:10]}")
    print("-" * 60)
    print(f"信号总数: {report.metrics.total_signals}")
    print(f"交易总数: {report.metrics.total_trades}")
    print(f"胜率: {report.metrics.win_rate:.1f}%")
    print(f"最大回撤: {report.metrics.max_drawdown:.2f}%")
    print(f"总收益: {report.metrics.total_return:.2f}%")
    print("-" * 60)
    print(f"评估结果: {report.result.value}")
    print(f"评估原因: {report.result_reason}")
    print(f"风险等级: {report.risk_level.value}")
    
    if report.recommendations:
        print("\n建议:")
        for rec in report.recommendations:
            print(f"  → {rec}")
    
    # 审批报告
    print("\n【审批报告】")
    approved = validator.approve_report(
        shadow_id,
        approved_by="总控官",
        notes="影子模式验证通过，批准小仓位试运行"
    )
    print(f"审批结果: {'通过' if approved else '拒绝'}")
    
    # 生成汇总报告
    print("\n【活跃影子模式汇总】")
    summary = validator.generate_summary_report()
    print(summary.to_string(index=False))
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
