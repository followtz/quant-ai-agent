# -*- coding: utf-8 -*-
"""
备选股票池评分自动化脚本
========================
版本: 1.0
创建时间: 2026-04-21
功能: 基于备选股票池标准化框架自动评分候选标的

评分维度:
1. 流动性 (25%): 成交量 + 价差
2. 波动率 (25%): 日均振幅 + 历史波动率
3. 策略适配度 (30%): BTC相关性 + 信号回测胜率
4. 基本面 (10%): 机构持仓 + 财报质量
5. 风险可控性 (10%): 做空比例 + 异常波动频率

评分等级:
- A级 (≥80分): 优先纳入
- B级 (60-79分): 观察纳入
- C级 (40-59分): 暂缓
- D级 (<40分): 排除
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import json
import logging
import os

# ============================================================================
# 日志配置
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# 评分配置
# ============================================================================

@dataclass
class ScoringConfig:
    """评分配置"""
    
    # 流动性门槛
    min_volume: int = 2000000      # 最低日均成交量（股）
    ideal_volume_min: int = 5000000  # 理想日均成交量下限
    ideal_volume_max: int = 20000000 # 理想日均成交量上限
    min_turnover: float = 5000000   # 最低日均成交额（美元）
    
    # 市值门槛
    min_market_cap: float = 300000000  # 3亿美元
    max_market_cap: float = 100000000000 # 20亿美元
    
    # 波动率门槛
    min_volatility: float = 0.03      # 最低日均振幅 3%
    min_hv20: float = 0.30            # 最低20日历史波动率 30%
    
    # 相关性门槛
    min_btc_correlation: float = 0.4   # 最低BTC相关性
    min_btdr_correlation: float = 0.3  # 最低BTDR相关性
    
    # 做空比例
    max_short_ratio: float = 0.30     # 最高做空比例30%


@dataclass
class StockScore:
    """股票评分结果"""
    code: str
    name: str
    
    # 原始数据
    volume: float = 0              # 日均成交量
    turnover: float = 0             # 日均成交额
    market_cap: float = 0           # 市值（美元）
    volatility: float = 0           # 日均振幅
    hv20: float = 0                # 20日历史波动率
    btc_correlation: float = 0     # BTC相关性
    btdr_correlation: float = 0    # BTDR相关性
    short_ratio: float = 0         # 做空比例
    institution_holding: float = 0  # 机构持仓比例
    
    # 各维度得分
    liquidity_score: float = 0      # 流动性得分
    volatility_score: float = 0     # 波动率得分
    strategy_score: float = 0       # 策略适配度得分
    fundamental_score: float = 0    # 基本面得分
    risk_score: float = 0          # 风险可控性得分
    
    # 综合得分
    total_score: float = 0         # 总分
    grade: str = "D"               # 等级
    
    # 详细分析
    pass_items: List[str] = field(default_factory=list)
    fail_items: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "code": self.code,
            "name": self.name,
            "volume": self.volume,
            "turnover": self.turnover,
            "market_cap": self.market_cap,
            "volatility": self.volatility,
            "hv20": self.hv20,
            "btc_correlation": self.btc_correlation,
            "btdr_correlation": self.btdr_correlation,
            "short_ratio": self.short_ratio,
            "institution_holding": self.institution_holding,
            "liquidity_score": self.liquidity_score,
            "volatility_score": self.volatility_score,
            "strategy_score": self.strategy_score,
            "fundamental_score": self.fundamental_score,
            "risk_score": self.risk_score,
            "total_score": self.total_score,
            "grade": self.grade,
            "pass_items": self.pass_items,
            "fail_items": self.fail_items,
            "recommendations": self.recommendations
        }


# ============================================================================
# 股票评分器
# ============================================================================

class StockPoolScorer:
    """
    备选股票池评分器
    """
    
    def __init__(self, config: ScoringConfig = None):
        self.config = config or ScoringConfig()
        self.logger = logging.getLogger(__name__)
        
        # 评分权重
        self.weights = {
            "liquidity": 0.25,
            "volatility": 0.25,
            "strategy": 0.30,
            "fundamental": 0.10,
            "risk": 0.10
        }
        
        # 历史评分记录
        self.score_history: List[Dict] = []
    
    def score_stock(self, stock_data: Dict) -> StockScore:
        """
        对单只股票评分
        
        Args:
            stock_data: 股票数据字典
        
        Returns:
            StockScore对象
        """
        code = stock_data.get("code", "UNKNOWN")
        name = stock_data.get("name", code)
        
        score = StockScore(code=code, name=name)
        
        # 提取数据
        score.volume = stock_data.get("volume", 0)
        score.turnover = stock_data.get("turnover", 0)
        score.market_cap = stock_data.get("market_cap", 0)
        score.volatility = stock_data.get("volatility", 0)
        score.hv20 = stock_data.get("hv20", 0)
        score.btc_correlation = stock_data.get("btc_correlation", 0)
        score.btdr_correlation = stock_data.get("btdr_correlation", 0)
        score.short_ratio = stock_data.get("short_ratio", 0)
        score.institution_holding = stock_data.get("institution_holding", 0)
        
        # 1. 初步筛选（硬性门槛）
        self._check_hard_criteria(score)
        
        # 2. 计算各维度得分
        score.liquidity_score = self._score_liquidity(score)
        score.volatility_score = self._score_volatility(score)
        score.strategy_score = self._score_strategy(score)
        score.fundamental_score = self._score_fundamental(score)
        score.risk_score = self._score_risk(score)
        
        # 3. 计算综合得分 (直接求和，各维度满分相加=100分)
        score.total_score = (
            score.liquidity_score +
            score.volatility_score +
            score.strategy_score +
            score.fundamental_score +
            score.risk_score
        )
        
        # 4. 评定等级
        score.grade = self._get_grade(score.total_score)
        
        # 5. 生成建议
        self._generate_recommendations(score)
        
        return score
    
    def _check_hard_criteria(self, score: StockScore):
        """检查硬性门槛"""
        cfg = self.config
        
        # 流动性检查
        if score.volume >= cfg.min_volume:
            score.pass_items.append(f"成交量达标: {score.volume/1e6:.1f}M股")
        else:
            score.fail_items.append(f"成交量不足: {score.volume/1e6:.1f}M < {cfg.min_volume/1e6:.1f}M")
        
        if score.turnover >= cfg.min_turnover:
            score.pass_items.append(f"成交额达标: ${score.turnover/1e6:.1f}M")
        else:
            score.fail_items.append(f"成交额不足: ${score.turnover/1e6:.1f}M < ${cfg.min_turnover/1e6:.1f}M")
        
        # 市值检查
        if cfg.min_market_cap <= score.market_cap <= cfg.max_market_cap:
            score.pass_items.append(f"市值合规: ${score.market_cap/1e9:.1f}B")
        else:
            if score.market_cap < cfg.min_market_cap:
                score.fail_items.append(f"市值太小: ${score.market_cap/1e9:.1f}B < ${cfg.min_market_cap/1e9:.1f}B")
            else:
                score.fail_items.append(f"市值太大: ${score.market_cap/1e9:.1f}B > ${cfg.max_market_cap/1e9:.1f}B")
        
        # 波动率检查
        if score.volatility >= cfg.min_volatility:
            score.pass_items.append(f"振幅达标: {score.volatility*100:.1f}%")
        else:
            score.fail_items.append(f"振幅不足: {score.volatility*100:.1f}% < {cfg.min_volatility*100:.1f}%")
        
        if score.hv20 >= cfg.min_hv20:
            score.pass_items.append(f"HV20达标: {score.hv20*100:.1f}%")
        else:
            score.fail_items.append(f"HV20不足: {score.hv20*100:.1f}% < {cfg.min_hv20*100:.1f}%")
    
    def _score_liquidity(self, score: StockScore) -> float:
        """
        评分流动性 (满分25分)
        
        成交量15分 + 价差10分
        """
        cfg = self.config
        total = 0
        
        # 成交量评分 (15分)
        volume = score.volume
        if volume >= cfg.ideal_volume_max:
            volume_score = 15
        elif volume >= cfg.ideal_volume_min:
            # 理想范围内线性得分
            ratio = (volume - cfg.ideal_volume_min) / (cfg.ideal_volume_max - cfg.ideal_volume_min)
            volume_score = 10 + ratio * 5
        elif volume >= cfg.min_volume:
            # 达标但低于理想，按比例递减
            ratio = (volume - cfg.min_volume) / (cfg.ideal_volume_min - cfg.min_volume)
            volume_score = 5 + ratio * 5
        else:
            volume_score = 0
        
        total += volume_score
        
        # 成交额评分 (10分)
        turnover = score.turnover
        if turnover >= 50000000:  # 5000万美元
            turnover_score = 10
        elif turnover >= cfg.min_turnover:
            ratio = (turnover - cfg.min_turnover) / (50000000 - cfg.min_turnover)
            turnover_score = ratio * 10
        else:
            turnover_score = 0
        
        total += turnover_score
        
        return min(total, 25)
    
    def _score_volatility(self, score: StockScore) -> float:
        """
        评分波动率 (满分25分)
        
        日均振幅15分 + 历史波动率10分
        """
        total = 0
        
        # 日均振幅评分 (15分)
        vol = score.volatility
        if vol >= 0.08:  # 8%+
            vol_score = 15
        elif vol >= 0.06:  # 6-8%
            vol_score = 12 + (vol - 0.06) / 0.02 * 3
        elif vol >= 0.04:  # 4-6%
            vol_score = 8 + (vol - 0.04) / 0.02 * 4
        elif vol >= 0.03:  # 3-4%
            vol_score = 5 + (vol - 0.03) / 0.01 * 3
        else:
            vol_score = max(0, vol / 0.03 * 5)
        
        total += vol_score
        
        # 历史波动率评分 (10分)
        hv = score.hv20
        if hv >= 0.80:  # 80%+
            hv_score = 10
        elif hv >= 0.60:  # 60-80%
            hv_score = 8 + (hv - 0.60) / 0.20 * 2
        elif hv >= 0.40:  # 40-60%
            hv_score = 5 + (hv - 0.40) / 0.20 * 3
        elif hv >= 0.30:  # 30-40%
            hv_score = 3 + (hv - 0.30) / 0.10 * 2
        else:
            hv_score = max(0, hv / 0.30 * 3)
        
        total += hv_score
        
        return min(total, 25)
    
    def _score_strategy(self, score: StockScore) -> float:
        """
        评分策略适配度 (满分30分)
        
        BTC相关性15分 + BTDR相关性15分
        """
        cfg = self.config
        total = 0
        
        # BTC相关性评分 (15分)
        btc_corr = score.btc_correlation
        if btc_corr >= 0.8:
            btc_score = 15
        elif btc_corr >= 0.6:
            btc_score = 12 + (btc_corr - 0.6) / 0.2 * 3
        elif btc_corr >= cfg.min_btc_correlation:
            btc_score = 8 + (btc_corr - cfg.min_btc_correlation) / (0.6 - cfg.min_btc_correlation) * 4
        else:
            btc_score = max(0, btc_corr / cfg.min_btc_correlation * 8)
        
        total += btc_score
        
        # BTDR相关性评分 (15分)
        btdr_corr = score.btdr_correlation
        if btdr_corr >= 0.7:
            btdr_score = 15
        elif btdr_corr >= 0.5:
            btdr_score = 10 + (btdr_corr - 0.5) / 0.2 * 5
        elif btdr_corr >= cfg.min_btdr_correlation:
            btdr_score = 5 + (btdr_corr - cfg.min_btdr_correlation) / (0.5 - cfg.min_btdr_correlation) * 5
        else:
            btdr_score = max(0, btdr_corr / cfg.min_btdr_correlation * 5)
        
        total += btdr_score
        
        return min(total, 30)
    
    def _score_fundamental(self, score: StockScore) -> float:
        """
        评分基本面 (满分10分)
        
        机构持仓5分 + 财报质量5分
        """
        total = 0
        
        # 机构持仓评分 (5分)
        inst = score.institution_holding
        if inst >= 0.50:  # 50%+
            inst_score = 5
        elif inst >= 0.30:
            inst_score = 3 + (inst - 0.30) / 0.20 * 2
        elif inst >= 0.10:
            inst_score = 1 + (inst - 0.10) / 0.20 * 2
        else:
            inst_score = max(0, inst / 0.10 * 1)
        
        total += inst_score
        
        # 财报质量 (简化评分，5分)
        # 实际应用中应该检查财报发布规律、审计意见等
        fundamental_score = 5  # 默认满分，需要扩展时检查
        
        total += fundamental_score
        
        return min(total, 10)
    
    def _score_risk(self, score: StockScore) -> float:
        """
        评分风险可控性 (满分10分)
        
        做空比例5分 + 异常波动频率5分
        """
        cfg = self.config
        total = 0
        
        # 做空比例评分 (5分)
        short = score.short_ratio
        if short <= 0.10:  # 10%以下
            short_score = 5
        elif short <= 0.20:
            short_score = 4 - (short - 0.10) / 0.10 * 1
        elif short <= cfg.max_short_ratio:
            short_score = 3 - (short - 0.20) / (cfg.max_short_ratio - 0.20) * 1.5
        else:
            short_score = max(0, 1.5 - (short - cfg.max_short_ratio) * 5)
        
        total += short_score
        
        # 异常波动频率 (简化评分，5分)
        # 实际应用中应该检查历史异常波动记录
        # 默认满分
        total += 5
        
        return min(total, 10)
    
    def _get_grade(self, score: float) -> str:
        """根据分数评定等级"""
        if score >= 80:
            return "A级-优先纳入"
        elif score >= 60:
            return "B级-观察纳入"
        elif score >= 40:
            return "C级-暂缓"
        else:
            return "D级-排除"
    
    def _generate_recommendations(self, score: StockScore):
        """生成建议"""
        # 根据评分生成建议
        if score.total_score >= 80:
            score.recommendations.append("优先启动影子模式验证")
        
        if score.liquidity_score >= 20:
            score.recommendations.append("流动性优秀，适合大资金")
        
        if score.volatility_score >= 20:
            score.recommendations.append("波动率优秀，日内交易机会多")
        
        if score.strategy_score >= 25:
            score.recommendations.append("策略适配度极高，PrevClose规律可能存在")
        
        if score.btc_correlation >= 0.6:
            score.recommendations.append("BTC联动性强，适合BTC相关策略")
        
        # 根据不足项给出建议
        if score.liquidity_score < 15:
            score.recommendations.append("注意流动性风险，控制仓位")
        
        if score.volatility_score < 15:
            score.recommendations.append("波动率偏低，考虑期权策略")
        
        if score.short_ratio > 0.25:
            score.recommendations.append("做空比例偏高，注意逼空风险")
    
    def score_multiple(self, stocks_data: List[Dict]) -> pd.DataFrame:
        """
        对多只股票评分
        
        Args:
            stocks_data: 股票数据列表
        
        Returns:
            评分结果DataFrame
        """
        results = []
        
        for stock in stocks_data:
            score = self.score_stock(stock)
            results.append(score.to_dict())
            
            # 记录历史
            self.score_history.append({
                "timestamp": datetime.now().isoformat(),
                **score.to_dict()
            })
        
        df = pd.DataFrame(results)
        
        # 按总分排序
        df = df.sort_values("total_score", ascending=False)
        
        return df


# ============================================================================
# 示例股票数据
# ============================================================================

SAMPLE_STOCKS = [
    {
        "code": "MSTR",
        "name": "MicroStrategy",
        "volume": 3000000,
        "turnover": 80000000,
        "market_cap": 40000000000,
        "volatility": 0.08,
        "hv20": 0.85,
        "btc_correlation": 0.88,
        "btdr_correlation": 0.75,
        "short_ratio": 0.15,
        "institution_holding": 0.45
    },
    {
        "code": "CLSK",
        "name": "CleanSpark",
        "volume": 8000000,
        "turnover": 25000000,
        "market_cap": 1800000000,
        "volatility": 0.06,
        "hv20": 0.60,
        "btc_correlation": 0.65,
        "btdr_correlation": 0.55,
        "short_ratio": 0.20,
        "institution_holding": 0.35
    },
    {
        "code": "MARA",
        "name": "Marathon Digital",
        "volume": 12000000,
        "turnover": 35000000,
        "market_cap": 1500000000,
        "volatility": 0.05,
        "hv20": 0.55,
        "btc_correlation": 0.60,
        "btdr_correlation": 0.50,
        "short_ratio": 0.28,
        "institution_holding": 0.40
    },
    {
        "code": "RIOT",
        "name": "Riot Platforms",
        "volume": 15000000,
        "turnover": 28000000,
        "market_cap": 1200000000,
        "volatility": 0.05,
        "hv20": 0.50,
        "btc_correlation": 0.55,
        "btdr_correlation": 0.48,
        "short_ratio": 0.32,
        "institution_holding": 0.38
    },
    {
        "code": "WULF",
        "name": "TeraWulf",
        "volume": 5000000,
        "turnover": 9000000,
        "market_cap": 500000000,
        "volatility": 0.075,
        "hv20": 0.70,
        "btc_correlation": 0.50,
        "btdr_correlation": 0.42,
        "short_ratio": 0.18,
        "institution_holding": 0.25
    },
    {
        "code": "HUT",
        "name": "Hut 8 Corp",
        "volume": 6000000,
        "turnover": 12000000,
        "market_cap": 800000000,
        "volatility": 0.065,
        "hv20": 0.60,
        "btc_correlation": 0.50,
        "btdr_correlation": 0.40,
        "short_ratio": 0.15,
        "institution_holding": 0.30
    },
    {
        "code": "COIN",
        "name": "Coinbase",
        "volume": 8000000,
        "turnover": 150000000,
        "market_cap": 50000000000,
        "volatility": 0.04,
        "hv20": 0.45,
        "btc_correlation": 0.70,
        "btdr_correlation": 0.60,
        "short_ratio": 0.10,
        "institution_holding": 0.55
    },
    {
        "code": "CIFR",
        "name": "Cipher Mining",
        "volume": 4000000,
        "turnover": 8000000,
        "market_cap": 600000000,
        "volatility": 0.06,
        "hv20": 0.65,
        "btc_correlation": 0.55,
        "btdr_correlation": 0.45,
        "short_ratio": 0.22,
        "institution_holding": 0.20
    }
]


# ============================================================================
# 测试和报告生成
# ============================================================================

def print_score_report(df: pd.DataFrame):
    """打印评分报告"""
    print("=" * 80)
    print("备选股票池评分报告")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)
    
    for idx, row in df.iterrows():
        print(f"\n{'─' * 80}")
        print(f"【{row['code']}】{row['name']} | 总分: {row['total_score']:.1f} | {row['grade']}")
        print(f"{'─' * 80}")
        
        print(f"  [数据] 原始数据:")
        print(f"     成交量: {row['volume']/1e6:.1f}M股 | 成交额: ${row['turnover']/1e6:.1f}M")
        print(f"     市值: ${row['market_cap']/1e9:.1f}B | 振幅: {row['volatility']*100:.1f}%")
        print(f"     HV20: {row['hv20']*100:.1f}% | BTC相关性: {row['btc_correlation']:.2f}")
        print(f"     BTDR相关性: {row['btdr_correlation']:.2f} | 做空比例: {row['short_ratio']*100:.1f}%")
        
        print(f"\n  [得分] 各维度得分:")
        print(f"     流动性: {row['liquidity_score']:.1f}/25 | 波动率: {row['volatility_score']:.1f}/25")
        print(f"     策略适配: {row['strategy_score']:.1f}/30 | 基本面: {row['fundamental_score']:.1f}/10")
        print(f"     风险可控: {row['risk_score']:.1f}/10")
        
        if row['pass_items']:
            print(f"\n  [OK] 通过项:")
            for item in row['pass_items']:
                print(f"     * {item}")
        
        if row['fail_items']:
            print(f"\n  [X] 未通过项:")
            for item in row['fail_items']:
                print(f"     * {item}")
        
        if row['recommendations']:
            print(f"\n  [建议] 建议:")
            for rec in row['recommendations']:
                print(f"     >> {rec}")
    
    print(f"\n{'=' * 80}")
    print("汇总统计")
    print("=" * 80)
    grade_counts = df['grade'].value_counts()
    print(f"  A级(优先纳入): {grade_counts.get('A级-优先纳入', 0)} 只")
    print(f"  B级(观察纳入): {grade_counts.get('B级-观察纳入', 0)} 只")
    print(f"  C级(暂缓): {grade_counts.get('C级-暂缓', 0)} 只")
    print(f"  D级(排除): {grade_counts.get('D级-排除', 0)} 只")


def save_report(df: pd.DataFrame, filepath: str):
    """保存报告到文件"""
    df.to_excel(filepath, sheet_name='评分详情', index=False)
    
    # 同时保存JSON
    json_path = filepath.replace('.xlsx', '.json')
    records = df.to_dict('records')
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2)
    
    logger.info(f"报告已保存: {filepath}, {json_path}")


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("备选股票池评分自动化脚本")
    print("=" * 60)
    
    # 创建评分器
    scorer = StockPoolScorer()
    
    # 评分示例股票
    print("\n正在评分候选股票池...")
    df = scorer.score_multiple(SAMPLE_STOCKS)
    
    # 打印报告
    print_score_report(df)
    
    # 保存报告
    output_dir = r"C:\Users\Administrator\Desktop\量化AI公司\01_策略库"
    os.makedirs(output_dir, exist_ok=True)
    
    excel_path = os.path.join(output_dir, "备选股票池评分报告.xlsx")
    save_report(df, excel_path)
    
    print(f"\n[OK] 评分完成！报告已保存至:")
    print(f"   Excel: {excel_path}")
    print(f"   JSON: {excel_path.replace('.xlsx', '.json')}")
