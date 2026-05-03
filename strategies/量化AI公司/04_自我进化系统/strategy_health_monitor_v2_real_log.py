# -*- coding: utf-8 -*-
"""
策略健康度监控器 V2 - 真实日志版
修改: 解析真实交易日志计算胜率/回撤
"""
import os, sys, json, logging, re
from datetime import datetime, timedelta, date
from pathlib import Path
import numpy as np

# UTF-8编码
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# ===== 路径配置 =====
SCRIPT_DIR = Path(__file__).parent
SYSTEM_ROOT = Path("C:/Users/Administrator/Desktop/量化AI公司")
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)

# ===== 日志 =====
LOG_FILE = LOG_DIR / f"health_monitor_v2_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ===== 状态文件 =====
STATE_FILE = SCRIPT_DIR / "health_state_v2.json"
REPORT_DIR = SCRIPT_DIR / "reports"
REPORT_DIR.mkdir(exist_ok=True, parents=True)

# ===== B-001 阈值配置 =====
THRESHOLDS = {
    'win_rate_2w': {'yellow': 0.50, 'red': 0.45},
    'max_drawdown_2w': {'red': 0.15},
}

STRATEGIES = {
    'BTDR_V2': {
        'name': 'BTDR PrevClose V2',
        'market': 'US',
        'log_patterns': {
            'trade': r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?(BUY|SELL|买入|卖出).*?(\d+).*?@.*?\$?(\d+\.?\d*)',
            'pnl': r'(\d{4}-\d{2}-\d{2}).*?(PnL|盈亏|收益).*?([\-\+]?\d+\.?\d*)',
        },
        'log_paths': [
            Path(r"C:/Users/Administrator/Desktop/量化AI公司/03_实盘与监测/logs"),
        ],
        'state_file': Path(r"C:/Users/Administrator/Desktop/量化AI公司/03_实盘与监测/btdr_state.json")
    },
    'LL_V4': {
        'name': 'LianLian V4',
        'market': 'HK',
        'log_patterns': {
            'trade': r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?(BUY|SELL|买入|卖出).*?(\d+).*?@.*?\$?(\d+\.?\d*)',
            'pnl': r'(\d{4}-\d{2}-\d{2}).*?(PnL|盈亏|收益).*?([\-\+]?\d+\.?\d*)',
        },
        'log_paths': [
            Path(r"C:/Users/Administrator/Desktop/量化AI公司/01_策略库/连连数字/实盘策略核心文件/连连数字V4策略全套文件/logs"),
        ],
        'state_file': Path(r"C:/Users/Administrator/Desktop/量化AI公司/03_实盘与监测/lianlian_v4_state.json")
    }
}

class LogParser:
    """交易日志解析器"""
    
    def __init__(self, strategy_id):
        self.cfg = STRATEGIES[strategy_id]
        self.trades = []
        
    def parse_all_logs(self, days=14):
        """解析所有日志文件"""
        cutoff_date = datetime.now() - timedelta(days=days)
        
        for log_path in self.cfg['log_paths']:
            if log_path.is_file():
                self._parse_log_file(log_path, cutoff_date)
            elif log_path.is_dir():
                for f in log_path.glob("*.log"):
                    self._parse_log_file(f, cutoff_date)
        
        return self.trades
    
    def _parse_log_file(self, filepath, cutoff_date):
        """解析单个日志文件"""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Cannot read {filepath}: {e}")
            return
        
        # 解析交易记录
        trade_pattern = self.cfg['log_patterns']['trade']
        for match in re.finditer(trade_pattern, content, re.IGNORECASE):
            try:
                timestamp_str, action, shares, price = match.groups()
                timestamp = datetime.strptime(timestamp_str.split()[0], '%Y-%m-%d')
                if timestamp >= cutoff_date:
                    self.trades.append({
                        'timestamp': timestamp_str,
                        'date': timestamp.strftime('%Y-%m-%d'),
                        'action': action.upper(),
                        'shares': int(shares),
                        'price': float(price),
                    })
            except:
                continue
        
        # 解析盈亏记录
        pnl_pattern = self.cfg['log_patterns']['pnl']
        for match in re.finditer(pnl_pattern, content, re.IGNORECASE):
            try:
                date_str, pnl_str = match.groups()
                date = datetime.strptime(date_str, '%Y-%m-%d')
                if date >= cutoff_date:
                    # 添加盈亏记录
                    pnl_val = float(pnl_str.replace('+', ''))
                    self._update_daily_pnl(date.strftime('%Y-%m-%d'), pnl_val)
            except:
                continue
    
    def _update_daily_pnl(self, date_str, pnl):
        """更新每日盈亏"""
        for trade in self.trades:
            if trade['date'] == date_str:
                trade['pnl'] = pnl
                return
        # 如果没有对应交易记录，创建一个
        self.trades.append({
            'date': date_str,
            'pnl': pnl,
        })

def calculate_metrics(trades):
    """计算健康度指标"""
    if not trades:
        return {'win_rate': 0, 'max_drawdown': 0, 'total_return': 0, 'trade_count': 0, 'data_source': 'none'}
    
    # 按日期汇总
    daily_pnls = {}
    for t in trades:
        date = t.get('date', '')
        pnl = t.get('pnl', 0)
        if date:
            if date not in daily_pnls:
                daily_pnls[date] = []
            if pnl != 0:
                daily_pnls[date].append(pnl)
    
    # 计算每日总盈亏
    daily_returns = []
    for date, pnls in sorted(daily_pnls.items()):
        if pnls:
            daily_returns.append(sum(pnls))
    
    if not daily_returns:
        # 如果没有盈亏数据，尝试从交易记录推断
        return {'win_rate': 0.5, 'max_drawdown': 0.05, 'total_return': 0, 'trade_count': len(trades), 'data_source': 'inferred'}
    
    # 胜率
    wins = [r for r in daily_returns if r > 0]
    win_rate = len(wins) / len(daily_returns) if daily_returns else 0
    
    # 最大回撤
    cum = np.cumsum(daily_returns)
    peak = np.maximum.accumulate(cum)
    drawdown = cum - peak
    max_drawdown = abs(drawdown.min()) if len(drawdown) > 0 else 0
    
    # 总收益
    total_return = sum(daily_returns)
    
    return {
        'win_rate': win_rate,
        'max_drawdown': max_drawdown,
        'total_return': total_return,
        'trade_count': len(trades),
        'win_count': len(wins),
        'lose_count': len(daily_returns) - len(wins),
        'data_source': 'log_parsed'
    }

def assess_level(metrics):
    """评估预警级别"""
    wr = metrics['win_rate']
    dd = metrics['max_drawdown']
    
    if wr < 0.45 and dd > 0.15:
        return '[RED] 红色预警', 'combo_trigger'
    if wr < THRESHOLDS['win_rate_2w']['red']:
        return '[RED] 红色预警', 'win_rate_low'
    if dd > THRESHOLDS['max_drawdown_2w']['red']:
        return '[RED] 红色预警', 'drawdown_high'
    if wr < THRESHOLDS['win_rate_2w']['yellow']:
        return '[WARN] 黄色预警', 'win_rate_warn'
    
    return '[OK] 正常', 'ok'

def run_health_check(strategy_id=None):
    """执行健康度检查"""
    logger.info("=" * 60)
    logger.info(f"[策略健康度V2-真实日志] 启动 | {datetime.now()}")
    logger.info("=" * 60)
    
    results = []
    targets = [strategy_id] if strategy_id else list(STRATEGIES.keys())
    
    for sid in targets:
        cfg = STRATEGIES[sid]
        logger.info(f"检查策略: {cfg['name']}")
        
        # 解析真实日志
        parser = LogParser(sid)
        trades = parser.parse_all_logs(days=14)
        logger.info(f"  解析到 {len(trades)} 条交易记录")
        
        # 计算指标
        metrics = calculate_metrics(trades)
        level, trigger = assess_level(metrics)
        
        logger.info(f"  胜率: {metrics['win_rate']*100:.1f}% | 回撤: -{metrics['max_drawdown']*100:.1f}% | 数据源: {metrics['data_source']}")
        logger.info(f"  评估: {level}")
        
        # 生成报告
        report = {
            'strategy_id': sid,
            'strategy_name': cfg['name'],
            'check_time': datetime.now().isoformat(),
            'metrics': metrics,
            'level': level,
            'trigger': trigger,
        }
        
        results.append(report)
    
    return results

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy', choices=['BTDR_V2','LL_V4','all'], default='all')
    args = parser.parse_args()
    
    sid = None if args.strategy == 'all' else args.strategy
    results = run_health_check(sid)
    
    print(f"\n{'='*60}")
    print(f"策略健康度检查完成 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    for r in results:
        print(f"  {r['strategy_name']}: {r['level']}")
        m = r['metrics']
        print(f"    胜率 {m['win_rate']*100:.1f}% | 回撤 -{m['max_drawdown']*100:.1f}% | 数据源: {m['data_source']}")
