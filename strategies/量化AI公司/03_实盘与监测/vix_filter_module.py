# -*- coding: utf-8 -*-
"""
BTDR PrevClose V2.1 - VIX波动率过滤增强模块
===========================================
版本: 2.1
创建时间: 2026-04-21
灵感来源: je-suis-tm/quant-trading VIX策略
增强内容: VIX/VVIX市场状态过滤 PrevClose交易信号

原理:
- VIX > 25: 市场恐慌增加，涡轮卖出风险大，推迟卖出
- VVIX > 110: 波动率溢价期，增加卖出信心
- VIX + BTC组合判断最优执行时机
"""

import pandas as pd
import numpy as np
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple, Union
from enum import Enum
import json
import logging

# ============================================================================
# 配置
# ============================================================================

class VIXConfig:
    """VIX过滤配置"""
    
    # VIX阈值
    VIX_EXTREME_FEAR = 30      # 极度恐慌阈值
    VIX_HIGH_FEAR = 25         # 高度恐慌阈值
    VIX_NORMAL = 20             # 正常上限
    VIX_LOW_GREED = 15          # 低贪婪阈值
    VIX_EXTREME_GREED = 12     # 极度贪婪阈值
    
    # VVIX阈值
    VVIX_EXTREME = 120         # VVIX极度溢价
    VVIX_HIGH = 110            # VVIX高溢价
    VVIX_NORMAL = 95           # VVIX正常
    
    # 修正系数（调整信号强度）
    VIX_CORRECTION_FACTOR = 0.3   # VIX修正因子
    
    # 震荡市场参数
    VIX_RANGE_LOW = 15
    VIX_RANGE_HIGH = 25
    
    # 建议等待期（小时）
    WAIT_AFTER_EXTREME = 4


class MarketRegime(Enum):
    """市场状态枚举"""
    EXTREME_FEAR = "极度恐慌"
    HIGH_FEAR = "高度恐慌"
    ELEVATED = "偏高"
    NORMAL = "正常"
    LOW_GREED = "低贪婪"
    EXTREME_GREED = "极度贪婪"
    UNKNOWN = "未知"


class BTDRSignal(Enum):
    """BTDR交易信号枚举"""
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    HOLD = "持有"
    REDUCE_SIZE = "减仓"
    WAIT = "等待"
    SELL = "卖出"
    STRONG_SELL = "强烈卖出"


# ============================================================================
# VIX市场状态检测器
# ============================================================================

class VIXRegimeDetector:
    """VIX市场状态检测器"""
    
    def __init__(self, config: VIXConfig = None):
        self.config = config or VIXConfig()
        self.logger = logging.getLogger(__name__)
        
        # 历史状态缓存
        self.regime_history: List[Dict] = []
    
    def detect_regime(self, vix: float, vvix: float = None) -> Tuple[MarketRegime, Dict]:
        """
        检测VIX市场状态
        
        Args:
            vix: VIX当前值
            vvix: VVIX当前值（可选）
        
        Returns:
            (市场状态, 详细信息字典)
        """
        cfg = self.config
        
        # 检测VIX状态
        if vix > cfg.VIX_EXTREME_FEAR:
            vix_regime = "EXTREME_FEAR"
            vix_score = -2
        elif vix > cfg.VIX_HIGH_FEAR:
            vix_regime = "HIGH_FEAR"
            vix_score = -1
        elif vix > cfg.VIX_NORMAL:
            vix_regime = "ELEVATED"
            vix_score = -0.5
        elif vix > cfg.VIX_LOW_GREED:
            vix_regime = "NORMAL"
            vix_score = 0
        elif vix > cfg.VIX_EXTREME_GREED:
            vix_regime = "LOW_GREED"
            vix_score = 0.5
        else:
            vix_regime = "EXTREME_GREED"
            vix_score = 1
        
        # 检测VVIX状态（如果可用）
        vvix_regime = None
        vvix_score = 0
        vvix_signal = "NEUTRAL"
        
        if vvix is not None:
            if vvix > cfg.VVIX_EXTREME:
                vvix_regime = "EXTREME_PREMIUM"
                vvix_score = 1
                vvix_signal = "VOLATILITY_PREMIUM"  # 波动率溢价，增加卖出信心
            elif vvix > cfg.VVIX_HIGH:
                vvix_regime = "HIGH_PREMIUM"
                vvix_score = 0.5
                vvix_signal = "ELEVATED_PREMIUM"
            elif vvix < cfg.VVIX_NORMAL:
                vvix_regime = "LOW_PREMIUM"
                vvix_score = -0.5
                vvix_signal = "REDUCED_VOL"
            else:
                vvix_regime = "NORMAL_PREMIUM"
                vvix_signal = "NEUTRAL"
        
        # 综合判断市场状态
        combined_score = vix_score + vvix_score
        
        if combined_score <= -2:
            final_regime = MarketRegime.EXTREME_FEAR
        elif combined_score <= -1:
            final_regime = MarketRegime.HIGH_FEAR
        elif combined_score <= -0.5:
            final_regime = MarketRegime.ELEVATED
        elif combined_score <= 0.5:
            final_regime = MarketRegime.NORMAL
        elif combined_score <= 1:
            final_regime = MarketRegime.LOW_GREED
        else:
            final_regime = MarketRegime.EXTREME_GREED
        
        # 记录历史
        regime_info = {
            "timestamp": datetime.now().isoformat(),
            "vix": vix,
            "vvix": vvix,
            "vix_regime": vix_regime,
            "vvix_regime": vvix_regime,
            "combined_score": combined_score,
            "regime": final_regime.value,
            "signal": vvix_signal
        }
        self.regime_history.append(regime_info)
        
        return final_regime, regime_info
    
    def get_recent_regimes(self, n: int = 5) -> pd.DataFrame:
        """获取最近n个市场状态"""
        if len(self.regime_history) < n:
            return pd.DataFrame(self.regime_history)
        return pd.DataFrame(self.regime_history[-n:])


# ============================================================================
# BTC市场关联分析器
# ============================================================================

class BTCCorrelationAnalyzer:
    """BTC市场关联分析器"""
    
    def __init__(self):
        self.btc_price_history: List[float] = []
        self.volatility_history: List[float] = []
    
    def analyze_btc_momentum(self, btc_price: float, lookback: int = 20) -> Dict:
        """
        分析BTC动量
        
        Args:
            btc_price: BTC当前价格
            lookback: 回看周期
        
        Returns:
            动量分析结果字典
        """
        self.btc_price_history.append(btc_price)
        if len(self.btc_price_history) > lookback * 2:
            self.btc_price_history.pop(0)
        
        if len(self.btc_price_history) < lookback:
            return {"momentum": "UNKNOWN", "score": 0, "trend": "N/A"}
        
        # 计算动量
        recent_prices = self.btc_price_history[-lookback:]
        older_prices = self.btc_price_history[-lookback*2:-lookback]
        
        recent_return = (recent_prices[-1] / recent_prices[0] - 1) * 100
        older_return = (older_prices[-1] / older_prices[0] - 1) * 100 if len(older_prices) > 1 else 0
        
        # 计算波动率
        returns = pd.Series(recent_prices).pct_change().dropna()
        volatility = returns.std() * np.sqrt(365) * 100  # 年化波动率
        self.volatility_history.append(volatility)
        
        # 判断动量
        if recent_return > 5:
            momentum = "STRONG_UP"
            score = 2
        elif recent_return > 2:
            momentum = "UP"
            score = 1
        elif recent_return < -5:
            momentum = "STRONG_DOWN"
            score = -2
        elif recent_return < -2:
            momentum = "DOWN"
            score = -1
        else:
            momentum = "SIDEWAYS"
            score = 0
        
        return {
            "momentum": momentum,
            "score": score,
            "recent_return_pct": recent_return,
            "volatility_annual": volatility,
            "trend": "BULL" if recent_return > older_return else "BEAR"
        }


# ============================================================================
# BTDR PrevClose V2.1 增强信号生成器
# ============================================================================

class BTDRPrevCloseV21Enhancer:
    """
    BTDR PrevClose V2.1 增强版信号生成器
    ========================================
    在原有V2基础上加入VIX波动率过滤和BTC动量确认
    
    增强逻辑:
    1. VIX > 25 + 跳空下行 → 减少涡轮A卖出
    2. VVIX > 110 → 增加涡轮卖出信心
    3. BTC强势 → 减少涡轮B卖出（可能有反弹）
    4. BTC弱势 → 增加涡轮B卖出（可能继续下跌）
    """
    
    def __init__(self, 
                 vix_detector: VIXRegimeDetector = None,
                 btc_analyzer: BTCCorrelationAnalyzer = None,
                 config: VIXConfig = None):
        self.vix_detector = vix_detector or VIXRegimeDetector()
        self.btc_analyzer = btc_analyzer or BTCCorrelationAnalyzer()
        self.config = config or VIXConfig()
        
        self.logger = logging.getLogger(__name__)
        
        # 信号历史
        self.signal_history: List[Dict] = []
        
        # 统计
        self.stats = {
            "total_signals": 0,
            "vix_filter_active": 0,
            "btc_confirm_active": 0,
            "final_signals": {}
        }
    
    def analyze_prevclose_trade(
        self,
        # 原有V2信号
        prevclose_signal: bool,
        prevclose_deviation: float,  # 百分比
        gap_direction: str,          # "UP", "DOWN", "NONE"
        turbo_type: str,             # "A" (涡轮A), "B" (涡轮B), "C" (涡轮C)
        # 新增：VIX数据
        vix: float,
        vvix: float = None,
        # 新增：BTC数据
        btc_price: float = None,
        # 新增：原始信号强度
        original_conviction: float = 0.5
    ) -> Dict:
        """
        分析PrevClose交易信号
        
        Args:
            prevclose_signal: 原始PrevClose信号
            prevclose_deviation: PrevClose偏差百分比
            gap_direction: 跳空方向
            turbo_type: 涡轮类型
            vix: VIX当前值
            vvix: VVIX当前值（可选）
            btc_price: BTC当前价格（可选）
            original_conviction: 原始信号置信度
        
        Returns:
            增强后的交易决策字典
        """
        self.stats["total_signals"] += 1
        
        # 1. VIX市场状态检测
        vix_regime, vix_info = self.vix_detector.detect_regime(vix, vvix)
        
        # 2. BTC动量分析（如果提供）
        btc_info = {"momentum": "UNKNOWN", "score": 0}
        if btc_price is not None:
            btc_info = self.btc_analyzer.analyze_btc_momentum(btc_price)
        
        # 3. 计算修正因子
        vix_correction = self._calculate_vix_correction(vix_regime, turbo_type, gap_direction)
        btc_correction = self._calculate_btc_correction(btc_info, turbo_type)
        
        # 4. 综合评分
        base_score = original_conviction if prevclose_signal else 0.5
        adjusted_score = base_score * (1 + vix_correction) * (1 + btc_correction)
        adjusted_score = max(0, min(1, adjusted_score))  # 限制在0-1
        
        # 5. 生成最终信号
        final_signal, action = self._generate_signal(
            prevclose_signal=prevclose_signal,
            turbo_type=turbo_type,
            gap_direction=gap_direction,
            vix_regime=vix_regime,
            vix_info=vix_info,
            btc_info=btc_info,
            adjusted_score=adjusted_score,
            prevclose_deviation=prevclose_deviation
        )
        
        # 记录统计
        if vix_correction != 0:
            self.stats["vix_filter_active"] += 1
        if btc_correction != 0:
            self.stats["btc_confirm_active"] += 1
        
        signal_key = f"{final_signal.value}_{turbo_type}"
        self.stats["final_signals"][signal_key] = self.stats["final_signals"].get(signal_key, 0) + 1
        
        # 构建结果
        result = {
            "timestamp": datetime.now().isoformat(),
            # 原始信息
            "original_signal": prevclose_signal,
            "original_conviction": original_conviction,
            "prevclose_deviation": prevclose_deviation,
            "gap_direction": gap_direction,
            "turbo_type": turbo_type,
            # VIX分析
            "vix": vix,
            "vvix": vvix,
            "vix_regime": vix_regime.value,
            "vix_info": vix_info,
            # BTC分析
            "btc_price": btc_price,
            "btc_momentum": btc_info.get("momentum", "UNKNOWN"),
            "btc_score": btc_info.get("score", 0),
            # 修正因子
            "vix_correction": vix_correction,
            "btc_correction": btc_correction,
            "adjusted_score": adjusted_score,
            # 最终决策
            "final_signal": final_signal.value,
            "action": action,
            "conviction": adjusted_score,
            "reason": self._generate_reason(vix_regime, btc_info, turbo_type)
        }
        
        self.signal_history.append(result)
        return result
    
    def _calculate_vix_correction(
        self, 
        regime: MarketRegime, 
        turbo_type: str,
        gap_direction: str
    ) -> float:
        """
        计算VIX修正因子
        
        Returns:
            float: 修正因子 (-0.5 ~ +0.5)
        """
        cfg = self.config
        correction = 0
        
        if regime == MarketRegime.EXTREME_FEAR:
            # 极度恐慌：大幅减少卖出
            if turbo_type in ["A", "B"]:
                correction = -0.4
            else:
                correction = -0.2
        
        elif regime == MarketRegime.HIGH_FEAR:
            # 高度恐慌
            if gap_direction == "DOWN":
                # 跳空下行 + 高波动：减少卖出
                correction = -0.3
            elif turbo_type == "A":
                correction = -0.2
        
        elif regime == MarketRegime.ELEVATED:
            if gap_direction == "DOWN":
                correction = -0.15
        
        elif regime == MarketRegime.LOW_GREED:
            # 低贪婪：增加卖出信心
            if turbo_type in ["A", "B"]:
                correction = 0.2
        
        elif regime == MarketRegime.EXTREME_GREED:
            # 极度贪婪：大幅增加卖出
            if turbo_type in ["A", "B"]:
                correction = 0.4
        
        return correction
    
    def _calculate_btc_correction(
        self,
        btc_info: Dict,
        turbo_type: str
    ) -> float:
        """
        计算BTC修正因子
        
        Returns:
            float: 修正因子 (-0.3 ~ +0.3)
        """
        correction = 0
        momentum = btc_info.get("momentum", "UNKNOWN")
        score = btc_info.get("score", 0)
        
        if momentum == "UNKNOWN":
            return 0
        
        # 涡轮A（通常在BTC下跌时升值）
        if turbo_type == "A":
            if momentum == "STRONG_DOWN":
                correction = -0.2  # BTC已经很弱，减少卖出涡轮A
            elif momentum == "STRONG_UP":
                correction = 0.15  # BTC强势，涡轮A可能回调
        
        # 涡轮B（通常在BTC上涨时升值）
        elif turbo_type == "B":
            if momentum == "STRONG_UP":
                correction = -0.2  # BTC已经很强势，减少卖出涡轮B
            elif momentum == "STRONG_DOWN":
                correction = 0.2   # BTC弱势，涡轮B可能继续跌
        
        return correction
    
    def _generate_signal(
        self,
        prevclose_signal: bool,
        turbo_type: str,
        gap_direction: str,
        vix_regime: MarketRegime,
        vix_info: Dict,
        btc_info: Dict,
        adjusted_score: float,
        prevclose_deviation: float
    ) -> Tuple[BTDRSignal, str]:
        """生成最终信号"""
        
        # 极度恐慌：等待
        if vix_regime == MarketRegime.EXTREME_FEAR:
            return BTDRSignal.WAIT, "VIX极度恐慌，等待市场稳定"
        
        # 高度恐慌 + 跳空下行 + 涡轮A
        if (vix_regime == MarketRegime.HIGH_FEAR and 
            gap_direction == "DOWN" and 
            turbo_type == "A"):
            return BTDRSignal.REDUCE_SIZE, "高波动+跳空下行，减少涡轮A仓位"
        
        # 极度贪婪：强烈卖出
        if vix_regime == MarketRegime.EXTREME_GREED and prevclose_signal:
            return BTDRSignal.STRONG_SELL, "VIX极度贪婪，增加卖出力度"
        
        # 有PrevClose信号且置信度高
        if prevclose_signal and adjusted_score > 0.7:
            return BTDRSignal.SELL, "PrevClose信号确认 + VIX支持"
        
        if prevclose_signal and adjusted_score > 0.55:
            return BTDRSignal.BUY, "PrevClose信号确认"
        
        # PrevClose信号但置信度低
        if prevclose_signal and adjusted_score <= 0.55:
            return BTDRSignal.HOLD, "PrevClose信号存在但VIX环境不支持"
        
        # 无PrevClose信号
        return BTDRSignal.HOLD, "无PrevClose信号，保持观望"
    
    def _generate_reason(
        self,
        vix_regime: MarketRegime,
        btc_info: Dict,
        turbo_type: str
    ) -> str:
        """生成决策原因说明"""
        reasons = []
        
        reasons.append(f"VIX状态: {vix_regime.value}")
        
        if btc_info.get("momentum") != "UNKNOWN":
            reasons.append(f"BTC动量: {btc_info['momentum']}")
        
        reasons.append(f"涡轮类型: {turbo_type}")
        
        return " | ".join(reasons)
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats,
            "vix_filter_rate": (
                self.stats["vix_filter_active"] / max(1, self.stats["total_signals"]) * 100
            ),
            "btc_confirm_rate": (
                self.stats["btc_confirm_active"] / max(1, self.stats["total_signals"]) * 100
            )
        }
    
    def get_signal_dataframe(self) -> pd.DataFrame:
        """获取信号历史DataFrame"""
        if not self.signal_history:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.signal_history)
        
        # 添加时间索引
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        
        return df


# ============================================================================
# VIX数据获取器（多数据源）
# ============================================================================

class VIXDataProvider:
    """
    VIX数据获取器
    支持多种数据源：Futu OpenD, yfinance, investing.com等
    """
    
    def __init__(self):
        self.data_cache: Dict[str, Dict] = {
            "vix": [],
            "vvix": [],
            "btc": []
        }
        self.logger = logging.getLogger(__name__)
    
    def get_vix_vvix(
        self,
        source: str = "futu",
        futu_conn = None
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        获取VIX和VVIX数据
        
        Args:
            source: 数据源 ("futu", "yfinance", "manual")
            futu_conn: 富途连接对象
        
        Returns:
            (vix, vvix)
        """
        if source == "futu":
            return self._get_from_futu(futu_conn)
        elif source == "yfinance":
            return self._get_from_yfinance()
        elif source == "manual":
            # 手动输入模式（用于测试或数据缺失时）
            return None, None
        else:
            self.logger.warning(f"未知数据源: {source}")
            return None, None
    
    def _get_from_futu(self, conn) -> Tuple[Optional[float], Optional[float]]:
        """从富途获取VIX数据"""
        # 注意：富途OpenD不直接提供VIX期货数据
        # 需要通过期权链计算隐含波动率
        # 这里提供框架代码，实际使用需要根据API调整
        
        self.logger.warning("富途OpenD不直接提供VIX数据")
        self.logger.info("建议使用VVIX指数或通过期权链计算")
        
        return None, None
    
    def _get_from_yfinance(self) -> Tuple[Optional[float], Optional[float]]:
        """从yfinance获取VIX数据"""
        try:
            import yfinance as yf
            
            # 获取VIX ETF（VIXY或UVXY）
            vixy = yf.Ticker("VIXY")
            vix_data = vixy.history(period="1d")
            
            if not vix_data.empty:
                vix = float(vix_data['Close'].iloc[-1])
            else:
                vix = None
            
            # VVIX获取（可通过期权链计算，这里用代理指标）
            # 使用VIX短期期货ETF作为代理
            uvxy = yf.Ticker("UVXY")
            uvxy_data = uvxy.history(period="1d")
            
            if not uvxy_data.empty:
                vvix_proxy = float(uvxy_data['Close'].iloc[-1])
                # VVIX通常比VIX高，这里用比例估算
                vvix = vvix_proxy * 1.2 if vix else None
            else:
                vvix = None
            
            return vix, vvix
            
        except ImportError:
            self.logger.error("yfinance未安装，请运行: pip install yfinance")
            return None, None
        except Exception as e:
            self.logger.error(f"yfinance获取VIX失败: {e}")
            return None, None
    
    def get_btc_price(self, source: str = "yfinance") -> Optional[float]:
        """获取BTC价格"""
        try:
            import yfinance as yf
            
            btc = yf.Ticker("BTC-USD")
            btc_data = btc.history(period="1d")
            
            if not btc_data.empty:
                return float(btc_data['Close'].iloc[-1])
            return None
            
        except Exception as e:
            self.logger.error(f"获取BTC价格失败: {e}")
            return None


# ============================================================================
# 实用工具函数
# ============================================================================

def create_vix_enhanced_signal(
    # PrevClose参数
    prevclose_signal: bool,
    prevclose_deviation: float,
    gap_direction: str,
    turbo_type: str,
    original_conviction: float = 0.5,
    # VIX参数
    vix: float = 20.0,
    vvix: float = 100.0,
    # BTC参数
    btc_price: float = None
) -> Dict:
    """
    快速创建VIX增强信号的便捷函数
    
    示例:
        result = create_vix_enhanced_signal(
            prevclose_signal=True,
            prevclose_deviation=5.0,
            gap_direction="UP",
            turbo_type="A",
            vix=22.0,
            vvix=105.0,
            btc_price=65000.0
        )
        print(result['final_signal'])
    """
    enhancer = BTDRPrevCloseV21Enhancer()
    
    return enhancer.analyze_prevclose_trade(
        prevclose_signal=prevclose_signal,
        prevclose_deviation=prevclose_deviation,
        gap_direction=gap_direction,
        turbo_type=turbo_type,
        vix=vix,
        vvix=vvix,
        btc_price=btc_price,
        original_conviction=original_conviction
    )


def print_signal_summary(result: Dict):
    """Print signal summary in ASCII-safe format"""
    print("=" * 60)
    print("BTDR PrevClose V2.1 Signal Summary")
    print("=" * 60)
    print(f"Time: {result['timestamp']}")
    print(f"Turbo Type: {result['turbo_type']}")
    print("-" * 40)
    vix_val = result['vix']
    vvix_val = result.get('vvix', 'N/A')
    print(f"VIX: {vix_val} | VVIX: {vvix_val}")
    print(f"VIX Regime: {result['vix_regime']}")
    btc_mom = result.get('btc_momentum', 'UNKNOWN')
    print(f"BTC Momentum: {btc_mom}")
    print("-" * 40)
    orig_sig = result['original_signal']
    orig_conf = result['original_conviction']
    print(f"Original Signal: {orig_sig} (Conviction: {orig_conf:.2f})")
    print(f"Adjusted Conviction: {result['adjusted_score']:.2f}")
    print(f"VIX Correction: {result['vix_correction']:+.2f}")
    print(f"BTC Correction: {result['btc_correction']:+.2f}")
    print("-" * 40)
    print(f"Final Signal: {result['final_signal']}")
    print(f"Action: {result['action']}")
    print(f"Reason: {result['reason']}")
    print("=" * 60)


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("BTDR PrevClose V2.1 VIX过滤增强模块测试")
    print("=" * 60)
    
    # 测试案例1：正常市场 PrevClose买入信号
    print("\n[Test 1] Normal market PrevClose BUY signal")
    result1 = create_vix_enhanced_signal(
        prevclose_signal=True,
        prevclose_deviation=5.0,
        gap_direction="UP",
        turbo_type="A",
        vix=18.0,  # 正常偏低
        vvix=95.0,
        btc_price=65000.0,
        original_conviction=0.7
    )
    print_signal_summary(result1)
    
    # 测试案例2：高波动市场 跳空下行
    print("\n[Test 2] High volatility DOWN gap Turbo A")
    result2 = create_vix_enhanced_signal(
        prevclose_signal=True,
        prevclose_deviation=4.0,
        gap_direction="DOWN",
        turbo_type="A",
        vix=28.0,  # 极度恐慌
        vvix=115.0,
        btc_price=58000.0,  # BTC下跌
        original_conviction=0.7
    )
    print_signal_summary(result2)
    
    # 测试案例3：极度贪婪市场
    print("\n[Test 3] Extreme greed market PrevClose SELL signal")
    result3 = create_vix_enhanced_signal(
        prevclose_signal=True,
        prevclose_deviation=6.0,
        gap_direction="UP",
        turbo_type="B",
        vix=12.0,  # 极度贪婪
        vvix=90.0,
        btc_price=70000.0,  # BTC强势
        original_conviction=0.75
    )
    print_signal_summary(result3)
    
    # 测试案例4：涡轮B + BTC强势
    print("\n[Test 4] Turbo B + BTC strong uptrend")
    result4 = create_vix_enhanced_signal(
        prevclose_signal=True,
        prevclose_deviation=3.0,
        gap_direction="UP",
        turbo_type="B",
        vix=16.0,
        vvix=100.0,
        btc_price=72000.0,  # BTC强势
        original_conviction=0.65
    )
    print_signal_summary(result4)
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
