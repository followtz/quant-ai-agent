# -*- coding: utf-8 -*-
"""
连连数字V4策略回测 - ML增强对比
任务2: 对比原始ML vs 增强ML(FinRL风格集成)的回测表现

回测内容:
1. V4原始策略 (单一RF模型, 置信度0.5)
2. V4增强策略 (RF+GBM+LR集成, 置信度0.55)
3. 仅均值回归基准
4. Buy&Hold基准

输出: 回测结果 + 详细交易日志
"""
import sys
import os
import json
import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV

# Windows encoding fix
if sys.platform == 'win32':
    import codecs
    try:
        sys.stdout = codecs.getwriter('gbk')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('gbk')(sys.stderr.buffer, 'strict')
    except:
        pass

# ============== 配置 ==============
SCRIPT_DIR = Path(__file__).parent
RESULT_DIR = Path(r"C:\Users\Administrator\Desktop\量化AI公司\02_回测数据\每日新回测")
RESULT_DIR.mkdir(exist_ok=True, parents=True)

STOCK_CODE = "HK.02598"
STOCK_NAME = "连连数字"

# 策略参数
V3_THRESHOLD = 0.03  # V3阈值 (20260420优化: 5%→3%)
MA_LOOKBACK = 20
MR_THRESHOLD = 2.0   # 均值回归Z-Score阈值
ML_CONFIDENCE_ORIG = 0.5    # 原始ML置信度
ML_CONFIDENCE_ENHANCED = 0.55  # 增强ML置信度
CONFIRMATION_COUNT = 2  # 双重确认
BASE_POSITION = 8000
MIN_POSITION = 6000
MAX_POSITION = 10000
TRADE_QTY = 1000
INITIAL_CASH = 100000

# 回测参数
BACKTEST_DAYS = 180  # 回测6个月
COMMISSION = 0.001   # 手续费0.1%

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def fetch_data_from_futu(days=200):
    """从富途API获取历史数据"""
    try:
        from futu import OpenQuoteContext, KLType, AuType, RET_OK
        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        end_str = datetime.now().strftime('%Y-%m-%d')
        start_str = (datetime.now() - timedelta(days=days + 30)).strftime('%Y-%m-%d')
        ret_code, ret_msg, data = ctx.request_history_kline(
            STOCK_CODE, start=start_str, end=end_str,
            ktype=KLType.K_DAY, autype=AuType.QFQ
        )
        ctx.close()
        
        # Futu OpenD v10.x: 数据可能在ret_msg或data中
        import pandas as pd
        raw = None
        if isinstance(ret_msg, pd.DataFrame) and not ret_msg.empty:
            raw = ret_msg
        elif data is not None and not data.empty:
            raw = data
        
        if raw is not None and len(raw) > 10:
            logger.info(f"[Futu] 获取 {len(raw)} 条K线数据, columns: {list(raw.columns)}")
            df = raw.rename(columns={'time_key': 'date'})
            # 确保必要列存在
            required = ['date', 'open', 'close', 'high', 'low']
            for col in required:
                if col not in df.columns:
                    logger.warning(f"[Futu] 缺少列: {col}")
                    return None
            df['date'] = pd.to_datetime(df['date'])
            # 确保有volume列
            if 'volume' not in df.columns:
                df['volume'] = 0
            df = df[['date', 'open', 'close', 'high', 'low', 'volume']].copy()
            result = df.sort_values('date').reset_index(drop=True)
            logger.info(f"[Futu] 处理后 {len(result)} 条数据, 价格范围: {result['close'].min():.2f}~{result['close'].max():.2f}")
            return result
        else:
            logger.warning(f"[Futu] 无有效数据 (ret_code={ret_code})")
    except Exception as e:
        logger.warning(f"[Futu] 连接异常: {e}")
    return None


def generate_realistic_data(days=200):
    """
    生成符合连连数字(02598.HK)特征的模拟数据
    基于实际价格区间(8-25 HKD)和波动率
    """
    np.random.seed(2026)
    dates = pd.date_range(end=datetime.now(), periods=days, freq='B')
    n = len(dates)
    
    # 初始价格 ~20 HKD, 带均值回归特征
    price = np.zeros(n)
    price[0] = 20.0
    mu = 18.0  # 均值回归水平
    theta = 0.02  # 回归速度
    sigma = 0.03  # 日波动率
    
    for i in range(1, n):
        # Ornstein-Uhlenbeck过程 (均值回归)
        dp = theta * (mu - price[i-1]) + sigma * price[i-1] * np.random.randn()
        price[i] = max(price[i-1] * (1 + dp / price[i-1]), 5.0)
    
    # 添加真实的波动率聚类
    vol = np.zeros(n)
    vol[0] = 0.03
    for i in range(1, n):
        vol[i] = 0.7 * vol[i-1] + 0.3 * (0.02 + 0.02 * np.random.rand())
    
    # 重新生成价格使用时变波动率
    price2 = np.zeros(n)
    price2[0] = 20.0
    for i in range(1, n):
        dp = theta * (mu - price2[i-1]) + vol[i] * price2[i-1] * np.random.randn()
        price2[i] = max(price2[i-1] + dp, 5.0)
    
    df = pd.DataFrame({
        'date': dates,
        'open': price2 + np.random.randn(n) * 0.1,
        'high': price2 + np.abs(np.random.randn(n)) * 0.3,
        'low': price2 - np.abs(np.random.randn(n)) * 0.3,
        'close': price2,
        'volume': np.random.randint(500000, 5000000, n)
    })
    
    return df


def calculate_features(df):
    """计算所有技术指标和特征"""
    df = df.copy()
    
    # 基础特征
    df['returns'] = df['close'].pct_change()
    df['ma_5'] = df['close'].rolling(5).mean()
    df['ma_10'] = df['close'].rolling(10).mean()
    df['ma_20'] = df['close'].rolling(MA_LOOKBACK).mean()
    df['std_20'] = df['close'].rolling(MA_LOOKBACK).std()
    
    # 价格偏离均线
    df['price_vs_ma20'] = (df['close'] - df['ma_20']) / df['ma_20']
    df['price_vs_ma5'] = (df['close'] - df['ma_5']) / df['ma_5']
    df['price_vs_ma10'] = (df['close'] - df['ma_10']) / df['ma_10']
    
    # 均值回归Z-Score
    df['zscore'] = (df['close'] - df['ma_20']) / df['std_20']
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss))
    
    # MACD
    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    
    # 布林带
    df['bb_upper'] = df['ma_20'] + 2 * df['std_20']
    df['bb_lower'] = df['ma_20'] - 2 * df['std_20']
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    # V4增强特征
    df['volatility_5d'] = df['returns'].rolling(5).std()
    df['volatility_20d'] = df['returns'].rolling(20).std()
    df['momentum_5d'] = df['close'].pct_change(5)
    df['momentum_10d'] = df['close'].pct_change(10)
    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']
    df['vix_proxy'] = df['volatility_20d'] * 100
    df['volatility_regime'] = pd.cut(
        df['volatility_20d'], bins=[-np.inf, 0.02, 0.05, np.inf], labels=[0, 1, 2]
    ).astype(float)
    
    return df


def generate_target(df, forward_days=3, threshold=0.02):
    """生成目标变量"""
    future_return = df['close'].shift(-forward_days) / df['close'] - 1
    df['target'] = 0
    df.loc[future_return > threshold, 'target'] = 1
    df.loc[future_return < -threshold, 'target'] = -1
    return df


# ============== 原始ML模型 (单一RF) ==============
class OriginalML:
    """V4原始ML: 单一RandomForest"""
    
    def __init__(self, confidence=ML_CONFIDENCE_ORIG):
        self.confidence = confidence
        self.model = RandomForestClassifier(
            n_estimators=50, max_depth=6, min_samples_split=5, random_state=42
        )
        self.scaler = StandardScaler()
        self.trained = False
        self.features = ['returns', 'rsi', 'macd', 'macd_signal', 'zscore', 'bb_position']
    
    def train(self, df):
        df = df.dropna(subset=self.features + ['target'])
        if len(df) < 30:
            return False
        X = self.scaler.fit_transform(df[self.features].values)
        y = df['target'].values
        self.model.fit(X, y)
        self.trained = True
        return True
    
    def predict(self, row):
        if not self.trained:
            return 0, 0.5
        X = self.scaler.transform(row[self.features].values.reshape(1, -1))
        pred = self.model.predict(X)[0]
        proba = self.model.predict_proba(X)[0]
        classes = list(self.model.classes_)
        up_prob = proba[classes.index(1)] if 1 in classes else 0.33
        down_prob = proba[classes.index(-1)] if -1 in classes else 0.33
        
        buy = up_prob > self.confidence
        sell = down_prob > self.confidence
        direction = 1 if buy else (-1 if sell else 0)
        confidence = max(up_prob, down_prob) if direction != 0 else 0.5
        return direction, confidence


# ============== 增强ML模型 (RF+GBM+LR集成) ==============
class EnhancedML:
    """V4增强ML: FinRL风格集成模型"""
    
    def __init__(self, confidence=ML_CONFIDENCE_ENHANCED):
        self.confidence = confidence
        self.models = {
            'rf': RandomForestClassifier(
                n_estimators=100, max_depth=8, min_samples_split=5, random_state=42
            ),
            'gbm': GradientBoostingClassifier(
                n_estimators=100, max_depth=6, learning_rate=0.05, random_state=42
            ),
            'lr': CalibratedClassifierCV(
                LogisticRegression(max_iter=1000, random_state=42), cv=3
            )
        }
        self.scaler = StandardScaler()
        self.trained = False
        self.features = [
            'returns', 'rsi', 'macd', 'macd_signal', 'zscore', 'bb_position',
            'volatility_5d', 'volatility_20d', 'momentum_5d', 'momentum_10d',
            'volume_ratio', 'price_vs_ma5', 'price_vs_ma20',
            'vix_proxy', 'volatility_regime'
        ]
        self.feature_importance = {}
    
    def train(self, df):
        available = [f for f in self.features if f in df.columns]
        df = df.dropna(subset=available + ['target'])
        if len(df) < 30:
            return False
        X = self.scaler.fit_transform(df[available].values)
        y = df['target'].values
        
        for name, model in self.models.items():
            try:
                model.fit(X, y)
            except Exception as e:
                logger.warning(f"  {name} training failed: {e}")
        
        # 特征重要性
        if hasattr(self.models['rf'], 'feature_importances_'):
            self.feature_importance = dict(zip(available, self.models['rf'].feature_importances_))
        
        self.trained = True
        self._available_features = available
        return True
    
    def predict(self, row):
        if not self.trained:
            return 0, 0.5
        available = [f for f in self.features if f in row.index]
        X = self.scaler.transform(row[available].values.reshape(1, -1))
        
        votes = []
        probas = []
        for name, model in self.models.items():
            pred = model.predict(X)[0]
            proba = model.predict_proba(X)[0]
            votes.append(pred)
            probas.append(proba)
        
        avg_proba = np.mean(probas, axis=0)
        classes = list(self.models['rf'].classes_)
        up_prob = avg_proba[classes.index(1)] if 1 in classes else 0.33
        down_prob = avg_proba[classes.index(-1)] if -1 in classes else 0.33
        
        # 多数投票
        buy = up_prob > self.confidence
        sell = down_prob > self.confidence
        direction = 1 if buy else (-1 if sell else 0)
        confidence = max(up_prob, down_prob) if direction != 0 else 0.5
        return direction, confidence


# ============== 回测引擎 ==============
class BacktestEngine:
    """通用回测引擎"""
    
    def __init__(self, name, initial_cash=INITIAL_CASH):
        self.name = name
        self.cash = initial_cash
        self.position = BASE_POSITION
        self.initial_price = None
        self.trades = []
        self.equity_curve = []
        self.max_equity = initial_cash
        self.max_drawdown = 0
    
    def get_equity(self, price):
        return self.cash + self.position * price
    
    def execute_buy(self, price, date, qty=TRADE_QTY):
        actual_qty = min(qty, MAX_POSITION - self.position, int(self.cash / price / 100) * 100)
        if actual_qty < 100:
            return False
        cost = actual_qty * price * (1 + COMMISSION)
        if cost > self.cash:
            actual_qty = int(self.cash / price / (1 + COMMISSION) / 100) * 100
            if actual_qty < 100:
                return False
            cost = actual_qty * price * (1 + COMMISSION)
        self.position += actual_qty
        self.cash -= cost
        self.trades.append({
            'date': str(date.date()) if hasattr(date, 'date') else str(date),
            'action': 'BUY',
            'qty': actual_qty,
            'price': price,
            'commission': actual_qty * price * COMMISSION
        })
        return True
    
    def execute_sell(self, price, date, qty=TRADE_QTY):
        actual_qty = min(qty, self.position - MIN_POSITION)
        if actual_qty < 100:
            return False
        revenue = actual_qty * price * (1 - COMMISSION)
        self.position -= actual_qty
        self.cash += revenue
        self.trades.append({
            'date': str(date.date()) if hasattr(date, 'date') else str(date),
            'action': 'SELL',
            'qty': actual_qty,
            'price': price,
            'commission': actual_qty * price * COMMISSION
        })
        return True
    
    def record_equity(self, date, price):
        equity = self.get_equity(price)
        self.equity_curve.append({'date': date, 'equity': equity, 'price': price})
        if equity > self.max_equity:
            self.max_equity = equity
        dd = (self.max_equity - equity) / self.max_equity
        if dd > self.max_drawdown:
            self.max_drawdown = dd
    
    def get_stats(self, final_price):
        equity = self.get_equity(final_price)
        initial_equity = INITIAL_CASH + BASE_POSITION * (self.initial_price or final_price)
        total_return = (equity - initial_equity) / initial_equity
        
        wins = [t for t in self.trades[::2] if len(self.trades) > self.trades.index(t) + 1]
        win_count = 0
        total_count = 0
        for i in range(0, len(self.trades) - 1, 2):
            if i + 1 < len(self.trades):
                buy = self.trades[i]
                sell = self.trades[i + 1]
                if buy['action'] == 'BUY' and sell['action'] == 'SELL':
                    total_count += 1
                    if sell['price'] > buy['price']:
                        win_count += 1
        
        win_rate = win_count / total_count if total_count > 0 else 0
        
        return {
            'name': self.name,
            'total_return': f"{total_return*100:+.2f}%",
            'total_return_pct': total_return * 100,
            'max_drawdown': f"-{self.max_drawdown*100:.2f}%",
            'max_drawdown_pct': self.max_drawdown * 100,
            'total_trades': len(self.trades),
            'round_trips': total_count,
            'win_rate': f"{win_rate*100:.1f}%",
            'win_rate_pct': win_rate * 100,
            'final_equity': f"${equity:,.2f}",
            'final_position': self.position,
            'final_cash': f"${self.cash:,.2f}"
        }


def run_backtest_strategy(df, ml_model, name, use_enhanced_features=False):
    """运行单策略回测"""
    engine = BacktestEngine(name)
    
    # 准备数据
    df = calculate_features(df)
    df = generate_target(df)
    
    # 训练窗口: 前60天
    train_window = 60
    
    logger.info(f"\n{'='*60}")
    logger.info(f"Running backtest: {name}")
    logger.info(f"{'='*60}")
    
    for i in range(train_window, len(df) - 3):
        train_df = df.iloc[max(0, i-120):i].copy()  # 使用120天滚动窗口训练
        current_row = df.iloc[i]
        current_price = current_row['close']
        current_date = current_row['date']
        
        if i == train_window:
            engine.initial_price = current_price
        
        # 记录权益
        engine.record_equity(current_date, current_price)
        
        # 每20天重训练
        if i == train_window or (i - train_window) % 20 == 0:
            ml_model.train(train_df)
        
        # === 信号生成 ===
        # V3信号
        v3_buy = current_row['price_vs_ma20'] < -V3_THRESHOLD
        v3_sell = current_row['price_vs_ma20'] > V3_THRESHOLD
        
        # 均值回归信号
        mr_buy = current_row['zscore'] < -MR_THRESHOLD
        mr_sell = current_row['zscore'] > MR_THRESHOLD
        
        # ML信号
        ml_direction, ml_conf = ml_model.predict(current_row)
        ml_buy = ml_direction == 1
        ml_sell = ml_direction == -1
        
        # 双重确认
        buy_signals = sum([v3_buy, mr_buy, ml_buy])
        sell_signals = sum([v3_sell, mr_sell, ml_sell])
        
        final_buy = buy_signals >= CONFIRMATION_COUNT
        final_sell = sell_signals >= CONFIRMATION_COUNT
        
        # 执行交易
        if final_buy and engine.position < MAX_POSITION:
            engine.execute_buy(current_price, current_date)
        elif final_sell and engine.position > MIN_POSITION:
            engine.execute_sell(current_price, current_date)
    
    # 最终统计
    final_price = df.iloc[-3]['close']
    engine.record_equity(df.iloc[-3]['date'], final_price)
    stats = engine.get_stats(final_price)
    
    return stats, engine.trades, engine.equity_curve


def run_buyhold_backtest(df):
    """Buy&Hold基准"""
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    initial_equity = INITIAL_CASH + BASE_POSITION * start_price
    final_equity = INITIAL_CASH + BASE_POSITION * end_price
    total_return = (final_equity - initial_equity) / initial_equity
    
    return {
        'name': 'Buy&Hold',
        'total_return': f"{total_return*100:+.2f}%",
        'total_return_pct': total_return * 100,
        'total_trades': 0,
        'note': '基准策略'
    }


def run_meanreversion_only_backtest(df):
    """仅均值回归策略"""
    engine = BacktestEngine("MeanReversion Only")
    df = calculate_features(df)
    
    train_window = 30
    for i in range(train_window, len(df) - 3):
        current_row = df.iloc[i]
        current_price = current_row['close']
        current_date = current_row['date']
        
        if i == train_window:
            engine.initial_price = current_price
        
        engine.record_equity(current_date, current_price)
        
        # 仅均值回归信号
        if current_row['zscore'] < -MR_THRESHOLD and engine.position < MAX_POSITION:
            engine.execute_buy(current_price, current_date)
        elif current_row['zscore'] > MR_THRESHOLD and engine.position > MIN_POSITION:
            engine.execute_sell(current_price, current_date)
    
    final_price = df.iloc[-3]['close']
    stats = engine.get_stats(final_price)
    return stats


def main():
    logger.info("=" * 70)
    logger.info("V4 ML Enhancement Backtest - Task 2")
    logger.info("=" * 70)
    
    # 1. 获取数据
    logger.info("[1/5] Fetching data...")
    df = fetch_data_from_futu(days=220)
    data_source = 'Futu API'
    if df is None or len(df) < 60:
        logger.info("  Using simulated data (Futu unavailable)")
        df = generate_realistic_data(days=220)
        data_source = 'Simulated'
    else:
        logger.info(f"  Got {len(df)} bars from Futu")
    
    logger.info(f"  Date range: {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}")
    logger.info(f"  Price range: {df['close'].min():.2f} ~ {df['close'].max():.2f}")
    
    # 2. 运行原始V4策略 (单一RF)
    logger.info("\n[2/5] Running Original V4 (Single RF)...")
    orig_ml = OriginalML(confidence=ML_CONFIDENCE_ORIG)
    orig_stats, orig_trades, orig_equity = run_backtest_strategy(df, orig_ml, "V4 Original (RF)")
    
    # 3. 运行增强V4策略 (RF+GBM+LR集成)
    logger.info("\n[3/5] Running Enhanced V4 (RF+GBM+LR Ensemble)...")
    enh_ml = EnhancedML(confidence=ML_CONFIDENCE_ENHANCED)
    enh_stats, enh_trades, enh_equity = run_backtest_strategy(df, enh_ml, "V4 Enhanced (Ensemble)")
    
    # 4. 基准策略
    logger.info("\n[4/5] Running benchmarks...")
    bh_stats = run_buyhold_backtest(df)
    mr_stats = run_meanreversion_only_backtest(df)
    
    # 5. 汇总结果
    logger.info("\n[5/5] Generating report...")
    
    # 特征重要性
    feature_imp = {}
    if enh_ml.feature_importance:
        sorted_imp = sorted(enh_ml.feature_importance.items(), key=lambda x: x[1], reverse=True)
        feature_imp = {k: f"{v:.4f}" for k, v in sorted_imp[:10]}
    
    results = {
        'backtest_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'stock': f"{STOCK_CODE} ({STOCK_NAME})",
        'data_source': data_source,
        'backtest_period': f"{df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()}",
        'parameters': {
            'v3_threshold': V3_THRESHOLD,
            'mr_threshold': MR_THRESHOLD,
            'confirmation_count': CONFIRMATION_COUNT,
            'ml_confidence_orig': ML_CONFIDENCE_ORIG,
            'ml_confidence_enhanced': ML_CONFIDENCE_ENHANCED
        },
        'results': {
            'v4_original': orig_stats,
            'v4_enhanced': enh_stats,
            'mean_reversion_only': mr_stats,
            'buy_hold': bh_stats
        },
        'enhanced_feature_importance': feature_imp,
        'v4_original_trades': orig_trades[-10:],  # 最近10笔
        'v4_enhanced_trades': enh_trades[-10:]
    }
    
    # 保存结果
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    result_file = RESULT_DIR / f"v4_ml_backtest_{timestamp}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"\nResults saved: {result_file}")
    
    # 打印对比表
    print("\n" + "=" * 70)
    print("  V4 ML Enhancement Backtest Results")
    print("=" * 70)
    print(f"  Stock: {STOCK_CODE} ({STOCK_NAME})")
    print(f"  Period: {results['backtest_period']}")
    print("-" * 70)
    print(f"  {'Strategy':<25} {'Return':>10} {'MaxDD':>10} {'Trades':>8} {'WinRate':>10}")
    print("-" * 70)
    for key, label in [
        ('v4_original', 'V4 Original (RF)'),
        ('v4_enhanced', 'V4 Enhanced (Ensemble)'),
        ('mean_reversion_only', 'MeanReversion Only'),
        ('buy_hold', 'Buy&Hold')
    ]:
        r = results['results'][key]
        ret = r.get('total_return', 'N/A')
        dd = r.get('max_drawdown', 'N/A')
        trades = r.get('total_trades', 0)
        wr = r.get('win_rate', 'N/A')
        print(f"  {label:<25} {ret:>10} {dd:>10} {trades:>8} {wr:>10}")
    print("-" * 70)
    
    # 特征重要性
    if feature_imp:
        print("\n  Enhanced Model - Top 10 Feature Importance:")
        for feat, imp in list(feature_imp.items())[:10]:
            print(f"    {feat:<25} {imp}")
    
    print("\n" + "=" * 70)
    
    # 生成Markdown报告
    report_file = RESULT_DIR / f"v4_ml_backtest_report_{timestamp}.md"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(generate_markdown_report(results, df))
    logger.info(f"Report saved: {report_file}")
    
    return results


def generate_markdown_report(results, df):
    """生成Markdown回测报告"""
    r = results
    report = f"""# V4 ML Enhancement Backtest Report

**Date**: {r['backtest_date']}
**Stock**: {r['stock']}
**Data Source**: {r['data_source']}
**Period**: {r['backtest_period']}

---

## 1. Strategy Comparison

| Strategy | Return | Max Drawdown | Trades | Win Rate |
|----------|--------|-------------|--------|----------|
"""
    for key, label in [
        ('v4_original', 'V4 Original (RF)'),
        ('v4_enhanced', 'V4 Enhanced (Ensemble)'),
        ('mean_reversion_only', 'MeanReversion Only'),
        ('buy_hold', 'Buy&Hold')
    ]:
        s = r['results'][key]
        ret = s.get('total_return', 'N/A')
        dd = s.get('max_drawdown', 'N/A')
        trades = s.get('total_trades', 0)
        wr = s.get('win_rate', 'N/A')
        report += f"| {label} | {ret} | {dd} | {trades} | {wr} |\n"
    
    report += f"""

---

## 2. Parameters

| Parameter | Value |
|-----------|-------|
| V3 Threshold | {r['parameters']['v3_threshold']*100}% |
| MR Z-Score Threshold | ±{r['parameters']['mr_threshold']} |
| Confirmation Count | {r['parameters']['confirmation_count']} |
| ML Confidence (Original) | {r['parameters']['ml_confidence_orig']} |
| ML Confidence (Enhanced) | {r['parameters']['ml_confidence_enhanced']} |

---

## 3. Enhancement Details

### Original Model
- Single RandomForest (50 trees, max_depth=6)
- 6 features: returns, rsi, macd, macd_signal, zscore, bb_position
- Confidence threshold: {r['parameters']['ml_confidence_orig']}

### Enhanced Model
- Ensemble: RandomForest + GradientBoosting + CalibratedLR
- 15 features (added: volatility, momentum, volume, multi-timeframe, VIX proxy)
- Confidence threshold: {r['parameters']['ml_confidence_enhanced']}
- Rolling retrain every 20 days

---

## 4. Feature Importance (Enhanced Model)

| Feature | Importance |
|---------|-----------|
"""
    if r['enhanced_feature_importance']:
        for feat, imp in r['enhanced_feature_importance'].items():
            report += f"| {feat} | {imp} |\n"
    
    report += f"""

---

## 5. Recent Trades (Enhanced Model)

| Date | Action | Qty | Price |
|------|--------|-----|-------|
"""
    for t in r.get('v4_enhanced_trades', []):
        report += f"| {t['date']} | {t['action']} | {t['qty']} | {t['price']:.2f} |\n"
    
    report += """
---

*Generated by V4 ML Enhancement Backtest Engine*
"""
    return report


if __name__ == '__main__':
    main()
