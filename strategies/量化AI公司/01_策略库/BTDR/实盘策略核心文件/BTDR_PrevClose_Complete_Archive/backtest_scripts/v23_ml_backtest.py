# -*- coding: utf-8 -*-
"""
BTDR V2.3 ML情绪反转预测器
完整实现：预测大跌后反弹 + 大涨后回调

核心思想：
1. 构造两个方向的标签（大跌反弹/大涨回调）
2. 提取多维特征（价格/成交量/波动率/状态/时间）
3. 训练随机森林分类器
4. 只在预测概率>阈值时交易
5. 回测验证 vs V2原版
"""
import sys, json, math, random
from datetime import datetime
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

# ===================== 特征工程 =====================
def extract_features(data, i, window=20):
    """提取第i根bar的特征向量"""
    if i < 1:
        return None
    
    bar = data[i]
    prev = data[i-1]
    
    close = bar['close']
    prev_close = prev['close']
    open_p = bar['open']
    volume = bar['volume']
    
    # 1. 价格行为特征
    daily_ret = (close - prev_close) / prev_close
    intraday = (close - open_p) / open_p
    
    # 连续涨跌天数
    consecutive_up = 0
    consecutive_down = 0
    for j in range(max(0, i-5), i):
        ret = (data[j]['close'] - data[j-1]['close']) / data[j-1]['close']
        if ret > 0:
            consecutive_up += 1
            consecutive_down = 0
        else:
            consecutive_down += 1
            consecutive_up = 0
    
    # 2. 成交量特征
    avg_vol = sum(b['volume'] for b in data[max(0,i-window):i]) / min(i, window)
    vol_ratio = volume / avg_vol if avg_vol > 0 else 1.0
    
    # 3. 波动率特征
    returns = [(data[j]['close'] - data[j-1]['close']) / data[j-1]['close'] 
               for j in range(max(1,i-window), i+1)]
    if len(returns) > 1:
        avg_ret = sum(returns) / len(returns)
        volatility = (sum((r - avg_ret)**2 for r in returns) / len(returns)) ** 0.5
        vol_change = volatility - (sum(returns[:len(returns)//2]) / (len(returns)//2) if len(returns)>2 else volatility)
    else:
        volatility = 0.05
        vol_change = 0
    
    # 4. 市场状态特征 (简化版，不用K-means)
    if volatility > 0.05:
        if daily_ret < -0.02:
            regime_panic = 1
            regime_euphoria = 0
            regime_trend = 0
        else:
            regime_panic = 0
            regime_euphoria = 1
            regime_trend = 0
    else:
        if daily_ret > 0.01:
            regime_panic = 0
            regime_euphoria = 0
            regime_trend = 1
        else:
            regime_panic = 0
            regime_euphoria = 1
            regime_trend = 0
    
    # 5. 时间特征
    try:
        dt = datetime.strptime(bar['date'][:10], '%Y-%m-%d')
        day_of_week = dt.weekday()  # 0=Mon, 6=Sun
    except:
        day_of_week = 2
    
    return {
        'daily_ret': daily_ret,
        'intraday': intraday,
        'consecutive_up': consecutive_up,
        'consecutive_down': consecutive_down,
        'vol_ratio': vol_ratio,
        'volatility': volatility,
        'vol_change': vol_change,
        'regime_panic': regime_panic,
        'regime_euphoria': regime_euphoria,
        'regime_trend': regime_trend,
        'day_of_week': day_of_week,
        'price': close,
        'prev_close': prev_close,
    }

# ===================== 构造标签 =====================
def create_labels(data, drop_threshold=0.05, gain_threshold=0.05, forward_days=3):
    """
    构造两个方向的标签：
    1. 大跌后N日是否反弹（future_ret > 0）
    2. 大涨后N日是否回调（future_ret < 0）
    """
    panic_samples = []  # 大跌反弹样本
    euphoria_samples = []  # 大涨回调样本
    
    for i in range(1, len(data)):
        features = extract_features(data, i)
        if features is None:
            continue
        
        close = data[i]['close']
        
        # 大跌反弹标签
        if features['daily_ret'] <= -drop_threshold:
            # 计算未来N日收益
            if i + forward_days < len(data):
                future_ret = (data[i+forward_days]['close'] - close) / close
                label = 1 if future_ret > 0 else 0  # 1=反弹, 0=继续跌
                panic_samples.append({
                    'idx': i,
                    'features': features,
                    'label': label,
                    'future_ret': future_ret,
                })
        
        # 大涨回调标签
        if features['daily_ret'] >= gain_threshold:
            if i + forward_days < len(data):
                future_ret = (data[i+forward_days]['close'] - close) / close
                label = 1 if future_ret < 0 else 0  # 1=回调, 0=继续涨
                euphoria_samples.append({
                    'idx': i,
                    'features': features,
                    'label': label,
                    'future_ret': future_ret,
                })
    
    return panic_samples, euphoria_samples

# ===================== 简化版随机森林 (不依赖sklearn) =====================
class SimpleRandomForest:
    """
    简化版随机森林（不依赖sklearn）
    用决策树bagging实现二分类
    """
    def __init__(self, n_trees=10, max_depth=5, n_features=None):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.n_features = n_features  # None=all
        self.trees = []
    
    def _entropy(self, labels):
        """计算熵"""
        if not labels:
            return 0
        n = len(labels)
        p1 = sum(labels) / n
        p0 = 1 - p1
        if p0 == 0 or p1 == 0:
            return 0
        return -p0 * math.log2(p0) - p1 * math.log2(p1)
    
    def _split(self, X, y, feature_idx):
        """找最佳分割点（中位数）"""
        values = [x[feature_idx] for x in X]
        if not values:
            return None, None, None, None
        
        threshold = sorted(values)[len(values)//2]
        
        left_X = [x for x in X if x[feature_idx] <= threshold]
        left_y = [y[i] for i in range(len(X)) if X[i][feature_idx] <= threshold]
        right_X = [x for x in X if x[feature_idx] > threshold]
        right_y = [y[i] for i in range(len(X)) if X[i][feature_idx] > threshold]
        
        if not left_y or not right_y:
            return None, None, None, None
        
        # 计算信息增益
        parent_entropy = self._entropy(y)
        left_entropy = self._entropy(left_y)
        right_entropy = self._entropy(right_y)
        n = len(y)
        gain = parent_entropy - (len(left_y)/n * left_entropy + len(right_y)/n * right_entropy)
        
        return threshold, left_X, left_y, right_X, right_y, gain
    
    def _build_tree(self, X, y, depth=0):
        """递归构建决策树"""
        if depth >= self.max_depth or len(set(y)) <= 1 or len(X) < 5:
            # 叶节点：返回多数类
            return {'type': 'leaf', 'prediction': sum(y) / len(y)}
        
        # 随机选择特征子集
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
        """单棵树预测"""
        if tree['type'] == 'leaf':
            return tree['prediction']
        
        if x[tree['feature_idx']] <= tree['threshold']:
            return self._predict_tree(tree['left'], x)
        else:
            return self._predict_tree(tree['right'], x)
    
    def fit(self, X, y):
        """训练随机森林"""
        self.trees = []
        for _ in range(self.n_trees):
            # Bootstrap采样
            n_samples = len(X)
            indices = [random.randint(0, n_samples-1) for _ in range(n_samples)]
            X_boot = [X[i] for i in indices]
            y_boot = [y[i] for i in indices]
            
            tree = self._build_tree(X_boot, y_boot)
            self.trees.append(tree)
    
    def predict_proba(self, x):
        """预测概率（平均所有树的输出）"""
        preds = [self._predict_tree(tree, x) for tree in self.trees]
        return sum(preds) / len(preds)  # 返回P(y=1)
    
    def predict(self, x, threshold=0.5):
        """二分类预测"""
        prob = self.predict_proba(x)
        return 1 if prob >= threshold else 0

# ===================== 特征向量化 =====================
FEATURE_KEYS = [
    'daily_ret', 'intraday', 'consecutive_up', 'consecutive_down',
    'vol_ratio', 'volatility', 'vol_change',
    'regime_panic', 'regime_euphoria', 'regime_trend',
    'day_of_week',
]

def vectorize(features_dict):
    """将特征字典转为向量"""
    return [features_dict[k] for k in FEATURE_KEYS]

# ===================== 主函数 =====================
def main():
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日")
    
    # 1. 构造标签
    print("\n" + "="*70)
    print("  构造ML训练样本")
    print("="*70)
    
    panic_samples, euphoria_samples = create_labels(
        data, drop_threshold=0.05, gain_threshold=0.05, forward_days=3
    )
    
    print(f"  大跌反弹样本: {len(panic_samples)}个")
    print(f"  大涨回调样本: {len(euphoria_samples)}个")
    
    if len(panic_samples) < 10 or len(euphoria_samples) < 10:
        print("  [错误] 样本不足，无法训练")
        return
    
    # 统计标签分布
    panic_pos = sum(1 for s in panic_samples if s['label'] == 1)
    euphoria_pos = sum(1 for s in euphoria_samples if s['label'] == 1)
    
    print(f"  大跌反弹正样本: {panic_pos}/{len(panic_samples)} ({panic_pos/len(panic_samples)*100:.1f}%)")
    print(f"  大涨回调正样本: {euphoria_pos}/{len(euphoria_samples)} ({euphoria_pos/len(euphoria_samples)*100:.1f}%)")
    
    # 2. 训练模型
    print("\n" + "="*70)
    print("  训练随机森林模型")
    print("="*70)
    
    # 大跌反弹模型
    X_panic = [vectorize(s['features']) for s in panic_samples]
    y_panic = [s['label'] for s in panic_samples]
    model_panic = SimpleRandomForest(n_trees=10, max_depth=5, n_features=5)
    model_panic.fit(X_panic, y_panic)
    print(f"  [大跌反弹模型] 训练完成")
    
    # 大涨回调模型
    X_euphoria = [vectorize(s['features']) for s in euphoria_samples]
    y_euphoria = [s['label'] for s in euphoria_samples]
    model_euphoria = SimpleRandomForest(n_trees=10, max_depth=5, n_features=5)
    model_euphoria.fit(X_euphoria, y_euphoria)
    print(f"  [大涨回调模型] 训练完成")
    
    # 3. 回测V2.3 ML策略
    print("\n" + "="*70)
    print("  回测V2.3 ML情绪反转策略")
    print("="*70)
    
    # 回测参数
    BASE = {
        'base_shares': 8894,
        'trade_qty': 1000,
        'pos_min': 7000,
        'pos_max': 11000,
        'a_offset': -0.01,
        'b_offset': 0.05,
        'stop_loss_pct': 0.05,
        'ml_threshold': 0.6,  # ML预测概率阈值
    }
    
    shares = BASE['base_shares']
    total_pnl = 0.0
    total_trades = 0
    wins = 0
    losses = 0
    max_drawdown = 0.0
    peak_equity = 0.0
    ml_triggered = 0  # ML触发次数
    ml_correct = 0  # ML预测正确次数
    
    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    
    trade_log = []
    
    for i, bar in enumerate(data):
        if i == 0:
            continue
        
        price = bar['close']
        prev_close = data[i-1]['close']
        
        # 权益计算
        equity = shares * price
        if equity > peak_equity:
            peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown:
            max_drawdown = dd
        
        # 提取特征
        features_dict = extract_features(data, i)
        if features_dict is None:
            continue
        
        features_vec = vectorize(features_dict)
        
        # =============== 涡轮A检查 ===============
        if turbo_a['active']:
            turbo_a['days'] += 1
            entry = turbo_a['entry']
            buyback = turbo_a['prev_close'] * (1 + BASE['a_offset'])
            
            # 止损
            if price <= entry * (1 - BASE['stop_loss_pct']):
                pnl = (price - entry) * turbo_a['qty']
                total_pnl += pnl; shares += turbo_a['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_STOP', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 买回
            if price <= buyback:
                pnl = (entry - price) * turbo_a['qty']
                total_pnl += pnl; shares += turbo_a['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_BACK', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查A卖出信号（大涨后）
            sell_trigger = prev_close * (1 + 0.12)  # 原V2的sell_t
            if price >= sell_trigger and shares > BASE['pos_min']:
                # ML预测：大涨后会回调吗？
                prob = model_euphoria.predict_proba(features_vec)
                if prob >= BASE['ml_threshold']:
                    ml_triggered += 1
                    # 检查未来是否真的回调（用于评估ML准确率）
                    if i + 3 < len(data):
                        future_ret = (data[i+3]['close'] - price) / price
                        if future_ret < 0:
                            ml_correct += 1
                    
                    qty = min(int(BASE['trade_qty'] / 100) * 100, shares - BASE['pos_min'])
                    qty = max(100, qty)
                    shares -= qty
                    turbo_a = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                    trade_log.append({
                        'type': 'A_SELL_ML', 'price': price, 'qty': qty, 'pnl': 0,
                        'date': bar['date'][:10], 'ml_prob': round(prob, 3),
                    })
                # 如果ML不触发，不卖出（跳过原V2逻辑）
        
        # =============== 涡轮B检查 ===============
        if turbo_b['active']:
            turbo_b['days'] += 1
            entry = turbo_b['entry']
            sellback = turbo_b['prev_close'] * (1 + BASE['b_offset'])
            
            # 止损
            if price <= entry * (1 - BASE['stop_loss_pct']):
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl; shares -= turbo_b['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_STOP', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 卖出
            if price >= sellback:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl; shares -= turbo_b['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_SELL', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查B买入信号（大跌后）
            buy_trigger = prev_close * (1 - 0.05)  # 原V2的buy_t
            if price <= buy_trigger and shares < BASE['pos_max']:
                # ML预测：大跌后会反弹吗？
                prob = model_panic.predict_proba(features_vec)
                if prob >= BASE['ml_threshold']:
                    ml_triggered += 1
                    # 检查未来是否真的反弹
                    if i + 3 < len(data):
                        future_ret = (data[i+3]['close'] - price) / price
                        if future_ret > 0:
                            ml_correct += 1
                    
                    qty = min(int(BASE['trade_qty'] / 100) * 100, BASE['pos_max'] - shares)
                    qty = max(100, qty)
                    shares += qty
                    turbo_b = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                    trade_log.append({
                        'type': 'B_BUY_ML', 'price': price, 'qty': qty, 'pnl': 0,
                        'date': bar['date'][:10], 'ml_prob': round(prob, 3),
                    })
                # 如果ML不触发，不买入
    
    # 输出结果
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    ml_accuracy = ml_correct / ml_triggered * 100 if ml_triggered > 0 else 0
    
    print(f"\n  V2.3 ML策略结果:")
    print(f"  盈亏: ${total_pnl:,.2f}")
    print(f"  交易: {total_trades}笔 (胜率={win_rate:.1f}%)")
    print(f"  最大回撤: {max_drawdown*100:.2f}%")
    print(f"  ML触发: {ml_triggered}次 (准确率={ml_accuracy:.1f}%)")
    
    # 对比V2原版（运行之前的v22_simple_backtest.py的逻辑）
    print(f"\n  对比V2原版(预期): $2,115 (胜率44.4%, 回撤-54.59%)")
    
    # 保存报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'v23_results': {
            'total_pnl': round(total_pnl, 2),
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
            'max_drawdown': round(max_drawdown * 100, 2),
            'ml_triggered': ml_triggered,
            'ml_accuracy': round(ml_accuracy, 2),
        },
        'training_samples': {
            'panic': len(panic_samples),
            'euphoria': len(euphoria_samples),
            'panic_positive_rate': panic_pos/len(panic_samples)*100,
            'euphoria_positive_rate': euphoria_pos/len(euphoria_samples)*100,
        },
        'trade_log': trade_log[:20],
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v23_ml_backtest_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    random.seed(42)
    main()