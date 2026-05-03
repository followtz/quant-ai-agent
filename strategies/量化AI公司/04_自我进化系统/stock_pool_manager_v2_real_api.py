# -*- coding: utf-8 -*-
"""
股票池管理器 V2 - 富途真实API版
修改: 接入富途OpenD获取真实行情数据
"""
import os, sys, json, logging
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

# UTF-8编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# 富途API导入
try:
    from futu import OpenQuoteContext, RET_OK, KLType, AuType
    FUTU_AVAILABLE = True
except ImportError:
    FUTU_AVAILABLE = False
    print("[ERROR] Futu API not installed. Run: pip install futu-api")

# ===== 路径配置 =====
SCRIPT_DIR = Path(__file__).parent
SYSTEM_ROOT = Path("C:/Users/Administrator/Desktop/量化AI公司")
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

# ===== 富途OpenD配置 =====
FUTU_HOST = '127.0.0.1'
FUTU_PORT = 11111

# ===== 日志 =====
LOG_FILE = LOG_DIR / f"stock_pool_v2_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===== 筛选标准 =====
SCREENING_CRITERIA = {
    'liquidity': {
        'min_avg_volume': 2_000_000,      # 日均成交量 >= 200万股
        'min_avg_amount': 5_000_000,      # 日均成交额 >= 500万美元
    },
    'market_cap': {
        'small_cap_min': 300_000_000,     # 小盘股 >= 3亿美元
        'mid_cap_max': 10_000_000_000     # 中盘股 <= 100亿美元
    },
    'volatility': {
        'min_hist_vol': 0.30,             # 20日历史波动率 >= 30%
    },
    'exclude': {
        'min_price': 2.0,                 # 股价 >= 2美元
    }
}

# ===== 评分权重 =====
SCORING_WEIGHTS = {
    'liquidity': 0.25,
    'volatility': 0.25,
    'strategy_fit': 0.30,
    'fundamentals': 0.10,
    'risk_control': 0.10
}

# ===== 重点关注标的 =====
PRIORITY_TARGETS = {
    'bitcoin_mining': ['US.CLSK', 'US.MARA', 'US.RIOT', 'US.HUT', 'US.CIFR', 'US.WULF'],
    'crypto_eco': ['US.COIN', 'US.MSTR', 'US.CAN'],
}

class FutuDataFetcher:
    """富途数据获取器"""
    
    def __init__(self):
        self.quote_ctx = None
        
    def connect(self):
        if not FUTU_AVAILABLE:
            logger.error("[FAIL] Futu API not available")
            return False
        
        try:
            self.quote_ctx = OpenQuoteContext(host=FUTU_HOST, port=FUTU_PORT)
            logger.info("[OK] Connected to Futu OpenD")
            return True
        except Exception as e:
            logger.error(f"[FAIL] Connect failed: {e}")
            return False
    
    def disconnect(self):
        if self.quote_ctx:
            self.quote_ctx.close()
    
    def get_snapshot(self, code):
        """获取实时行情快照"""
        if not self.quote_ctx:
            return None
        
        ret, data = self.quote_ctx.get_market_snapshot([code])
        if ret == RET_OK and data is not None and len(data) > 0:
            row = data.iloc[0]
            return {
                'price': row.get('last_price', 0),
                'volume': row.get('volume', 0),
                'turnover': row.get('turnover', 0),
                'market_cap': row.get('market_val', 0),
            }
        return None
    
    def get_kline(self, code, days=30):
        """获取K线数据计算波动率"""
        if not self.quote_ctx:
            return None
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        ret, msg, data = self.quote_ctx.request_history_kline(
            code,
            start=start_date.strftime('%Y-%m-%d'),
            end=end_date.strftime('%Y-%m-%d'),
            ktype=KLType.K_DAY,
            autype=AuType.QFQ
        )
        
        if ret == RET_OK and data is not None and len(data) > 0:
            return data
        return None
    
    def get_stock_data(self, code):
        """获取完整股票数据"""
        snapshot = self.get_snapshot(code)
        if not snapshot:
            return None
        
        # 获取波动率
        kline = self.get_kline(code, days=30)
        volatility = 0
        if kline is not None and len(kline) > 5:
            closes = kline['close'].astype(float)
            returns = closes.pct_change().dropna()
            volatility = returns.std() * np.sqrt(252)  # 年化波动率
        
        # 简化版BTC相关性（实际需要BTC价格序列计算）
        # 根据标的类型估算相关性
        btc_corr_map = {
            'CLSK': 0.72, 'MARA': 0.68, 'RIOT': 0.70, 'HUT': 0.65,
            'CIFR': 0.60, 'WULF': 0.58, 'COIN': 0.82, 'MSTR': 0.88, 'CAN': 0.55
        }
        ticker = code.split('.')[-1]
        btc_corr = btc_corr_map.get(ticker, 0.5)
        
        return {
            'price': snapshot['price'],
            'volume': snapshot['volume'] / 1e6 if snapshot['volume'] else 0,  # 百万股
            'market_cap': snapshot['market_cap'],
            'volatility': volatility,
            'btc_corr': btc_corr
        }

def screen_stock(code, data):
    """筛选检查"""
    passed = True
    reasons = []
    
    if data['volume'] < SCREENING_CRITERIA['liquidity']['min_avg_volume'] / 1e6:
        passed = False
        reasons.append(f"成交量{data['volume']:.1f}M < 2M")
    
    mc = data['market_cap']
    if mc < SCREENING_CRITERIA['market_cap']['small_cap_min']:
        passed = False
        reasons.append(f"市值${mc/1e6:.0f}M < 300M")
    
    if data['volatility'] < SCREENING_CRITERIA['volatility']['min_hist_vol']:
        passed = False
        reasons.append(f"波动率{data['volatility']*100:.0f}% < 30%")
    
    if data['price'] < SCREENING_CRITERIA['exclude']['min_price']:
        passed = False
        reasons.append(f"股价${data['price']:.2f} < $2")
    
    return passed, reasons

def score_stock(code, data):
    """评分"""
    scores = {}
    
    # 流动性评分 (25分)
    scores['liquidity'] = min(data['volume'] / 10 * 15, 15) + 10
    
    # 波动率评分 (25分)
    vol = data['volatility']
    scores['volatility'] = min(vol / 0.8 * 15, 15) + min(vol / 0.6 * 10, 10) if vol >= 0.3 else 5
    
    # 策略适配度 (30分)
    btc_corr = data['btc_corr']
    scores['strategy_fit'] = min(btc_corr / 0.8 * 15, 15) + (15 if btc_corr >= 0.6 else 10 if btc_corr >= 0.4 else 5)
    
    # 基本面 (10分)
    scores['fundamentals'] = 5 if data['market_cap'] > 1e9 else 3
    scores['fundamentals'] += 5
    
    # 风险 (10分)
    scores['risk_control'] = 10
    
    total = sum(scores[k] * SCORING_WEIGHTS[k] for k in scores)
    return total, scores

def get_grade(total):
    if total >= 80: return 'A'
    elif total >= 60: return 'B'
    elif total >= 40: return 'C'
    return 'D'

def main():
    logger.info("=" * 60)
    logger.info(f"[股票池管理器V2-真实API] 启动 | {datetime.now()}")
    logger.info("=" * 60)
    
    fetcher = FutuDataFetcher()
    if not fetcher.connect():
        return {'error': 'Futu connection failed'}
    
    try:
        all_targets = PRIORITY_TARGETS['bitcoin_mining'] + PRIORITY_TARGETS['crypto_eco']
        results = []
        
        for code in all_targets:
            logger.info(f"获取数据: {code}")
            data = fetcher.get_stock_data(code)
            
            if not data:
                logger.warning(f"  {code}: [FAIL] 无法获取数据")
                continue
            
            passed, reasons = screen_stock(code, data)
            if not passed:
                logger.info(f"  {code}: [FAIL] 未通过筛选 - {'; '.join(reasons)}")
                continue
            
            total, scores = score_stock(code, data)
            grade = get_grade(total)
            
            logger.info(f"  {code}: [OK] {grade}级 | 总分{total:.1f} | 波动率{data['volatility']*100:.0f}% | BTC相关性{data['btc_corr']:.2f}")
            
            results.append({
                'code': code,
                'grade': grade,
                'total_score': round(total, 1),
                'data': data,
                'last_check': datetime.now().isoformat()
            })
        
        # 保存结果
        output_file = SCRIPT_DIR / "stock_pool_v2_result.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"[OK] 结果已保存: {output_file}")
        
        return results
        
    finally:
        fetcher.disconnect()

if __name__ == '__main__':
    main()
