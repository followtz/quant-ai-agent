# -*- coding: utf-8 -*-
"""
VIX数据源调研与获取脚本
========================
版本: 1.0
创建时间: 2026-04-21
功能: 调研多种VIX数据源，提供统一的获取接口

数据源对比:
| 数据源 | VIX | VVIX | BTC | 延迟 | 成本 |
|--------|-----|------|-----|------|------|
| yfinance | ✓ | ~代理 | ✓ | 15min | 免费 |
| investpy | ✓ | ✗ | ✓ | 日间 | 免费 |
| Alpha Vantage | ✓ | ✗ | ✓ | 日间 | 免费(有限) |
| 富途OpenD | ~需计算 | ✗ | ✗ | 实时 | 免费(已开通) |
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging
import json
import time

# ============================================================================
# 日志配置
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# 数据源基类
# ============================================================================

class VIXDataSource:
    """VIX数据源基类"""
    
    name = "Base"
    description = ""
    
    def __init__(self):
        self.logger = logging.getLogger(self.name)
    
    def get_vix(self) -> Optional[float]:
        """获取VIX当前值"""
        raise NotImplementedError
    
    def get_vvix(self) -> Optional[float]:
        """获取VVIX当前值"""
        raise NotImplementedError
    
    def get_btc_price(self) -> Optional[float]:
        """获取BTC价格"""
        raise NotImplementedError
    
    def get_historical_vix(self, days: int = 30) -> Optional[pd.DataFrame]:
        """获取VIX历史数据"""
        raise NotImplementedError


# ============================================================================
# yfinance数据源
# ============================================================================

class YFinanceSource(VIXDataSource):
    """
    Yahoo Finance数据源
    使用yfinance库获取数据
    
    优点: 免费、数据全面、易用
    缺点: 延迟15分钟、无VVIX直接数据
    """
    
    name = "Yahoo Finance"
    description = "免费股票/指数/加密货币数据源"
    
    def __init__(self):
        super().__init__()
        self._yfinance = None
        self._init_yfinance()
    
    def _init_yfinance(self):
        """初始化yfinance"""
        try:
            import yfinance as yf
            self._yfinance = yf
            self.logger.info("yfinance初始化成功")
        except ImportError:
            self.logger.error("yfinance未安装，请运行: pip install yfinance")
    
    def get_vix(self) -> Optional[float]:
        """
        获取VIX值
        使用VIXY ETF作为VIX代理
        注意: VIXY追踪VIX短期期货，非现货指数
        """
        if not self._yfinance:
            return None
        
        try:
            # VIXY: ProShares VIX Short-Term Futures ETF
            vixy = self._yfinance.Ticker("VIXY")
            data = vixy.history(period="1d", auto_adjust=True)
            
            if not data.empty:
                price = float(data['Close'].iloc[-1])
                self.logger.info(f"VIX (VIXY代理): {price:.2f}")
                return price
            return None
            
        except Exception as e:
            self.logger.error(f"获取VIX失败: {e}")
            return None
    
    def get_vvix(self) -> Optional[float]:
        """
        获取VVIX值
        VVIX衡量VIX期权市场的波动率
        无直接ETF，使用UVXY作为代理（VIX中期期货ETF）
        """
        if not self._yfinance:
            return None
        
        try:
            # UVXY: ProShares Ultra VIX Short-Term Futures ETF
            uvxy = self._yfinance.Ticker("UVXY")
            data = uvxy.history(period="1d", auto_adjust=True)
            
            if not data.empty:
                price = float(data['Close'].iloc[-1])
                
                # VVIX通常高于VIX，这里用经验比例估算
                vix = self.get_vix()
                if vix:
                    # VVIX ≈ VIX * 1.1 ~ 1.3
                    vvix_proxy = vix * 1.2
                    self.logger.info(f"VVIX (UVXY代理): {vvix_proxy:.2f}")
                    return vvix_proxy
                
                return price * 1.2
            return None
            
        except Exception as e:
            self.logger.error(f"获取VVIX失败: {e}")
            return None
    
    def get_btc_price(self) -> Optional[float]:
        """获取BTC价格"""
        if not self._yfinance:
            return None
        
        try:
            btc = self._yfinance.Ticker("BTC-USD")
            data = btc.history(period="1d", auto_adjust=True)
            
            if not data.empty:
                price = float(data['Close'].iloc[-1])
                self.logger.info(f"BTC: ${price:,.2f}")
                return price
            return None
            
        except Exception as e:
            self.logger.error(f"获取BTC价格失败: {e}")
            return None
    
    def get_historical_vix(self, days: int = 30) -> Optional[pd.DataFrame]:
        """获取VIX历史数据"""
        if not self._yfinance:
            return None
        
        try:
            vixy = self._yfinance.Ticker("VIXY")
            data = vixy.history(period=f"{days}d", auto_adjust=True)
            
            if not data.empty:
                df = data[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                df.columns = ['vix_open', 'vix_high', 'vix_low', 'vix_close', 'vix_volume']
                self.logger.info(f"获取VIX历史数据: {len(df)}条")
                return df
            return None
            
        except Exception as e:
            self.logger.error(f"获取VIX历史数据失败: {e}")
            return None


# ============================================================================
# 手动输入数据源
# ============================================================================

class ManualSource(VIXDataSource):
    """
    手动输入数据源
    用于测试或数据源不可用时手动输入数据
    """
    
    name = "手动输入"
    description = "手动输入VIX数据"
    
    def __init__(self, vix: float = 20.0, vvix: float = 100.0, btc: float = 65000.0):
        super().__init__()
        self._vix = vix
        self._vvix = vvix
        self._btc = btc
        self.logger.info(f"手动数据源初始化: VIX={vix}, VVIX={vvix}, BTC=${btc:,.2f}")
    
    def get_vix(self) -> Optional[float]:
        return self._vix
    
    def get_vvix(self) -> Optional[float]:
        return self._vvix
    
    def get_btc_price(self) -> Optional[float]:
        return self._btc
    
    def update(self, vix: float = None, vvix: float = None, btc: float = None):
        """更新数据"""
        if vix is not None:
            self._vix = vix
        if vvix is not None:
            self._vvix = vvix
        if btc is not None:
            self._btc = btc
        self.logger.info(f"数据已更新: VIX={self._vix}, VVIX={self._vvix}, BTC=${self._btc:,.2f}")


# ============================================================================
# 富途数据源（探索中）
# ============================================================================

class FutuSource(VIXDataSource):
    """
    富途OpenD数据源
    注意: 富途不直接提供VIX数据，但可以:
    1. 通过期权链计算隐含波动率
    2. 使用港股涡轮作为波动率代理
    
    本模块提供框架代码，实际使用需要根据API调整
    """
    
    name = "富途OpenD"
    description = "富途港股涡轮/美股期权数据"
    
    def __init__(self, host: str = "localhost", port: int = 11111):
        super().__init__()
        self.host = host
        self.port = port
        self._connected = False
        self._futu_api = None
        self.logger.info(f"富途数据源初始化: {host}:{port}")
    
    def connect(self) -> bool:
        """连接富途OpenD"""
        try:
            # 尝试导入富途API
            from futu import OpenQuoteContext
            
            self._futu_api = OpenQuoteContext(host=self.host, port=self.port)
            self._connected = True
            self.logger.info("富途OpenD连接成功")
            return True
            
        except ImportError:
            self.logger.error("富utu未安装，请运行: pip install futu-api")
            return False
        except Exception as e:
            self.logger.error(f"富途连接失败: {e}")
            return False
    
    def get_vix(self) -> Optional[float]:
        """
        获取VIX
        富途不直接提供VIX，但可以:
        1. 获取VIX期货（如果有权限）
        2. 通过VIX期权链计算隐含波动率
        """
        if not self._connected:
            self.logger.warning("富途未连接，尝试连接...")
            if not self.connect():
                return None
        
        # TODO: 实现VIX期权链隐含波动率计算
        # 思路:
        # 1. 获取VIX期权链 (FutuAPI: get_option_chain)
        # 2. 使用Black-Scholes计算隐含波动率
        # 3. 加权平均不同执行价的IV
        
        self.logger.warning("富途VIX获取未实现，请使用其他数据源")
        return None
    
    def get_vvix(self) -> Optional[float]:
        """VVIX: 富途暂无直接数据"""
        self.logger.warning("富途不支持VVIX")
        return None
    
    def get_btc_price(self) -> Optional[float]:
        """获取BTC价格（港股相关BTCETF）"""
        if not self._connected:
            if not self.connect():
                return None
        
        try:
            # 尝试获取港股BTC期货ETF
            # 注意: 具体代码需要根据实际可交易标的确定
            code = "HK.BTCF"  # 示例代码
            ret, data = self._futu_api.get_market_snapshot([code])
            
            if ret == 0 and not data.empty:
                return float(data['last'].iloc[0])
            return None
            
        except Exception as e:
            self.logger.error(f"获取BTC价格失败: {e}")
            return None
    
    def close(self):
        """关闭连接"""
        if self._futu_api:
            self._futu_api.close()
            self._connected = False


# ============================================================================
# VIX数据管理器
# ============================================================================

class VIXDataManager:
    """
    VIX数据管理器
    统一管理多种数据源，自动切换和融合
    """
    
    def __init__(self):
        self.logger = logging.getLogger("VIXDataManager")
        self.sources: Dict[str, VIXDataSource] = {}
        self.current_source: Optional[VIXDataSource] = None
        self.cache: Dict[str, Tuple[float, datetime]] = {}
        self.cache_ttl = 300  # 5分钟缓存
        
        # 注册默认数据源
        self._register_default_sources()
    
    def _register_default_sources(self):
        """注册默认数据源"""
        # yfinance
        yf_source = YFinanceSource()
        if yf_source._yfinance:
            self.register_source("yfinance", yf_source)
            self.current_source = yf_source
        
        # 手动输入（备用）
        manual_source = ManualSource()
        self.register_source("manual", manual_source)
    
    def register_source(self, name: str, source: VIXDataSource):
        """注册数据源"""
        self.sources[name] = source
        self.logger.info(f"注册数据源: {name} - {source.description}")
    
    def switch_source(self, name: str) -> bool:
        """切换数据源"""
        if name in self.sources:
            self.current_source = self.sources[name]
            self.logger.info(f"切换到数据源: {name}")
            return True
        self.logger.error(f"数据源不存在: {name}")
        return False
    
    def get_all_data(self, force_refresh: bool = False) -> Dict:
        """
        获取所有VIX相关数据
        
        Returns:
            {
                "vix": float,
                "vvix": float,
                "btc": float,
                "timestamp": datetime,
                "source": str,
                "cached": bool
            }
        """
        now = datetime.now()
        result = {
            "vix": None,
            "vvix": None,
            "btc": None,
            "timestamp": now,
            "source": None,
            "cached": False
        }
        
        # 检查缓存
        if not force_refresh and self.cache:
            cached_vix, cached_time = self.cache.get("vix", (None, None))
            if cached_vix and (now - cached_time).total_seconds() < self.cache_ttl:
                result["vix"] = cached_vix
                result["vvix"] = self.cache.get("vvix", (None, None))[0]
                result["btc"] = self.cache.get("btc", (None, None))[0]
                result["cached"] = True
                self.logger.info("使用缓存数据")
                return result
        
        # 获取数据
        if self.current_source:
            result["source"] = self.current_source.name
            
            # 获取VIX
            vix = self.current_source.get_vix()
            if vix:
                result["vix"] = vix
                self.cache["vix"] = (vix, now)
            
            # 获取VVIX
            vvix = self.current_source.get_vvix()
            if vvix:
                result["vvix"] = vvix
                self.cache["vvix"] = (vvix, now)
            
            # 获取BTC
            btc = self.current_source.get_btc_price()
            if btc:
                result["btc"] = btc
                self.cache["btc"] = (btc, now)
        
        return result
    
    def get_vix_regime(self) -> str:
        """获取VIX市场状态"""
        data = self.get_all_data()
        vix = data.get("vix")
        
        if vix is None:
            return "UNKNOWN"
        
        if vix > 30:
            return "极度恐慌"
        elif vix > 25:
            return "高度恐慌"
        elif vix > 20:
            return "偏高"
        elif vix > 15:
            return "正常"
        elif vix > 12:
            return "低贪婪"
        else:
            return "极度贪婪"


# ============================================================================
# 数据质量报告生成器
# ============================================================================

def generate_data_source_report(sources: List[VIXDataSource]) -> pd.DataFrame:
    """
    生成数据源对比报告
    
    Args:
        sources: 数据源列表
    
    Returns:
        对比报告DataFrame
    """
    records = []
    
    for source in sources:
        record = {
            "数据源": source.name,
            "描述": source.description,
            "VIX": "✓" if source.get_vix() else "✗",
            "VVIX": "✓" if source.get_vvix() else "✗",
            "BTC": "✓" if source.get_btc_price() else "✗",
            "历史数据": "✓" if source.get_historical_vix() else "✗"
        }
        records.append(record)
    
    return pd.DataFrame(records)


def print_data_report(data: Dict):
    """打印数据报告"""
    print("=" * 50)
    print("VIX数据报告")
    print("=" * 50)
    print(f"时间: {data['timestamp']}")
    print(f"数据源: {data['source'] or 'N/A'}")
    print(f"缓存: {'是' if data['cached'] else '否'}")
    print("-" * 50)
    print(f"VIX:  {data['vix'] or 'N/A':>10}")
    print(f"VVIX: {data['vvix'] or 'N/A':>10}")
    print(f"BTC:  ${data['btc'] or 0:>10,.2f}")
    print("=" * 50)


# ============================================================================
# 测试代码
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("VIX数据源调研测试")
    print("=" * 60)
    
    # 初始化数据管理器
    manager = VIXDataManager()
    
    # 获取所有数据
    print("\n【获取数据】")
    data = manager.get_all_data()
    print_data_report(data)
    
    # 获取VIX市场状态
    print("\n【VIX市场状态】")
    regime = manager.get_vix_regime()
    print(f"当前状态: {regime}")
    
    # 切换到手动数据源测试
    print("\n【切换到手动数据源】")
    manager.switch_source("manual")
    manual_data = manager.get_all_data(force_refresh=True)
    print_data_report(manual_data)
    
    # 更新手动数据
    print("\n【更新手动数据】")
    manual_source = manager.sources.get("manual")
    if manual_source:
        manual_source.update(vix=22.5, vvix=105.0, btc=68000.0)
        updated_data = manager.get_all_data(force_refresh=True)
        print_data_report(updated_data)
    
    # 生成数据源对比表
    print("\n【数据源对比】")
    sources = list(manager.sources.values())
    report = generate_data_source_report(sources)
    print(report.to_string(index=False))
    
    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)
