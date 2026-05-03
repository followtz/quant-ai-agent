# -*- coding: utf-8 -*-
"""
BTDR "情绪"探索性数据分析 (EDA)
目标：理解价格偏离前收的统计特性，为机器学习优化做准备

步骤：
1. 加载历史数据
2. 计算"情绪"指标 (price / prev_close - 1)
3. 分析"情绪极端"后的均值回归概率
4. 识别不同的"情绪阶段" (regime)
5. 可视化结果
"""
import sys, json, math
from datetime import datetime
from pathlib import Path
import csv

WORKSPACE = r'C:\Users\Administrator\.qclaw\workspace-agent-40f5a53e'
sys.path.insert(0, WORKSPACE)

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

def calculate_returns(data):
    """计算收益率和情绪指标"""
    results = []
    for i, bar in enumerate(data):
        if i == 0:
            continue
        prev_close = data[i-1]['close']
        close = bar['close']
        
        # 情绪指标1：简单涨跌幅
        sentiment_simple = (close - prev_close) / prev_close
        
        # 情绪指标2：日内反转
        open_price = bar['open']
        intraday_reversal = (close - open_price) / open_price
        
        # 情绪指标3：成交量加权
        avg_vol = sum(b['volume'] for b in data[max(0,i-20):i]) / min(i, 20)
        vol_weighted = sentiment_simple * (bar['volume'] / avg_vol) if avg_vol > 0 else 0
        
        # 未来N日收益（用于分析均值回归）
        future_ret_1d = None
        future_ret_3d = None
        future_ret_5d = None
        if i + 1 < len(data):
            future_ret_1d = (data[i+1]['close'] - close) / close
        if i + 3 < len(data):
            future_ret_3d = (data[i+3]['close'] - close) / close
        if i + 5 < len(data):
            future_ret_5d = (data[i+5]['close'] - close) / close
        
        results.append({
            'date': bar['date'],
            'sentiment_simple': sentiment_simple,
            'sentiment_intraday': intraday_reversal,
            'sentiment_vol_weighted': vol_weighted,
            'future_ret_1d': future_ret_1d,
            'future_ret_3d': future_ret_3d,
            'future_ret_5d': future_ret_5d,
            'close': close,
            'prev_close': prev_close,
        })
    
    return results

def analyze_mean_reversion(sentiment_data, threshold, future_key='future_ret_1d'):
    """
    分析"情绪极端"后的均值回归概率
    返回：
    - 触发次数
    - 平均未来收益
    - 胜率（未来收益>0的概率）
    - t-statistic (显著性)
    """
    # 筛选情绪极端日
    extreme_up = [s for s in sentiment_data if s['sentiment_simple'] >= threshold]  # 大涨
    extreme_down = [s for s in sentiment_data if s['sentiment_simple'] <= -threshold]  # 大跌
    
    results = {}
    for label, extreme in [('up', extreme_up), ('down', extreme_down)]:
        if not extreme:
            results[label] = {'count': 0, 'avg_ret': 0, 'win_rate': 0, 't_stat': 0}
            continue
        
        future_returns = [s[future_key] for s in extreme if s[future_key] is not None]
        if not future_returns:
            results[label] = {'count': len(extreme), 'avg_ret': None, 'win_rate': None, 't_stat': None}
            continue
        
        avg_ret = sum(future_returns) / len(future_returns)
        win_rate = sum(1 for r in future_returns if r > 0) / len(future_returns)
        
        # t-test
        n = len(future_returns)
        std_ret = (sum((r - avg_ret)**2 for r in future_returns) / (n-1))**0.5
        t_stat = (avg_ret / (std_ret / (n**0.5))) if std_ret > 0 else 0
        
        results[label] = {
            'count': len(extreme),
            'valid_count': len(future_returns),
            'avg_ret': round(avg_ret * 100, 4),  # 转百分比
            'win_rate': round(win_rate * 100, 2),
            't_stat': round(t_stat, 4),
            'significant': abs(t_stat) > 1.96,  # 95%置信度
        }
    
    return results

def regime_detection_hmm(sentiment_data, n_states=3):
    """
    用Hidden Markov Model识别"情绪阶段"
    简化版：用K-means聚类代替（避免依赖hmmlearn库）
    """
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        
        # 准备特征矩阵
        features = []
        for s in sentiment_data:
            if s['future_ret_1d'] is not None:
                features.append([
                    s['sentiment_simple'],
                    s['sentiment_intraday'],
                    s['future_ret_1d'],
                ])
        
        if len(features) < n_states * 5:
            return None, "数据不足"
        
        # 标准化
        scaler = StandardScaler()
        X = scaler.fit_transform(features)
        
        # K-means聚类
        kmeans = KMeans(n_clusters=n_states, random_state=42)
        labels = kmeans.fit_predict(X)
        
        # 分析每个簇的统计特性
        clusters = {}
        for i in range(n_states):
            cluster_data = [features[j] for j in range(len(features)) if labels[j] == i]
            if cluster_data:
                avg_sentiment = sum(d[0] for d in cluster_data) / len(cluster_data)
                avg_future = sum(d[2] for d in cluster_data) / len(cluster_data)
                clusters[f'state_{i}'] = {
                    'count': len(cluster_data),
                    'avg_sentiment': round(avg_sentiment * 100, 4),
                    'avg_future_ret': round(avg_future * 100, 4),
                }
        
        return labels, clusters
    
    except ImportError:
        return None, "需要安装scikit-learn: pip install scikit-learn"

def main():
    # 加载数据
    csv_path = r'C:\Trading\data\history\BTDR_daily_120d.csv'
    data = load_csv_data(csv_path)
    print(f"[数据] 加载{len(data)}个交易日")
    
    # 计算情绪指标
    sentiment_data = calculate_returns(data)
    print(f"[情绪] 计算{len(sentiment_data)}个交易日的情绪指标")
    
    # 分析不同阈值下的均值回归特性
    print("\n" + "="*70)
    print("  均值回归分析：不同情绪阈值下的未来收益")
    print("="*70)
    print(f"{'阈值':<10} {'事件':<10} {'次数':<8} {'平均收益':<12} {'胜率':<10} {'t-stat':<12} {'显著?':<8}")
    print("-" * 70)
    
    for threshold in [0.03, 0.05, 0.08, 0.10, 0.12]:
        results = analyze_mean_reversion(sentiment_data, threshold)
        
        for label in ['down', 'up']:
            r = results[label]
            if r['count'] > 0:
                event = "大跌" if label == 'down' else "大涨"
                sig = "是" if r.get('significant') else "否"
                print(f"{threshold:>8.0%} {event:<10} {r['valid_count']:<8} "
                      f"{r['avg_ret']:>10.2f}% {r['win_rate']:>8.1f}% "
                      f"{r['t_stat']:>10.2f} {sig:<8}")
    
    # 尝试识别市场状态
    print("\n" + "="*70)
    print("  市场状态识别 (K-means聚类)")
    print("="*70)
    
    labels, clusters = regime_detection_hmm(sentiment_data, n_states=3)
    
    if labels is not None:
        print(f"  识别到{len(clusters)}个市场状态：")
        for state, props in clusters.items():
            print(f"  {state}: {props['count']}天, 平均情绪={props['avg_sentiment']:.2f}%, "
                  f"平均未来收益={props['avg_future_ret']:.2f}%")
    else:
        print(f"  聚类失败: {clusters}")
    
    # 保存详细结果
    output = {
        'timestamp': datetime.now().isoformat(),
        'data_range': {
            'start': data[0]['date'],
            'end': data[-1]['date'],
            'count': len(data),
        },
        'sentiment_stats': {
            'mean': round(sum(s['sentiment_simple'] for s in sentiment_data) / len(sentiment_data) * 100, 4),
            'std': round((sum((s['sentiment_simple'] - 0)**2 for s in sentiment_data) / len(sentiment_data))**0.5 * 100, 4),
            'min': round(min(s['sentiment_simple'] for s in sentiment_data) * 100, 4),
            'max': round(max(s['sentiment_simple'] for s in sentiment_data) * 100, 4),
        },
        'mean_reversion_analysis': {},
        'regime_detection': clusters if labels is not None else "failed",
    }
    
    # 保存各阈值分析结果
    for threshold in [0.03, 0.05, 0.08, 0.10, 0.12]:
        output['mean_reversion_analysis'][str(threshold)] = analyze_mean_reversion(sentiment_data, threshold)
    
    # 保存文件
    out_path = Path(WORKSPACE) / "data" / "history" / "sentiment_eda_report.json"
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n[报告已保存] {out_path}")

if __name__ == '__main__':
    main()