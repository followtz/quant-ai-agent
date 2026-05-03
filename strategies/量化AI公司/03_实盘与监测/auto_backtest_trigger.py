#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
每日盘后自动回测触发机制 v1.0
==================================
- 港股16:30后触发连连V4回测
- 美股4:30(HKT)后触发BTDR回测
- 自动拉取实盘交易日志与回测结果对比
- 偏差超阈值生成预警
- 报告自动归档

用法:
    python auto_backtest_trigger.py                  # 自动模式，根据当前时间判断
    python auto_backtest_trigger.py --market HK      # 手动触发港股回测
    python auto_backtest_trigger.py --market US      # 手动触发美股回测
    python auto_backtest_trigger.py --market ALL     # 手动触发全部回测
"""

import os
import sys
import json
import logging
import argparse
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ============================================================
# 配置区
# ============================================================

BASE_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司")
STRATEGY_DIR = BASE_DIR / "01_策略库"
MONITOR_DIR = BASE_DIR / "03_实盘与监测"
LOG_DIR = BASE_DIR / "06_龙虾自动运行日志"

# 策略路径配置
STRATEGIES = {
    "BTDR": {
        "name": "BTDR PrevClose V2",
        "market": "US",
        "backtest_dir": STRATEGY_DIR / "BTDR" / "实盘策略核心文件" / "BTDR_PrevClose_Complete_Archive" / "backtest_scripts",
        "live_engine": STRATEGY_DIR / "BTDR" / "实盘策略核心文件" / "BTDR_PrevClose_Complete_Archive" / "live_engine" / "prev_close_v2_engine.py",
        "report_dir": STRATEGY_DIR / "BTDR" / "实盘策略核心文件",
        "log_pattern": "btdr_*.log",
        "trigger_time": {"hour": 4, "minute": 30},  # HKT, 美股收盘后
        "threshold": {
            "price_deviation_pct": 2.0,     # 价格偏差超2%预警
            "signal_miss_rate": 0.3,        # 信号遗漏率超30%预警
            "slippage_deviation_pct": 0.5,  # 滑点偏差超0.5%预警
        }
    },
    "LIANLIAN": {
        "name": "连连数字V4",
        "market": "HK",
        "backtest_dir": STRATEGY_DIR / "连连数字" / "实盘策略核心文件" / "连连数字V4策略全套文件",
        "live_engine": STRATEGY_DIR / "连连数字" / "实盘策略核心文件" / "连连数字V4策略全套文件" / "v4_live_engine.py",
        "report_dir": STRATEGY_DIR / "连连数字" / "实盘策略核心文件",
        "log_pattern": "v4_live_*.log",
        "trigger_time": {"hour": 16, "minute": 30},  # HKT, 港股收盘后
        "threshold": {
            "price_deviation_pct": 2.0,
            "signal_miss_rate": 0.3,
            "slippage_deviation_pct": 0.5,
        }
    }
}

# 日志配置
LOG_FILE = LOG_DIR / "auto_backtest" / f"backtest_{datetime.now().strftime('%Y%m%d')}.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 30


# ============================================================
# 工具函数
# ============================================================

def get_hkt_now() -> datetime:
    """获取当前香港时间（硬编码UTC+8，不依赖系统时区）"""
    # 简单实现：使用系统时间
    # TODO: 如需精确，使用 pytz 或 zoneinfo
    return datetime.now()


def should_trigger(strategy_key: str) -> bool:
    """判断当前时间是否应触发回测"""
    now = get_hkt_now()
    cfg = STRATEGIES[strategy_key]
    trigger_h = cfg["trigger_time"]["hour"]
    trigger_m = cfg["trigger_time"]["minute"]
    
    # 当前时间在触发时间后2小时内视为应触发
    trigger_minutes = trigger_h * 60 + trigger_m
    now_minutes = now.hour * 60 + now.minute
    
    return trigger_minutes <= now_minutes < trigger_minutes + 120


def find_trade_logs(log_dir: Path, pattern: str, date_str: str) -> List[Path]:
    """查找指定日期的交易日志"""
    logs = []
    if not log_dir.exists():
        logger.warning(f"日志目录不存在: {log_dir}")
        return logs
    
    for f in log_dir.rglob(pattern):
        if date_str in f.name:
            logs.append(f)
    
    return logs


def parse_trade_log(log_path: Path) -> List[Dict]:
    """解析交易日志，提取交易记录
    
    适配格式：每行一条JSON记录或特定格式的文本日志
    TODO: 根据实际日志格式调整解析逻辑
    """
    trades = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                # 尝试JSON格式
                try:
                    record = json.loads(line)
                    if record.get("action") in ["BUY", "SELL", "buy", "sell"]:
                        trades.append(record)
                    continue
                except json.JSONDecodeError:
                    pass
                
                # 尝试文本格式解析
                # TODO: 根据实际日志格式补充解析规则
                # 示例格式：2026-04-20 09:35:00 [TRADE] BUY BTDR @ 12.50 qty=100
                if "[TRADE]" in line or "TRADE" in line.upper():
                    parts = line.split()
                    trade = {
                        "raw": line,
                        "line_no": line_no,
                        "timestamp": parts[0] + " " + parts[1] if len(parts) >= 2 else "",
                    }
                    trades.append(trade)
                    
    except Exception as e:
        logger.error(f"解析日志失败 {log_path}: {e}")
    
    return trades


def run_backtest(strategy_key: str) -> Optional[Dict]:
    """执行回测
    
    TODO: 对接实际回测脚本，当前为框架实现
    """
    cfg = STRATEGIES[strategy_key]
    backtest_dir = cfg["backtest_dir"]
    
    if not backtest_dir.exists():
        logger.error(f"回测目录不存在: {backtest_dir}")
        return None
    
    # 查找回测脚本
    backtest_scripts = list(backtest_dir.glob("*.py"))
    if not backtest_scripts:
        logger.warning(f"未找到回测脚本: {backtest_dir}")
        return None
    
    logger.info(f"[{strategy_key}] 找到回测脚本: {[s.name for s in backtest_scripts]}")
    
    # TODO: 执行实际回测
    # 这里需要根据具体回测脚本实现调用逻辑
    # 示例：
    # import subprocess
    # result = subprocess.run(
    #     [sys.executable, str(backtest_script), "--date", date_str],
    #     capture_output=True, text=True, encoding="gbk",
    #     timeout=300
    # )
    
    backtest_result = {
        "strategy": strategy_key,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "status": "mock",  # TODO: 改为实际回测结果
        "total_trades": 0,
        "win_rate": 0.0,
        "total_pnl": 0.0,
        "max_drawdown": 0.0,
        "sharpe_ratio": 0.0,
        "signals": [],
        "note": "回测脚本尚未对接，结果为占位数据"
    }
    
    return backtest_result


def compare_live_vs_backtest(
    strategy_key: str, 
    live_trades: List[Dict], 
    backtest_result: Dict
) -> Dict:
    """对比实盘与回测结果"""
    cfg = STRATEGIES[strategy_key]
    threshold = cfg["threshold"]
    
    comparison = {
        "strategy": strategy_key,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "live_trade_count": len(live_trades),
        "backtest_trade_count": backtest_result.get("total_trades", 0),
        "alerts": [],
        "deviations": {}
    }
    
    # 信号遗漏率检查
    if backtest_result.get("total_trades", 0) > 0:
        live_count = len(live_trades)
        bt_count = backtest_result["total_trades"]
        if bt_count > 0:
            miss_rate = 1.0 - (live_count / bt_count) if live_count <= bt_count else 0.0
            comparison["deviations"]["signal_miss_rate"] = miss_rate
            if miss_rate > threshold["signal_miss_rate"]:
                comparison["alerts"].append(
                    f"⚠️ 信号遗漏率 {miss_rate:.1%} 超过阈值 {threshold['signal_miss_rate']:.1%}"
                )
    
    # TODO: 以下对比项需要实盘日志和回测结果有统一格式后实现
    # - 价格偏差对比
    # - 滑点偏差对比  
    # - 持仓时间对比
    # - 盈亏偏差对比
    
    comparison["status"] = "ALERT" if comparison["alerts"] else "OK"
    
    return comparison


def generate_report(strategy_key: str, comparison: Dict, backtest_result: Dict) -> str:
    """生成回测对比报告（Markdown格式）"""
    cfg = STRATEGIES[strategy_key]
    now = get_hkt_now()
    date_str = now.strftime("%Y-%m-%d")
    
    report = f"""# {cfg['name']} 每日回测对比报告

> 生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')} HKT
> 策略：{cfg['name']} | 市场：{cfg['market']}

---

## 一、概览

| 指标 | 实盘 | 回测 | 偏差 |
|------|------|------|------|
| 交易次数 | {comparison['live_trade_count']} | {comparison['backtest_trade_count']} | - |
| 状态 | {comparison['status']} | - | - |

## 二、预警信息

"""
    if comparison["alerts"]:
        for alert in comparison["alerts"]:
            report += f"- {alert}\n"
    else:
        report += "✅ 无预警\n"
    
    report += f"""
## 三、偏差详情

```json
{json.dumps(comparison.get('deviations', {}), indent=2, ensure_ascii=False)}
```

## 四、回测结果

```json
{json.dumps(backtest_result, indent=2, ensure_ascii=False)}
```

---

*本报告由 auto_backtest_trigger.py 自动生成*
"""
    return report


def save_report(strategy_key: str, report_content: str) -> Path:
    """保存报告到对应策略目录"""
    cfg = STRATEGIES[strategy_key]
    date_str = datetime.now().strftime("%Y%m%d")
    report_dir = cfg["report_dir"] / "backtest_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    
    safe_name = cfg["name"].replace(" ", "_")
    report_path = report_dir / f"{safe_name}_daily_{date_str}.md"
    
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)
    
    logger.info(f"[{strategy_key}] 报告已保存: {report_path}")
    return report_path


# ============================================================
# 主流程
# ============================================================

def run_single_backtest(strategy_key: str, retry_count: int = 0) -> bool:
    """执行单个策略的回测流程"""
    try:
        cfg = STRATEGIES[strategy_key]
        logger.info(f"[{strategy_key}] 开始回测流程: {cfg['name']}")
        
        # 1. 执行回测
        backtest_result = run_backtest(strategy_key)
        if backtest_result is None:
            logger.error(f"[{strategy_key}] 回测执行失败")
            return False
        
        # 2. 查找并解析实盘交易日志
        date_str = datetime.now().strftime("%Y%m%d")
        log_base = cfg["report_dir"]
        live_logs = find_trade_logs(log_base, cfg["log_pattern"], date_str)
        
        live_trades = []
        for log_path in live_logs:
            trades = parse_trade_log(log_path)
            live_trades.extend(trades)
        
        logger.info(f"[{strategy_key}] 找到实盘交易记录: {len(live_trades)}条")
        
        # 3. 对比实盘与回测
        comparison = compare_live_vs_backtest(strategy_key, live_trades, backtest_result)
        
        # 4. 生成报告
        report = generate_report(strategy_key, comparison, backtest_result)
        report_path = save_report(strategy_key, report)
        
        # 5. 预警处理
        if comparison["alerts"]:
            logger.warning(f"[{strategy_key}] 发现预警: {comparison['alerts']}")
            # TODO: 接入企业微信通知
            # TODO: 触发风控评估
        
        logger.info(f"[{strategy_key}] 回测流程完成，状态: {comparison['status']}")
        return True
        
    except Exception as e:
        logger.error(f"[{strategy_key}] 回测流程异常: {e}")
        if retry_count < MAX_RETRIES:
            logger.info(f"[{strategy_key}] {RETRY_DELAY_SECONDS}秒后重试 ({retry_count+1}/{MAX_RETRIES})")
            import time
            time.sleep(RETRY_DELAY_SECONDS)
            return run_single_backtest(strategy_key, retry_count + 1)
        else:
            logger.error(f"[{strategy_key}] 达到最大重试次数，放弃")
            return False


def main():
    parser = argparse.ArgumentParser(description="每日盘后自动回测触发机制")
    parser.add_argument("--market", choices=["HK", "US", "ALL"], default=None,
                       help="手动指定市场（HK=港股, US=美股, ALL=全部）")
    parser.add_argument("--force", action="store_true",
                       help="强制执行，忽略时间检查")
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("每日盘后自动回测触发机制 启动")
    logger.info(f"当前时间: {get_hkt_now().strftime('%Y-%m-%d %H:%M:%S')} HKT")
    logger.info("=" * 60)
    
    results = {}
    
    for strategy_key, cfg in STRATEGIES.items():
        # 判断是否应执行
        if args.market:
            if args.market != "ALL" and cfg["market"] != args.market:
                logger.info(f"[{strategy_key}] 跳过（市场不匹配: {cfg['market']} != {args.market}）")
                continue
        elif not args.force:
            if not should_trigger(strategy_key):
                logger.info(f"[{strategy_key}] 跳过（未到触发时间）")
                continue
        
        success = run_single_backtest(strategy_key)
        results[strategy_key] = "✅ 成功" if success else "❌ 失败"
    
    # 输出总结
    logger.info("=" * 60)
    logger.info("回测执行总结:")
    for k, v in results.items():
        logger.info(f"  {k}: {v}")
    logger.info("=" * 60)
    
    # 如有失败，退出码非0
    if any("失败" in v for v in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
