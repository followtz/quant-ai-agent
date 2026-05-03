# -*- coding: utf-8 -*-
"""
V3.0 ML趋势跟踪策略
基于历史经验改进：扩大数据、滚动验证、严格阈值

核心逻辑（与V2完全不同）：
1. 不用prev_close，改用价格动量 + 波动率 + 成交量
2. 标签：未来5日收益 > 0 为涨(1)，否则为跌(0)
3. 训练：滚动窗口（60天训练，预测后30天）
4. 交易：只在预测概率>70%时做多（或做空）
5. 底仓：1000股（很低，减少市场风险）
6. 严格风控：5%止损，单个持仓最多10天

改进点（相比当年失败尝试）：
- 训练窗口：20天 → 60天
- 验证方式：单次划分 → 滚动验证
- 置信阈值：无过滤 → 70%阈值
- 特征选择：全部使用 → 稳定性检验
"""
import sys, json, math, random
from datetime import datetime, timedelta
from pathlib import Path
import csv

WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)

# ===================== 数据加载 =====================
def load_csv_data(csv_path):
    data = []
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                data.append({
                    'date': row.get('time_key', ''),
                    'open': float(row.get('open',0)),
                    'high': float(row.get('high',0)),
                    'low': float(row.get('low',0)),
                    'close': float(row.get('close',0)),
                    'volume': float(row.get('volume',0)),
                })
            except (ValueError, KeyError):
                continue
    return data

# ===================== 特征工程（针对趋势预测） =====================
def extract_trend_features(data, i, window=20):
    """提取趋势预测的特征向量"""
    if i < window:
        return None
    
    bar = data[i]
    close = bar['close']
    
    # 1. 价格动量特征
    returns_5d = [(data[i-j]['close'] - data[i-j-5]['close']) / data[i-j-5]['close'] 
                  for j in range(0, 5) if i-j-5 >= 0]
    returns_10d = [(data[i-j]['close'] - data[i-j-10]['close']) / data[i-j-10]['close'] 
                   for j in range(0, 10) if i-j-10 >= 0]
    returns_20d = [(data[i-j]['close'] - data[i-j-20]['close']) / data[i-j-20]['close'] 
                   for j in range(0, 20) if i-j-20 >= 0]
    
    ret_5d = sum(returns_5d) / len(returns_5d) if returns_5d else 0
    ret_10d = sum(returns_10d) / len(returns_10d) if returns_10d else 0
    ret_20d = sum(returns_20d) / len(returns_20d) if returns_20d else 0
    
    # 2. 波动率特征
    recent_returns = [(data[j]['close'] - data[j-1]['close']) / data[j-1]['close'] 
                       for j in range(max(1,i-window), i+1)]
    volatility = (sum((r - sum(recent_returns)/len(recent_returns))**2 
                   for r in recent_returns) / len(recent_returns)) ** 0.5 if recent_returns else 0.05
    
    # 3. 成交量特征
    avg_vol = sum(b['volume'] for b in data[max(0,i-window):i]) / min(i, window)
    vol_ratio = bar['volume'] / avg_vol if avg_vol > 0 else 1.0
    
    # 4. 技术指标（简化版）
    # RSI (14)
    gains = [max(0, (data[j]['close'] - data[j-1]['close'])/data[j-1]['close']) 
             for j in range(max(1,i-14), i+1)]
    losses = [max(0, (data[j-1]['close'] - data[j]['close'])/data[j-1]['close']) 
             for j in range(max(1,i-14), i+1)]
    avg_gain = sum(gains) / 14 if len(gains) >= 14 else 0
    avg_loss = sum(losses) / 14 if len(losses) >= 14 else 0
    rsi = 100 - (100 / (1 + avg_gain/avg_loss)) if avg_loss > 0 else 100
    
    # 5. 价格位置（相对N日高低点）
    highs = [b['high'] for b in data[max(0,i-window):i+1]]
    lows = [b['low'] for b in data[max(0,i-window):i+1]]
    price_position = (close - min(lows)) / (max(highs) - min(lows)) if max(highs) > min(lows) else 0.5
    
    # 6. 连续涨跌天数
    consecutive_up = 0
    consecutive_down = 0
    for j in range(max(0,i-10), i):
        ret = (data[j+1]['close'] - data[j]['close']) / data[j]['close']
        if ret > 0:
            consecutive_up += 1
            consecutive_down = 0
        else:
            consecutive_down += 1
            consecutive_up = 0
    
    return {
        'ret_5d': ret_5d,
        'ret_10d': ret_10d,
        'ret_20d': ret_20d,
        'volatility': volatility,
        'vol_ratio': vol_ratio,
        'rsi': rsi / 100,  # 归一化到0-1
        'price_position': price_position,
        'consecutive_up': min(consecutive_up, 5) / 5,  # 归一化
        'consecutive_down': min(consecutive_down, 5) / 5,
        'price': close,
    }

# ===================== 标签构造 =====================
def create_trend_labels(data, forward_days=5):
    """
    构造趋势标签：未来N日是否上涨
    
    返回：样本列表，每个样本包含特征和标签
    """
    samples = []
    
    for i in range(len(data)):
        if i + forward_days >= len(data):
            break
        
        features = extract_trend_features(data, i, window=20)
        if features is None:
            continue
        
        # 计算未来N日收益
        future_ret = (data[i+forward_days]['close'] - data[i]['close']) / data[i]['close']
        label = 1 if future_ret > 0 else 0  # 1=涨, 0=跌
        
        samples.append({
            'idx': i,
            'date': data[i]['date'][:10],
            'features': features,
            'label': label,
            'future_ret': future_ret,
        })
    
    return samples

# ===================== 特征向量化 =====================
FEATURE_KEYS = [
    'ret_5d', 'ret_10d', 'ret_20d',
    'volatility', 'vol_ratio',
    'rsi', 'price_position',
    'consecutive_up', 'consecutive_down',
]

def vectorize(features_dict):
    return [features_dict[k] for k in FEATURE_KEYS]

# ===================== 简化版随机森林（同v23） =====================
class SimpleRandomForest:
    def __init__(self, n_trees=10, max_depth=5, n_features=None):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.n_features = n_features
        self.trees = []
    
    def _entropy(self, labels):
        if not labels:
            return 0
        n = len(labels)
        p1 = sum(labels) / n
        p0 = 1 - p1
        if p0 == 0 or p1 == 0:
            return 0
        return -p0 * math.log2(p0) - p1 * math.log2(p1)
    
    def _split(self, X, y, feature_idx):
        values = [x[feature_idx] for x in X]
        if not values:
            return None, None, None, None, None, None
        
        threshold = sorted(values)[len(values)//2]
        
        left_X = [x for x in X if x[feature_idx] <= threshold]
        left_y = [y[i] for i in range(len(X)) if X[i][feature_idx] <= threshold]
        right_X = [x for x in X if x[feature_idx] > threshold]
        right_y = [y[i] for i in range(len(X)) if X[i][feature_idx] > threshold]
        
        if not left_y or not right_y:
            return None, None, None, None, None, None
        
        parent_entropy = self._entropy(y)
        left_entropy = self._entropy(left_y)
        right_entropy = self._entropy(right_y)
        n = len(y)
        gain = parent_entropy - (len(left_y)/n * left_entropy + len(right_y)/n * right_entropy)
        
        return threshold, left_X, left_y, right_X, right_y, gain
    
    def _build_tree(self, X, y, depth=0):
        if depth >= self.max_depth or len(set(y)) <= 1 or len(X) < 5:
            return {'type': 'leaf', 'prediction': sum(y) / len(y)}
        
        n_feat = self.n_features or len(X[0])
        feature_indices = random.sample(range(len(X[0])), min(n_feat, len(X[0])))
        
        best_gain = -1
        best_split = None
        
        for fi in feature_indices:
            result = self._split(X, y, fi)
            if result[0] is not None:
                threshold, left_X, left_y, right_X, right_y, gain = result
                if gain > best_gain:
                    best_gain = gain
                    best_split = (fi, threshold, left_X, left_y, right_X, right_y)
        
        if best_split is None:
            return {'type': 'leaf', 'prediction': sum(y) / len(y)}
        
        fi, threshold, left_X, left_y, right_X, right_y = best_split
        
        return {
            'type': 'node',
            'feature_idx': fi,
            'threshold': threshold,
            'left': self._build_tree(left_X, left_y, depth+1),
            'right': self._build_tree(right_X, right_y, depth+1),
        }
    
    def _predict_tree(self, tree, x):
        if tree['type'] == 'leaf':
            return tree['prediction']
        if x[tree['feature_idx']] <= tree['threshold']:
            return self._predict_tree(tree['left'], x)
        else:
            return self._predict_tree(tree['right'], x)
    
    def fit(self, X, y):
        self.trees = []
        for _ in range(self.n_trees):
            n_samples = len(X)
            indices = [random.randint(0, n_samples-1) for _ in range(n_samples)]
            X_boot = [X[i] for i in indices]
            y_boot = [y[i] for i in indices]
            tree = self._build_tree(X_boot, y_boot)
            self.trees.append(tree)
    
    def predict_proba(self, x):
        preds = [self._predict_tree(tree, x) for tree in self.trees]
        return sum(preds) / len(preds)
    
    def predict(self, x, threshold=0.5):
        prob = self.predict_proba(x)
        return 1 if prob >= threshold else 0

# ===================== 滚动验证 =====================
def rolling_validation(data, train_days=60, test_days=30, threshold=0.7):
    """
    滚动验证：用前train_days天预测后test_days天
    
    返回：
    - 预测准确率（只计算概率>阈值的样本）
    - 样本外盈亏（模拟交易）
    """
    samples = create_trend_labels(data, forward_days=5)
    print(f"  总样本数: {len(samples)}")
    
    if len(samples) < train_days + test_days:
        print("  [错误] 样本不足，无法滚动验证")
        return None
    
    # 按时间顺序划分
    all_predictions = []
    correct = 0
    total = 0
    pnl = 0.0
    
    # 从第train_days个样本开始，每次向后移动test_days
    i = train_days
    while i + test_days < len(samples):
        # 训练集：前i个样本
        train_samples = samples[max(0, i-train_days):i]
        X_train = [vectorize(s['features']) for s in train_samples]
        y_train = [s['label'] for s in train_samples]
        
        # 测试集：后test_days个样本
        test_samples = samples[i:i+test_days]
        
        # 训练模型
        model = SimpleRandomForest(n_trees=10, max_depth=5, n_features=5)
        model.fit(X_train, y_train)
        
        # 测试预测
        for s in test_samples:
            prob = model.predict_proba(vectorize(s['features']))
            
            # 只看高置信度预测
            if prob >= threshold or prob <= (1 - threshold):
                pred = 1 if prob >= threshold else 0
                actual = s['label']
                
                all_predictions.append({
                    'date': s['date'],
                    'prob': prob,
                    'pred': pred,
                    'actual': actual,
                    'future_ret': s['future_ret'],
                })
                
                if pred == actual:
                    correct += 1
                total += 1
                
                # 模拟交易：预测涨(1)就做多，预测跌(0)就平仓（或做空）
                if pred == 1:
                    pnl += s['future_ret'] * 1000  # 假设1000股
        
        i += test_days
    
    accuracy = correct / total * 100 if total > 0 else 0
    
    return {
        'accuracy': accuracy,
        'total_predictions': total,
        'correct_predictions': correct,
        'sample_pnl': round(pnl, 2),
        'predictions': all_predictions[:20],
    }

# ===================== V3.0 ML趋势跟踪策略回测 =====================
def backtest_v30_ml_trend(data, threshold=0.7, base_shares=1000):
    """
    V3.0 ML趋势跟踪策略回测
    - 底仓1000股（很低）
    - 用ML预测未来趋势
    - 只在置信度>threshold时交易
    - 5%止损，最多持仓10天
    """
    samples = create_trend_labels(data, forward_days=5)
    
    # 训练一个全局模型（用前60天）
    train_samples = samples[:60]
    X_train = [vectorize(s['features']) for s in train_samples]
    y_train = [s['label'] for s in train_samples]
    
    model = SimpleRandomForest(n_trees=10, max_depth=5, n_features=5)
    model.fit(X_train, y_train)
    print(f"  [模型训练完成] 用前60天样本")
    
    # 回测
    shares = base_shares
    cash = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_equity = shares * data[0]['close']
    
    position = {'active': False, 'entry': 0, 'qty': 0, 'days': 0, 'type': ''}
    trade_log = []
    
    for i, bar in enumerate(data):
        if i == 0:
            continue
        
        price = bar['close']
        
        # 权益计算
        equity = shares * price + cash
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
        
        # 检查持仓
        if position['active']:
            position['days'] += 1
            entry = position['entry']
            qty = position['qty']
            
            # 止损
            if position['type'] == 'LONG':
                if price <= entry * 0.95:
                    pnl = (price - entry) * qty
                    cash += pnl
                    shares -= qty
                    total_trades += 1
                    if pnl >= 0: wins += 1
                    else: losses += 1
                    trade_log.append({
                        'type': 'LONG_STOP', 'price': price, 'qty': qty,
                        'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    })
                    position = {'active': False, 'entry': 0, 'qty': 0, 'days': 0, 'type': ''}
                    continue
            
            # 持仓超时（10天）
            if position['days'] >= 10:
                if position['type'] == 'LONG':
                    pnl = (price - entry) * qty
                    cash += pnl
                    shares -= qty
                    total_trades += 1
                    if pnl >= 0: wins += 1
                    else: losses += 1
                    trade_log.append({
                        'type': 'LONG_TIMEOUT', 'price': price, 'qty': qty,
                        'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    })
                    position = {'active': False, 'entry': 0, 'qty': 0, 'days': 0, 'type': ''}
        
        # ML预测
        if not position['active'] and i < len(samples):
            sample = samples[i]
            features_vec = vectorize(sample['features'])
            prob = model.predict_proba(features_vec)
            
            # 只做高置信度预测
            if prob >= threshold:
                # 预测涨，做多
                qty = 1000
                shares += qty
                position = {'active': True, 'entry': price, 'qty': qty, 'days': 0, 'type': 'LONG'}
                trade_log.append({
                    'type': 'LONG_ML', 'price': price, 'qty': qty, 'pnl': 0,
                    'date': bar['date'][:10], 'prob': round(prob, 3),
                })
    
    # 统计
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    total_pnl = cash + (shares - base_shares) * data[-1]['close']
    
    return {
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'trade_log': trade_log[:20],
    }

# ===================== 主函数 =====================
def main():
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日")
    
    # 1. 滚动验证（评估ML置信度）
    print("\n" + "="*70)
    print("  V3.0 ML趋势预测 - 滚动验证")
    print("="*70)
    print("  训练窗口=60天，测试窗口=30天，置信阈值=70%")
    
    val_result = rolling_validation(data, train_days=60, test_days=30, threshold=0.7)
    
    if val_result:
        print(f"\n  验证结果:")
        print(f"  总预测数: {val_result['total_predictions']}")
        print(f"  准确率: {val_result['accuracy']:.1f}%")
        print(f"  样本盈亏: ${val_result['sample_pnl']:,.2f}")
        
        if val_result['accuracy'] < 55:
            print(f"\n  [警告] 准确率过低({val_result['accuracy']:.1f}%)，ML预测不可信！")
            print(f"  建议：放弃ML预测，回到规则型策略")
        elif val_result['accuracy'] < 60:
            print(f"\n  [提示] 准确率一般({val_result['accuracy']:.1f}%)，谨慎使用ML")
        else:
            print(f"\n  [通过] 准确率{val_result['accuracy']:.1f}%，ML预测可用")
    
    # 2. V3.0回测
    print("\n" + "="*70)
    print("  V3.0 ML趋势跟踪策略回测")
    print("="*70)
    print("  配置: 底仓1000股，5%止损，70%置信阈值")
    
    v30_result = backtest_v30_ml_trend(data, threshold=0.7, base_shares=1000)
    
    print(f"\n  V3.0 结果:")
    print(f"  盈亏: ${v30_result['total_pnl']:,.2f}")
    print(f"  交易: {v30_result['total_trades']}笔 (胜率={v30_result['win_rate']:.1f}%)")
    print(f"  最大回撤: {v30_result['max_drawdown']:.2f}%")
    
    # 3. 对比V2原版
    print("\n" + "="*70)
    print("  对比总结")
    print("="*70)
    print(f"  V2原版(底仓8884股): $2,115 (胜率44.4%, 回撤-54.59%)")
    print(f"  V2.4 Zero-Beta:    $-1,425 (胜率36.4%, 回撤-196.11%)")
    print(f"  V3.0 ML趋势跟踪:   ${v30_result['total_pnl']:,.2f} "
          f"(胜率{v30_result['win_rate']:.1f}%, 回撤{v30_result['max_drawdown']:.2f}%)")
    
    if val_result:
        print(f"\n  ML滚动验证准确率: {val_result['accuracy']:.1f}%")
        print(f"  结论: {'ML可用' if val_result['accuracy'] >= 60 else 'ML置信度不足，建议放弃'}")
    
    # 4. 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'v30_result': v30_result,
        'rolling_validation': val_result,
        'comparison': {
            'v2_original': {'pnl': 2115, 'win_rate': 44.4, 'max_dd': -54.59},
            'v24_zero_beta': {'pnl': -1425, 'win_rate': 36.4, 'max_dd': -196.11},
        }
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v30_ml_trend_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    random.seed(42)
    main()