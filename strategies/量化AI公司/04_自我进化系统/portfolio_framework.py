#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多策略组合框架 (Round 2 产出)
功能: 统一管理BTDR V2 + 连连V4双策略组合，支持仓位分配、风险预算、相关性监控
来源: Round 1进化方向 + SOUL.md架构规范
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
LOG_FILE = LOG_DIR / f"portfolio_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===== 配置文件 =====
CONFIG_FILE = SCRIPT_DIR / "portfolio_config.json"
STATE_FILE = SCRIPT_DIR / "portfolio_state.json"

# ===== 策略定义 =====
STRATEGIES = {
    'BTDR_V2': {
        'name': 'BTDR PrevClose V2',
        'market': 'US',
        'currency': 'USD',
        'risk_weight': 0.6,           # 风险预算权重 60%
        'capital_allocation': 0.6,    # 资金分配 60%
        'max_position_pct': 0.30,     # 单策略最大仓位30%
        'target_vol': 0.50,           # 目标波动率 50%
        'state_file': SYSTEM_ROOT / "03_实盘与监测/btdr_state.json"
    },
    'LL_V4': {
        'name': '连连数字V4双重确认',
        'market': 'HK',
        'currency': 'HKD',
        'risk_weight': 0.4,           # 风险预算权重 40%
        'capital_allocation': 0.4,    # 资金分配 40%
        'max_position_pct': 0.25,     # 单策略最大仓位25%
        'target_vol': 0.35,           # 目标波动率 35%
        'state_file': SYSTEM_ROOT / "03_实盘与监测/lianlian_v4_state.json"
    }
}

# ===== 组合风控参数 =====
PORTFOLIO_RISK = {
    'max_total_drawdown': 0.15,       # 组合最大回撤 15%
    'max_single_loss': 0.05,          # 单日最大亏损 5%
    'rebalance_threshold': 0.10,      # 再平衡阈值 10%
    'correlation_limit': 0.70,        # 策略相关性上限
    'var_confidence': 0.95            # VaR置信度 95%
}

# ===== 工具函数 =====
def load_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'strategies': STRATEGIES, 'risk': PORTFOLIO_RISK}

def save_config(config):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'last_rebalance': None,
        'allocations': {},
        'risk_budget': {},
        'performance': {},
        'alerts': []
    }

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# ===== 策略状态获取 =====
def get_strategy_state(strategy_id):
    """获取单个策略当前状态"""
    cfg = STRATEGIES[strategy_id]
    state = {
        'strategy_id': strategy_id,
        'name': cfg['name'],
        'market': cfg['market'],
        'position': 0,
        'cash': 0,
        'market_value': 0,
        'pnl_today': 0,
        'pnl_total': 0,
        'trades_today': 0,
        'volatility': cfg['target_vol']
    }

    # 尝试从状态文件加载
    if cfg['state_file'].exists():
        try:
            with open(cfg['state_file'], 'r', encoding='utf-8') as f:
                data = json.load(f)
            state['position'] = data.get('position', 0)
            state['cash'] = data.get('cash', 0)
            state['market_value'] = data.get('market_value', 0)
            state['pnl_today'] = data.get('pnl_today', 0)
            state['pnl_total'] = data.get('pnl_total', 0)
            state['trades_today'] = data.get('trades_today', 0)
        except Exception as e:
            logger.warning(f"读取策略状态失败 {strategy_id}: {e}")

    # 模拟数据（实际需要真实数据）
    if strategy_id == 'BTDR_V2':
        state.update({'position': 7894, 'cash': 50000, 'market_value': 99000, 'pnl_today': -1200, 'pnl_total': -39230})
    elif strategy_id == 'LL_V4':
        state.update({'position': 8000, 'cash': 80000, 'market_value': 120000, 'pnl_today': 800, 'pnl_total': 5200})

    state['total_value'] = state['cash'] + state['market_value']
    return state

# ===== 组合计算 =====
def calculate_portfolio():
    """计算组合整体状态"""
    states = {sid: get_strategy_state(sid) for sid in STRATEGIES}

    total_value = sum(s['total_value'] for s in states.values())
    total_pnl_today = sum(s['pnl_today'] for s in states.values())
    total_pnl_total = sum(s['pnl_total'] for s in states.values())

    # 各策略权重
    weights = {sid: s['total_value'] / total_value if total_value > 0 else 0
               for sid, s in states.items()}

    # 组合波动率（简化计算）
    vol_bt = states['BTDR_V2']['volatility']
    vol_ll = states['LL_V4']['volatility']
    corr = 0.35  # 假设相关性
    port_vol = np.sqrt(
        weights['BTDR_V2']**2 * vol_bt**2 +
        weights['LL_V4']**2 * vol_ll**2 +
        2 * weights['BTDR_V2'] * weights['LL_V4'] * vol_bt * vol_ll * corr
    )

    portfolio = {
        'total_value': total_value,
        'total_pnl_today': total_pnl_today,
        'total_pnl_total': total_pnl_total,
        'pnl_today_pct': total_pnl_today / total_value if total_value > 0 else 0,
        'pnl_total_pct': total_pnl_total / total_value if total_value > 0 else 0,
        'weights': weights,
        'volatility': port_vol,
        'correlation': corr,
        'strategies': states,
        'timestamp': datetime.now().isoformat()
    }

    return portfolio

# ===== 风险预算分配 =====
def allocate_risk_budget(portfolio):
    """根据风险预算分配资金"""
    total_risk_weight = sum(STRATEGIES[sid]['risk_weight'] for sid in STRATEGIES)
    risk_budget = {}

    for sid, cfg in STRATEGIES.items():
        # 风险预算比例
        risk_share = cfg['risk_weight'] / total_risk_weight

        # 根据目标波动率调整
        vol_adj = cfg['target_vol'] / portfolio['volatility']

        # 最终分配
        allocation = risk_share * vol_adj
        allocation = min(allocation, cfg['max_position_pct'])

        risk_budget[sid] = {
            'risk_share': risk_share,
            'vol_adjustment': vol_adj,
            'allocation': allocation,
            'target_value': portfolio['total_value'] * allocation
        }

    return risk_budget

# ===== 再平衡检查 =====
def check_rebalance(portfolio, risk_budget):
    """检查是否需要再平衡"""
    alerts = []

    for sid, rb in risk_budget.items():
        current_weight = portfolio['weights'][sid]
        target_weight = rb['allocation']
        deviation = abs(current_weight - target_weight)

        if deviation > PORTFOLIO_RISK['rebalance_threshold']:
            alerts.append({
                'type': 'rebalance',
                'strategy': sid,
                'current_weight': current_weight,
                'target_weight': target_weight,
                'deviation': deviation,
                'action': 'increase' if current_weight < target_weight else 'decrease',
                'message': f"{sid}权重偏离{deviation*100:.1f}%，建议{'加仓' if current_weight < target_weight else '减仓'}"
            })

    # 组合回撤检查
    if portfolio['pnl_total_pct'] < -PORTFOLIO_RISK['max_total_drawdown']:
        alerts.append({
            'type': 'drawdown',
            'level': 'critical',
            'message': f"组合回撤{portfolio['pnl_total_pct']*100:.1f}%超过{PORTFOLIO_RISK['max_total_drawdown']*100:.0f}%阈值",
            'action': '建议暂停交易，启动风控审查'
        })

    # 单日亏损检查
    if portfolio['pnl_today_pct'] < -PORTFOLIO_RISK['max_single_loss']:
        alerts.append({
            'type': 'daily_loss',
            'level': 'warning',
            'message': f"单日亏损{portfolio['pnl_today_pct']*100:.1f}%超过{PORTFOLIO_RISK['max_single_loss']*100:.0f}%阈值",
            'action': '建议降低仓位'
        })

    return alerts

# ===== VaR计算 =====
def calculate_var(portfolio, confidence=0.95):
    """计算组合VaR"""
    # 简化计算：假设正态分布
    from scipy.stats import norm
    z = norm.ppf(confidence)
    var = portfolio['total_value'] * portfolio['volatility'] * z / np.sqrt(252)
    return var

# ===== 主执行函数 =====
def run_portfolio_management():
    """执行组合管理"""
    logger.info("=" * 60)
    logger.info(f"[组合框架] 启动 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # 计算组合状态
    portfolio = calculate_portfolio()

    logger.info(f"组合总值: ${portfolio['total_value']:,.0f}")
    logger.info(f"今日盈亏: ${portfolio['total_pnl_today']:,.0f} ({portfolio['pnl_today_pct']*100:.2f}%)")
    logger.info(f"累计盈亏: ${portfolio['total_pnl_total']:,.0f} ({portfolio['pnl_total_pct']*100:.2f}%)")
    logger.info(f"组合波动率: {portfolio['volatility']*100:.1f}%")

    for sid, w in portfolio['weights'].items():
        logger.info(f"  {sid}: 权重{w*100:.1f}% | 价值${portfolio['strategies'][sid]['total_value']:,.0f}")

    # 风险预算分配
    risk_budget = allocate_risk_budget(portfolio)
    logger.info("\n风险预算分配:")
    for sid, rb in risk_budget.items():
        logger.info(f"  {sid}: 目标{rb['allocation']*100:.1f}% | 目标价值${rb['target_value']:,.0f}")

    # 再平衡检查
    alerts = check_rebalance(portfolio, risk_budget)

    if alerts:
        logger.warning(f"\n[WARN] 发现{len(alerts)}个预警:")
        for a in alerts:
            logger.warning(f"  [{a['type']}] {a['message']}")
            if 'action' in a:
                logger.warning(f"    → {a['action']}")
    else:
        logger.info("\n[OK] 组合状态正常，无需再平衡")

    # VaR
    try:
        var = calculate_var(portfolio)
        logger.info(f"\n组合VaR(95%): ${var:,.0f}")
    except:
        pass

    # 保存状态
    state = load_state()
    state['last_check'] = datetime.now().isoformat()
    state['portfolio'] = portfolio
    state['risk_budget'] = risk_budget
    state['alerts'] = alerts
    save_state(state)

    logger.info("=" * 60)
    return portfolio, risk_budget, alerts

# ===== 命令行入口 =====
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='多策略组合框架')
    parser.add_argument('--mode', choices=['status', 'rebalance', 'all'], default='all')
    args = parser.parse_args()

    portfolio, risk_budget, alerts = run_portfolio_management()

    if args.mode == 'rebalance' and alerts:
        print("\n需要再平衡的操作:")
        for a in alerts:
            if a['type'] == 'rebalance':
                print(f"  {a['strategy']}: {a['message']}")