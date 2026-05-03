# -*- coding: utf-8 -*-
"""
BTDR PrevClose V2.2 状态依赖策略 + 趋势过滤器
基于EDA统计结果的机器学习优化

核心发现:
1. 12%大跌后继续跌(t=-6.16) → 不能在暴跌后买入
2. 识别3个市场状态(State0=恐慌反弹/State1=亢奋回调/State2=趋势)
3. 每个状态需要不同参数

V2.2改进:
1. 实时状态检测(K-means在线推断)
2. 状态依赖参数调整
3. 趋势过滤器(避免接飞刀)
"""
import sys, json, math
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
                    'open': float(row.get('open', 0)),
                    'high': float(row.get('high', 0)),
                    'low': float(row.get('low', 0)),
                    'close': float(row.get('close', 0)),
                    'volume': float(row.get('volume', 0)),
                })
            except (ValueError, KeyError):
                continue
    return data

# ===================== 特征工程 =====================
def extract_features(data_list, i):
    """从历史数据中提取K-means聚类特征"""
    if i < 1:
        return [0.0, 0.0, 0.0]
    
    prev_close = data_list[i-1]['close']
    close = data_list[i]['close']
    open_p = data_list[i]['open']
    
    # 特征1: 简单情绪
    sentiment = (close - prev_close) / prev_close
    
    # 特征2: 日内反转
    intraday = (close - open_p) / open_p
    
    # 特征3: 用历史窗口内的波动率作为未来收益的代理
    window = data_list[max(0, i-20):i]
    if len(window) >= 5:
        rets = [(window[j]['close'] - window[j-1]['close']) / window[j-1]['close']
                for j in range(1, len(window))]
        vol_proxy = (sum((r - sum(rets)/len(rets))**2 for r in rets) / len(rets)) ** 0.5
    else:
        vol_proxy = 0.05
    
    return [sentiment, intraday, vol_proxy]

# ===================== K-means 聚类中心 (来自EDA) =====================
# State 0: 30天, sentiment=-5.28%, future_ret=+1.49%  → 恐慌反弹
# State 1: 26天, sentiment=+2.38%, future_ret=-5.49%  → 亢奋回调
# State 2: 24天, sentiment=+5.12%, future_ret=+5.05%  → 趋势上涨

# 用EDA识别出的特征中心初始化 (标准化后的值需要估算)
# 实际运行时用滚动数据重新计算中心

# ===================== 滚动K-means状态检测 =====================
class RegimeDetector:
    """
    滚动K-means状态检测器
    使用过去N日数据训练，然后用最新特征推断当前状态
    """
    def __init__(self, lookback=30, n_states=3, warmup=20):
        self.lookback = lookback
        self.n_states = n_states
        self.warmup = warmup
        self.centroids = None
        self.fitted = False
        self.history = []  # 存储历史特征
    
    def _standardize(self, X_list):
        """Z-score标准化"""
        if not X_list:
            return X_list
        n = len(X_list[0])
        means = [sum(x[j] for x in X_list) / len(X_list) for j in range(n)]
        stds = [(sum((x[j] - means[j])**2 for x in X_list) / len(X_list)) ** 0.5 for j in range(n)]
        stds = [s if s > 1e-9 else 1.0 for s in stds]
        return [[(x[j] - means[j]) / stds[j] for j in range(n)] for x in X_list], means, stds
    
    def _euclidean(self, a, b):
        return math.sqrt(sum((a[i]-b[i])**2 for i in range(len(a))))
    
    def fit_predict(self, data_list):
        """用历史数据拟合，然后预测最新状态"""
        # 收集特征
        all_features = []
        for i in range(1, len(data_list)):
            f = extract_features(data_list, i)
            all_features.append(f)
        
        if len(all_features) < self.warmup + self.n_states:
            return 1  # 默认State1(亢奋)
        
        # 用warmup时期的数据训练
        train_features = all_features[:self.warmup]
        norm_train, self._means, self._stds = self._standardize(train_features)
        
        # 简单K-means: 先用分位数初始化中心
        sentiment_vals = sorted([f[0] for f in norm_train])
        n = len(norm_train)
        self.centroids = [
            norm_train[int(n * k / self.n_states)]
            for k in range(self.n_states)
        ]
        
        # 迭代优化
        for _ in range(20):
            clusters = [[] for _ in range(self.n_states)]
            for f in norm_train:
                distances = [self._euclidean(f, c) for c in self.centroids]
                clusters[distances.index(min(distances))].append(f)
            
            new_centroids = []
            for cluster in clusters:
                if cluster:
                    new_c = [sum(cluster[j][i] for cluster in j) / len(cluster) for i in range(len(cluster[0]))]
                    new_centroids.append(new_c)
                else:
                    new_centroids.append(self.centroids[len(new_centroids)])
            
            # 填充到n_states个中心
            while len(new_centroids) < self.n_states:
                new_centroids.append(norm_train[len(new_centroids) % n])
            
            self.centroids = new_centroids
        
        # 用训练好的中心预测所有数据的最终状态
        norm_all, _, _ = self._standardize(all_features)
        labels = []
        for f in norm_all:
            distances = [self._euclidean(f, c) for c in self.centroids]
            labels.append(distances.index(min(distances)))
        
        # 分析每个状态的实际含义(基于非标准化特征)
        state_stats = {}
        for s in range(self.n_states):
            indices = [i for i, l in enumerate(labels) if l == s]
            if indices:
                feats = [all_features[i] for i in indices]
                state_stats[s] = {
                    'count': len(indices),
                    'avg_sentiment': sum(f[0] for f in feats) / len(feats),
                    'avg_intraday': sum(f[1] for f in feats) / len(feats),
                    'avg_vol_proxy': sum(f[2] for f in feats) / len(feats),
                }
        
        self.fitted = True
        self.state_stats = state_stats
        return labels
    
    def predict_state(self, features):
        """用已拟合的中心预测当前状态"""
        if not self.fitted or self.centroids is None:
            return 1
        
        # 标准化
        norm_f = [(features[j] - self._means[j]) / self._stds[j] for j in range(len(features))]
        
        distances = [self._euclidean(norm_f, c) for c in self.centroids]
        return distances.index(min(distances))
    
    def get_regime_advice(self, state):
        """根据检测到的状态返回策略参数建议"""
        if state == 0:
            return {
                'name': 'PANIC (恐慌反弹)',
                'buy_t': 0.08,       # 等跌8%才买(更深反弹)
                'sell_t': 0.10,      # 涨10%就卖
                'position_scale': 1.2,  # 可加大仓位
                'trend_filter': True,
                'note': '均值回归大概率成功'
            }
        elif state == 1:
            return {
                'name': 'EUPHORIA (亢奋回调)',
                'buy_t': 0.03,       # 小跌就买(快进快出)
                'sell_t': 0.08,      # 涨8%卖
                'position_scale': 0.8,
                'trend_filter': True,
                'note': '涨多了会回调'
            }
        else:
            return {
                'name': 'TREND (趋势上涨)',
                'buy_t': 0.15,       # 等跌15%才买(趋势中不轻易抄底)
                'sell_t': 0.15,      # 涨15%才卖(让利润奔跑)
                'position_scale': 0.5,
                'trend_filter': True,
                'note': '不要逆势,趋势是你的朋友'
            }

# ===================== 趋势过滤器 =====================
class TrendFilter:
    """
    趋势过滤器: 避免在"接飞刀"时买入
    基于EDA发现: 12%大跌后继续跌(t=-6.16)
    """
    def __init__(self, window=20):
        self.window = window
        self.prices = []
        self.volumes = []
        self.closes = []
    
    def update(self, close, volume):
        self.closes.append(close)
        self.volumes.append(volume)
        if len(self.closes) > self.window:
            self.closes = self.closes[-self.window:]
            self.volumes = self.volumes[-self.window:]
    
    def is_crash_mode(self):
        """检测是否处于暴跌模式"""
        if len(self.closes) < 10:
            return False
        
        # 最近10日最大跌幅
        max_drop = min((self.closes[i] - self.closes[max(0,i-5)]) / self.closes[max(0,i-5)]
                       for i in range(len(self.closes)-5, len(self.closes)))
        
        # 最近20日平均波动
        rets = [(self.closes[i] - self.closes[i-1]) / self.closes[i-1]
                for i in range(1, len(self.closes))]
        avg_vol = sum(abs(r) for r in rets) / len(rets) if rets else 0.1
        
        # 如果最近跌幅超过平均波动的3倍，认为是暴跌模式
        return max_drop < -3 * avg_vol
    
    def should_allow_buy(self, prev_close, current_price):
        """判断是否应该允许买入"""
        drop_pct = (current_price - prev_close) / prev_close
        
        # EDA发现: 12%大跌后继续跌
        # 所以如果当日跌幅超过10%，且处于暴跌模式，禁止买入
        if drop_pct <= -0.10 and self.is_crash_mode():
            return False
        
        return True

# ===================== V2.2 回测引擎 =====================
def run_v22_backtest(data, base_params, use_regime=True, use_trend_filter=True):
    """
    V2.2 状态依赖策略回测
    
    参数:
    - base_params: V2基础参数
    - use_regime: 是否使用状态检测
    - use_trend_filter: 是否使用趋势过滤器
    """
    shares = base_params['base_shares']
    total_pnl = 0.0
    total_trades = 0
    wins = 0; losses = 0
    max_drawdown = 0.0
    peak_equity = 0.0
    stop_count = 0; filter_count = 0
    
    turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
    
    trade_log = []
    regime_log = []
    trend_filter = TrendFilter(window=20)
    
    # 拟合状态检测器
    detector = RegimeDetector(lookback=30, n_states=3, warmup=20)
    regime_labels = detector.fit_predict(data)
    
    # 当前状态
    current_regime = 1
    regime_advice = detector.get_regime_advice(1)
    
    for i, bar in enumerate(data):
        price = bar['close']
        prev_close = data[i-1]['close'] if i > 0 else price
        
        # 更新趋势过滤器
        trend_filter.update(price, bar['volume'])
        
        # 权益计算
        equity = shares * price
        if equity > peak_equity: peak_equity = equity
        dd = (equity - peak_equity) / peak_equity if peak_equity > 0 else 0
        if dd < max_drawdown: max_drawdown = dd
        
        # 更新状态检测 (从第warmup天开始)
        if i >= 20:
            features = extract_features(data, i)
            current_regime = detector.predict_state(features)
            regime_advice = detector.get_regime_advice(current_regime)
        else:
            current_regime = 1  # 默认状态
            regime_advice = detector.get_regime_advice(1)
        
        regime_log.append({
            'date': bar['date'][:10],
            'regime': current_regime,
            'regime_name': regime_advice['name'],
        })
        
        # 获取动态参数
        if use_regime:
            sell_t = regime_advice['sell_t']
            buy_t = regime_advice['buy_t']
            pos_scale = regime_advice['position_scale']
        else:
            sell_t = base_params['sell_t']
            buy_t = base_params['buy_t']
            pos_scale = 1.0
        
        # =============== 涡轮A检查 ===============
        if turbo_a['active']:
            turbo_a['days'] += 1
            entry = turbo_a['entry']
            buyback = turbo_a['prev_close'] * (1 + base_params['a_offset'])
            
            # 止损检查
            stop_price = entry * (1 + base_params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_a['qty']
                total_pnl += pnl; shares += turbo_a['qty']
                total_trades += 1; stop_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_STOP', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': regime_advice['name']
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 正常买回
            if price <= buyback:
                pnl = (entry - price) * turbo_a['qty']
                total_pnl += pnl; shares += turbo_a['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'A_BACK', 'price': price, 'qty': turbo_a['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': regime_advice['name']
                })
                turbo_a = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查卖出信号
            sell_trigger = prev_close * (1 + sell_t)
            if price >= sell_trigger and shares > base_params['pos_min']:
                qty = min(int(base_params['trade_qty'] * pos_scale / 100) * 100,
                          shares - base_params['pos_min'])
                qty = max(100, qty)
                shares -= qty
                turbo_a = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'A_SELL', 'price': price, 'qty': qty, 'pnl': 0,
                    'date': bar['date'][:10], 'regime': regime_advice['name'],
                    'note': f'sell_t={sell_t:.0%}'
                })
        
        # =============== 涡轮B检查 ===============
        if turbo_b['active']:
            turbo_b['days'] += 1
            entry = turbo_b['entry']
            sellback = turbo_b['prev_close'] * (1 + base_params['b_offset'])
            
            # 止损检查
            stop_price = entry * (1 - base_params['stop_loss_pct'])
            if price <= stop_price:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl; shares -= turbo_b['qty']
                total_trades += 1; stop_count += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_STOP', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': regime_advice['name']
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
                continue
            
            # 正常卖出
            if price >= sellback:
                pnl = (price - entry) * turbo_b['qty']
                total_pnl += pnl; shares -= turbo_b['qty']
                total_trades += 1
                if pnl >= 0: wins += 1
                else: losses += 1
                trade_log.append({
                    'type': 'B_SELL', 'price': price, 'qty': turbo_b['qty'],
                    'pnl': round(pnl, 2), 'date': bar['date'][:10],
                    'regime': regime_advice['name']
                })
                turbo_b = {'active': False, 'entry': 0, 'qty': 0, 'prev_close': 0, 'days': 0}
        else:
            # 检查买入信号
            buy_trigger = prev_close * (1 - buy_t)
            if price <= buy_trigger and shares < base_params['pos_max']:
                # 趋势过滤器检查
                if use_trend_filter and not trend_filter.should_allow_buy(prev_close, price):
                    filter_count += 1
                    continue
                
                qty = min(int(base_params['trade_qty'] * pos_scale / 100) * 100,
                          base_params['pos_max'] - shares)
                qty = max(100, qty)
                shares += qty
                turbo_b = {'active': True, 'entry': price, 'qty': qty, 'prev_close': prev_close, 'days': 0}
                trade_log.append({
                    'type': 'B_BUY', 'price': price, 'qty': qty, 'pnl': 0,
                    'date': bar['date'][:10], 'regime': regime_advice['name'],
                    'note': f'buy_t={buy_t:.0%}'
                })
    
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    
    return {
        'total_pnl': round(total_pnl, 2),
        'total_trades': total_trades,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'max_drawdown': round(max_drawdown * 100, 2),
        'final_shares': shares,
        'stop_count': stop_count,
        'filter_count': filter_count,
        'trade_log': trade_log,
        'regime_log': regime_log,
        'regime_stats': detector.state_stats if hasattr(detector, 'state_stats') else {},
    }


def main():
    # 加载数据
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] {len(data)}个交易日 ({data[0]['date'][:10]} ~ {data[-1]['date'][:10]})")
    
    # V2基础参数
    V2_BASE = {
        'sell_t': 0.12, 'a_offset': -0.01, 'buy_t': 0.05, 'b_offset': 0.05,
        'trade_qty': 1000, 'pos_min': 7000, 'pos_max': 11000,
        'base_shares': 8894, 'stop_loss_pct': 0.05,
    }
    
    print("\n" + "="*70)
    print("  对比: V2原版 vs V2.2状态依赖")
    print("="*70)
    
    # V2原版回测
    print("\n[V2 原版] 无状态检测, 无趋势过滤")
    v2_result = run_v22_backtest(data, V2_BASE, use_regime=False, use_trend_filter=False)
    print(f"  盈亏=${v2_result['total_pnl']:,.2f} 交易={v2_result['total_trades']} "
          f"胜率={v2_result['win_rate']:.1f}% 回撤={v2_result['max_drawdown']:.2f}% "
          f"止损={v2_result['stop_count']}")
    
    # V2.2 完全版
    print("\n[V2.2 完全版] 状态检测 + 趋势过滤")
    v22_result = run_v22_backtest(data, V2_BASE, use_regime=True, use_trend_filter=True)
    print(f"  盈亏=${v22_result['total_pnl']:,.2f} 交易={v22_result['total_trades']} "
          f"胜率={v22_result['win_rate']:.1f}% 回撤={v22_result['max_drawdown']:.2f}% "
          f"止损={v2_result['stop_count']} 过滤={v22_result['filter_count']}")
    
    # 只用状态检测
    print("\n[V2.2 仅状态检测]")
    v22r_result = run_v22_backtest(data, V2_BASE, use_regime=True, use_trend_filter=False)
    print(f"  盈亏=${v22r_result['total_pnl']:,.2f} 交易={v22r_result['total_trades']} "
          f"胜率={v22r_result['win_rate']:.1f}% 回撤={v22r_result['max_drawdown']:.2f}%")
    
    # 只用趋势过滤
    print("\n[V2.2 仅趋势过滤]")
    v22t_result = run_v22_backtest(data, V2_BASE, use_regime=False, use_trend_filter=True)
    print(f"  盈亏=${v22t_result['total_pnl']:,.2f} 交易={v22t_result['total_trades']} "
          f"胜率={v22t_result['win_rate']:.1f}% 回撤={v22t_result['max_drawdown']:.2f}%")
    
    # 打印状态统计
    print("\n" + "="*70)
    print("  状态检测结果")
    print("="*70)
    for state, stats in v22_result.get('regime_stats', {}).items():
        print(f"  {state}: {stats['count']}天, "
              f"avg_sentiment={stats['avg_sentiment']:.2%}, "
              f"avg_vol={stats['avg_vol_proxy']:.2%}")
    
    # 打印部分交易日志
    print("\n" + "="*70)
    print("  V2.2 交易明细 (前10笔)")
    print("="*70)
    for t in v22_result['trade_log'][:10]:
        print(f"  {t['date']} {t['type']:8s} @${t['price']:.2f} qty={t['qty']} "
              f"pnl={t['pnl']:>8.2f} [{t.get('regime','?')}] {t.get('note','')}")
    
    # 保存完整报告
    report = {
        'timestamp': datetime.now().isoformat(),
        'data_range': {'start': data[0]['date'], 'end': data[-1]['date'], 'bars': len(data)},
        'v2_baseline': {k: v for k, v in v2_result.items() if k not in ('trade_log','regime_log')},
        'v22_full': {k: v for k, v in v22_result.items() if k not in ('trade_log','regime_log')},
        'v22_regime_only': {k: v for k, v in v22r_result.items() if k not in ('trade_log','regime_log')},
        'v22_filter_only': {k: v for k, v in v22t_result.items() if k not in ('trade_log','regime_log')},
        'trade_log': v22_result['trade_log'],
        'regime_log': v22_result['regime_log'],
    }
    
    out_path = Path(WORKSPACE) / "data" / "history" / "v22_backtest_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    main()
