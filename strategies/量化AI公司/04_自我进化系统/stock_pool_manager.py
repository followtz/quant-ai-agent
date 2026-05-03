#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票池管理器 (Round 2 产出)
功能: 自动化执行备选股票池筛选、评分、入池/出池管理
来源: 01_策略库/备选股票池标准化框架.md
作者: 龙虾总控智能体 | 版本: 1.0 | 日期: 2026-04-21
"""
import os, sys, json, logging
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np

# ===== 路径与编码 =====
SCRIPT_DIR = Path(__file__).parent
SYSTEM_ROOT = Path("C:/Users/Administrator/Desktop/量化AI公司")
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('gbk')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('gbk')(sys.stderr.buffer, 'strict')

# ===== 日志 =====
LOG_FILE = LOG_DIR / f"stock_pool_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===== 数据文件 =====
POOL_FILE = SCRIPT_DIR / "stock_pool.json"
CANDIDATE_FILE = SCRIPT_DIR / "candidates.json"
HISTORY_FILE = SCRIPT_DIR / "pool_history.json"

# ===== 筛选标准 (来自备选股票池标准化框架.md) =====
SCREENING_CRITERIA = {
    'liquidity': {
        'min_avg_volume': 2_000_000,      # 日均成交量 >= 200万股
        'min_avg_amount': 5_000_000,      # 日均成交额 >= 500万美元
        'min_turnover': 0.01,             # 换手率 >= 1%
        'max_spread': 0.003               # 买卖价差 <= 0.3%
    },
    'market_cap': {
        'micro_cap_max': 300_000_000,     # 微盘股 < 3亿美元 (排除)
        'small_cap_min': 300_000_000,     # 小盘股 >= 3亿美元
        'small_cap_max': 2_000_000_000,   # 小盘股 <= 20亿美元
        'mid_cap_max': 10_000_000_000     # 中盘股 <= 100亿美元
    },
    'volatility': {
        'min_daily_range': 0.03,          # 日均振幅 >= 3%
        'min_hist_vol': 0.30,             # 20日历史波动率 >= 30%
        'min_intraday': 0.02              # 日内波幅 >= 2%
    },
    'correlation': {
        'btc_min': 0.4,                   # BTC相关性 >= 0.4
        'btdr_min': 0.3,                  # BTDR相关性 >= 0.3
        'mstr_min': 0.3                   # MSTR相关性 >= 0.3
    },
    'fundamentals': {
        'min_listing_days': 365,          # 上市时间 >= 1年
        'min_inst_holding': 0.10,         # 机构持仓 >= 10%
        'max_short_ratio': 0.30           # 做空比例 <= 30%
    },
    'exclude': {
        'min_price': 2.0,                 # 股价 >= 2美元
        'st': True,                       # 排除ST
        'reverse_split_days': 180         # 6个月内无合股
    }
}

# ===== 评分权重 =====
SCORING_WEIGHTS = {
    'liquidity': 0.25,        # 流动性 25%
    'volatility': 0.25,       # 波动率 25%
    'strategy_fit': 0.30,     # 策略适配度 30%
    'fundamentals': 0.10,     # 基本面 10%
    'risk_control': 0.10      # 风险可控性 10%
}

# ===== 重点关注标的 =====
PRIORITY_TARGETS = {
    'bitcoin_mining': ['CLSK', 'MARA', 'RIOT', 'HUT', 'CIFR', 'WULF'],
    'crypto_eco': ['COIN', 'MSTR', 'CAN'],
    'high_vol_smallcap': []  # 动态填充
}

# ===== 工具函数 =====
def load_pool():
    if POOL_FILE.exists():
        with open(POOL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'A': [], 'B': [], 'C': [], 'D': [], 'history': []}

def save_pool(pool):
    with open(POOL_FILE, 'w', encoding='utf-8') as f:
        json.dump(pool, f, ensure_ascii=False, indent=2)

def load_candidates():
    if CANDIDATE_FILE.exists():
        with open(CANDIDATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_candidates(candidates):
    with open(CANDIDATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)

# ===== 数据获取 (模拟/富途API) =====
def get_stock_data(code):
    """获取股票数据（实际应调用富途API）"""
    # 模拟数据 - 实际需要富途OpenD API
    mock_data = {
        'CLSK': {'price': 12.5, 'volume': 5_000_000, 'market_cap': 1_800_000_000, 'volatility': 0.65, 'btc_corr': 0.72},
        'MARA': {'price': 18.2, 'volume': 8_000_000, 'market_cap': 3_500_000_000, 'volatility': 0.58, 'btc_corr': 0.68},
        'RIOT': {'price': 10.8, 'volume': 6_000_000, 'market_cap': 2_200_000_000, 'volatility': 0.62, 'btc_corr': 0.70},
        'HUT': {'price': 15.3, 'volume': 3_500_000, 'market_cap': 1_500_000_000, 'volatility': 0.55, 'btc_corr': 0.65},
        'CIFR': {'price': 4.2, 'volume': 2_500_000, 'market_cap': 800_000_000, 'volatility': 0.70, 'btc_corr': 0.60},
        'WULF': {'price': 3.8, 'volume': 1_800_000, 'market_cap': 600_000_000, 'volatility': 0.75, 'btc_corr': 0.58},
        'COIN': {'price': 245.0, 'volume': 12_000_000, 'market_cap': 60_000_000_000, 'volatility': 0.45, 'btc_corr': 0.82},
        'MSTR': {'price': 420.0, 'volume': 5_500_000, 'market_cap': 85_000_000_000, 'volatility': 0.48, 'btc_corr': 0.88},
        'CAN': {'price': 6.5, 'volume': 2_000_000, 'market_cap': 1_200_000_000, 'volatility': 0.52, 'btc_corr': 0.55}
    }
    return mock_data.get(code, None)

# ===== 筛选函数 =====
def screen_stock(code, data):
    """执行筛选标准检查"""
    passed = {'liquidity': True, 'market_cap': True, 'volatility': True, 'fundamentals': True, 'exclude': True}
    reasons = []

    # 流动性检查
    if data['volume'] < SCREENING_CRITERIA['liquidity']['min_avg_volume']:
        passed['liquidity'] = False
        reasons.append(f"成交量{data['volume']:,} < 200万股")

    # 市值检查
    mc = data['market_cap']
    if mc < SCREENING_CRITERIA['market_cap']['small_cap_min']:
        passed['market_cap'] = False
        reasons.append(f"市值${mc/1e6:.0f}M < 3亿美元")
    elif mc > SCREENING_CRITERIA['market_cap']['mid_cap_max']:
        passed['market_cap'] = False
        reasons.append(f"市值${mc/1e9:.0f}B > 100亿美元")

    # 波动率检查
    if data['volatility'] < SCREENING_CRITERIA['volatility']['min_hist_vol']:
        passed['volatility'] = False
        reasons.append(f"波动率{data['volatility']*100:.0f}% < 30%")

    # 排除条件
    if data['price'] < SCREENING_CRITERIA['exclude']['min_price']:
        passed['exclude'] = False
        reasons.append(f"股价${data['price']:.2f} < 2美元")

    all_passed = all(passed.values())
    return all_passed, passed, reasons

# ===== 评分函数 =====
def score_stock(code, data):
    """计算综合评分"""
    scores = {}

    # 流动性评分 (25分)
    vol_score = min(data['volume'] / 10_000_000 * 15, 15)
    spread_score = 10  # 假设价差合理
    scores['liquidity'] = vol_score + spread_score

    # 波动率评分 (25分)
    vol = data['volatility']
    vol_score = min(vol / 0.8 * 15, 15) if vol >= 0.3 else 0
    hist_score = min(vol / 0.6 * 10, 10) if vol >= 0.4 else 0
    scores['volatility'] = vol_score + hist_score

    # 策略适配度 (30分)
    btc_corr = data.get('btc_corr', 0)
    corr_score = min(btc_corr / 0.8 * 15, 15) if btc_corr >= 0.4 else 0
    signal_score = 15 if btc_corr >= 0.6 else 10 if btc_corr >= 0.4 else 5
    scores['strategy_fit'] = corr_score + signal_score

    # 基本面 (10分)
    mc = data['market_cap']
    inst_score = 5 if mc > 1_000_000_000 else 3
    fin_score = 5
    scores['fundamentals'] = inst_score + fin_score

    # 风险可控性 (10分)
    short_score = 5  # 假设做空比例合理
    anomaly_score = 5
    scores['risk_control'] = short_score + anomaly_score

    # 加权总分
    total = sum(scores[k] * SCORING_WEIGHTS[k] for k in scores)
    return total, scores

def get_grade(total):
    """根据总分确定等级"""
    if total >= 80: return 'A'
    elif total >= 60: return 'B'
    elif total >= 40: return 'C'
    else: return 'D'

# ===== 主执行函数 =====
def run_pool_management():
    """执行股票池管理"""
    logger.info("=" * 60)
    logger.info(f"[股票池管理器] 启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    pool = load_pool()
    candidates = []

    # 扫描重点关注标的
    all_targets = PRIORITY_TARGETS['bitcoin_mining'] + PRIORITY_TARGETS['crypto_eco']
    logger.info(f"扫描标的: {', '.join(all_targets)}")

    for code in all_targets:
        data = get_stock_data(code)
        if not data:
            logger.warning(f"  {code}: 无法获取数据，跳过")
            continue

        # 筛选
        passed, details, reasons = screen_stock(code, data)
        if not passed:
            logger.info(f"  {code}: [FAIL] 未通过筛选 - {'; '.join(reasons)}")
            continue

        # 评分
        total, scores = score_stock(code, data)
        grade = get_grade(total)

        candidate = {
            'code': code,
            'grade': grade,
            'total_score': round(total, 1),
            'scores': {k: round(v, 1) for k, v in scores.items()},
            'data': data,
            'last_check': datetime.now().isoformat(),
            'status': 'pending' if grade in ['A', 'B'] else 'observe'
        }
        candidates.append(candidate)

        logger.info(f"  {code}: [OK] {grade}级 | 总分{total:.1f} | 适配度{scores['strategy_fit']:.1f} | BTC相关性{data['btc_corr']:.2f}")

    # 更新股票池
    for c in candidates:
        grade = c['grade']
        # 移除旧记录
        for g in ['A', 'B', 'C', 'D']:
            pool[g] = [p for p in pool[g] if p['code'] != c['code']]
        # 添加新记录
        pool[grade].append(c)

    save_pool(pool)
    save_candidates(candidates)

    # 汇总
    logger.info("=" * 60)
    logger.info(f"股票池更新完成:")
    logger.info(f"  A级(优先纳入): {len(pool['A'])}只 - {[c['code'] for c in pool['A']]}")
    logger.info(f"  B级(观察纳入): {len(pool['B'])}只 - {[c['code'] for c in pool['B']]}")
    logger.info(f"  C级(暂缓): {len(pool['C'])}只 - {[c['code'] for c in pool['C']]}")
    logger.info(f"  D级(排除): {len(pool['D'])}只 - {[c['code'] for c in pool['D']]}")
    logger.info("=" * 60)

    return pool

def check_exit_conditions():
    """检查出池条件"""
    pool = load_pool()
    exits = []

    for grade in ['A', 'B', 'C']:
        for stock in pool[grade]:
            # 模拟出池检查（实际需要实时数据）
            # 条件: 连续5日成交量低于门槛50%、波动率<15%、策略失效等
            data = get_stock_data(stock['code'])
            if not data:
                continue

            reasons = []
            if data['volume'] < SCREENING_CRITERIA['liquidity']['min_avg_volume'] * 0.5:
                reasons.append('流动性恶化')
            if data['volatility'] < 0.15:
                reasons.append('波动率过低')

            if reasons:
                exits.append({'code': stock['code'], 'grade': grade, 'reasons': reasons})
                logger.warning(f"[出池] {stock['code']} ({grade}级) - {', '.join(reasons)}")

    return exits

# ===== 命令行入口 =====
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='股票池管理器')
    parser.add_argument('--mode', choices=['scan', 'exit', 'all'], default='all')
    args = parser.parse_args()

    if args.mode in ['scan', 'all']:
        pool = run_pool_management()
    if args.mode in ['exit', 'all']:
        exits = check_exit_conditions()
        if exits:
            print(f"\n出池预警: {len(exits)}只")
            for e in exits:
                print(f"  {e['code']}: {', '.join(e['reasons'])}")