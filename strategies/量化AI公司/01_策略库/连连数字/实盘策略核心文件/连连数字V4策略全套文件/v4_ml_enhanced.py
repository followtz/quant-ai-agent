# -*- coding: utf-8 -*-
"""
连连数字V4 增强ML模块 (FinRL风格)
基于GitHub学习成果优化:
- 来源: AI4Finance-Foundation/FinRL-Trading
- 来源: je-suis-tm/quant-trading 多因子模型

增强内容:
1. 多模型集成 (RF + GBM + LR)
2. 在线学习能力 (增量更新)
3. 特征重要性追踪
4. 波动率特征 (VIX相关)
5. 多时间框架特征
"""
import numpy as np
import pandas as pd
import json
import logging
from datetime import datetime
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.calibration import CalibratedClassifierCV

# ========== 配置 ==========
ML_MODEL_DIR = Path("C:/Trading/data/ml_models")
ML_MODEL_DIR.mkdir(exist_ok=True, parents=True)

class V4EnhancedML:
    """
    V4增强ML模块
    多模型集成 + 在线学习
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # 模型参数
        self.confidence_threshold = self.config.get('ml_confidence', 0.55)
        self.lookback = self.config.get('ml_lookback', 60)
        
        # 集成模型
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
        self.model_trained = False
        self.feature_importance = {}
        
        # 在线学习参数
        self.online_batch_size = 20
        self.retrain_threshold = 100  # 积累100个新样本后重训
        
        # 特征列表
        self.feature_cols = [
            # 基础特征
            'returns', 'rsi', 'macd', 'macd_signal',
            'zscore', 'bb_position',
            # V3.1增强特征
            'volatility_5d', 'volatility_20d',
            'momentum_5d', 'momentum_10d',
            'volume_ratio',
            # 多时间框架
            'ma_5', 'ma_10', 'ma_20',
            'price_relative_ma5', 'price_relative_ma20',
            # 波动率特征
            'vix_proxy', 'volatility_regime'
        ]
        
        # 训练历史
        self.train_history = []
        
    def calculate_enhanced_features(self, df):
        """
        计算增强特征
        基于多因子模型和多时间框架分析
        """
        df = df.copy()
        
        # 1. 基础特征
        df['returns'] = df['close'].pct_change()
        
        # 2. 波动率特征 (V3.1新增)
        df['volatility_5d'] = df['returns'].rolling(5).std()
        df['volatility_20d'] = df['returns'].rolling(20).std()
        
        # 3. 动量特征
        df['momentum_5d'] = df['close'].pct_change(5)
        df['momentum_10d'] = df['close'].pct_change(10)
        
        # 4. 成交量特征
        if 'volume' in df.columns:
            df['volume_ma'] = df['volume'].rolling(20).mean()
            df['volume_ratio'] = df['volume'] / df['volume_ma']
        else:
            df['volume_ratio'] = 1.0
        
        # 5. 多时间框架均线
        for window in [5, 10, 20]:
            df[f'ma_{window}'] = df['close'].rolling(window).mean()
            df[f'price_relative_ma{window}'] = (df['close'] - df[f'ma_{window}']) / df[f'ma_{window}']
        
        # 6. RSI (已有)
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        df['rsi'] = 100 - (100 / (1 + gain / loss))
        
        # 7. MACD (已有)
        ema12 = df['close'].ewm(span=12).mean()
        ema26 = df['close'].ewm(span=26).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        
        # 8. 布林带 (已有)
        ma20 = df['close'].rolling(20).mean()
        std20 = df['close'].rolling(20).std()
        df['bb_mid'] = ma20
        df['bb_upper'] = ma20 + 2 * std20
        df['bb_lower'] = ma20 - 2 * std20
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
        
        # 9. Z-Score (已有)
        df['zscore'] = (df['close'] - ma20) / std20
        
        # 10. 波动率 regime (V3.1新增)
        # 低波动: volatility_20d < 0.02
        # 中波动: 0.02 <= volatility_20d < 0.05
        # 高波动: volatility_20d >= 0.05
        df['volatility_regime'] = pd.cut(
            df['volatility_20d'],
            bins=[-np.inf, 0.02, 0.05, np.inf],
            labels=[0, 1, 2]
        ).astype(float)
        
        # 11. VIX代理指标 (使用波动率模拟)
        # 当市场波动时，波动率会上升
        df['vix_proxy'] = df['volatility_20d'] * 100  # 缩放到类似VIX的数值
        
        return df
    
    def prepare_training_data(self, df):
        """
        准备训练数据
        目标: 未来3天收益 > 2% 为买入, < -2% 为卖出, 其他为持有
        """
        df = self.calculate_enhanced_features(df)
        
        # 创建目标变量
        future_return = df['close'].shift(-3) / df['close'] - 1
        df['target'] = 0
        df.loc[future_return > 0.02, 'target'] = 1
        df.loc[future_return < -0.02, 'target'] = -1
        
        # 过滤有效特征
        available_features = [f for f in self.feature_cols if f in df.columns]
        
        # 清理数据
        df_clean = df.dropna(subset=available_features + ['target'])
        
        if len(df_clean) < 30:
            self.logger.warning("[ML增强] 数据不足30条，无法训练")
            return None, None
        
        X = df_clean[available_features].values
        y = df_clean['target'].values
        
        return X, y, available_features
    
    def train(self, df):
        """
        训练集成模型
        """
        self.logger.info("[ML增强] 开始训练集成模型...")
        
        result = self.prepare_training_data(df)
        if result[0] is None:
            return False
            
        X, y, feature_names = result
        
        # 标准化
        X_scaled = self.scaler.fit_transform(X)
        
        # 训练每个模型
        for name, model in self.models.items():
            self.logger.info(f"[ML增强] 训练模型: {name}")
            model.fit(X_scaled, y)
        
        # 计算特征重要性
        if hasattr(self.models['rf'], 'feature_importances_'):
            importances = self.models['rf'].feature_importances_
            self.feature_importance = dict(zip(feature_names, importances))
            self._log_feature_importance()
        
        self.model_trained = True
        
        # 保存训练历史
        self.train_history.append({
            'timestamp': datetime.now().isoformat(),
            'samples': len(X),
            'features': len(feature_names),
            'accuracy': self._evaluate(X_scaled, y)
        })
        
        self.logger.info(f"[ML增强] 训练完成，样本数: {len(X)}")
        return True
    
    def _evaluate(self, X, y):
        """评估模型"""
        try:
            predictions = self.models['rf'].predict(X)
            accuracy = sum(predictions == y) / len(y)
            return accuracy
        except:
            return 0.5
    
    def _log_feature_importance(self):
        """记录特征重要性"""
        if not self.feature_importance:
            return
        
        sorted_features = sorted(
            self.feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        self.logger.info("[ML增强] Top 10 特征重要性:")
        for name, importance in sorted_features:
            self.logger.info(f"  {name}: {importance:.4f}")
    
    def predict(self, df):
        """
        集成预测
        返回: (预测方向, 置信度, 概率分布)
        """
        if not self.model_trained:
            return 0, 0.5, {'up': 0.33, 'neutral': 0.34, 'down': 0.33}
        
        df = self.calculate_enhanced_features(df)
        
        # 获取最新数据
        available_features = [f for f in self.feature_cols if f in df.columns]
        X = df[available_features].iloc[-1:].values
        X_scaled = self.scaler.transform(X)
        
        # 集成预测 (投票机制)
        votes = []
        probabilities = []
        
        for name, model in self.models.items():
            pred = model.predict(X_scaled)[0]
            proba = model.predict_proba(X_scaled)[0]
            votes.append(pred)
            probabilities.append(proba)
        
        # 平均概率
        avg_proba = np.mean(probabilities, axis=0)
        classes = list(self.models['rf'].classes_)
        
        # 获取各方向概率
        up_prob = avg_proba[classes.index(1)] if 1 in classes else 0.33
        down_prob = avg_proba[classes.index(-1)] if -1 in classes else 0.33
        
        # 最终预测 (多数投票)
        final_pred = 1 if votes.count(1) > votes.count(-1) else (-1 if votes.count(-1) > votes.count(0) else 0)
        
        # 置信度
        confidence = max(up_prob, down_prob) if final_pred != 0 else 0.5
        
        return final_pred, confidence, {'up': up_prob, 'neutral': 1-up_prob-down_prob, 'down': down_prob}
    
    def online_learn(self, new_data):
        """
        在线学习 (增量更新)
        当新数据累积到阈值时触发
        """
        # 这个功能需要更复杂实现，暂时标记为待扩展
        self.logger.info("[ML增强] 在线学习功能待实现")
        pass
    
    def save_model(self, path=None):
        """保存模型"""
        import pickle
        path = path or ML_MODEL_DIR / "v4_enhanced_ml.pkl"
        
        model_data = {
            'models': self.models,
            'scaler': self.scaler,
            'feature_importance': self.feature_importance,
            'config': self.config,
            'train_history': self.train_history
        }
        
        with open(path, 'wb') as f:
            pickle.dump(model_data, f)
        
        self.logger.info(f"[ML增强] 模型已保存: {path}")
    
    def load_model(self, path=None):
        """加载模型"""
        import pickle
        path = path or ML_MODEL_DIR / "v4_enhanced_ml.pkl"
        
        if not Path(path).exists():
            self.logger.warning(f"[ML增强] 模型文件不存在: {path}")
            return False
        
        try:
            with open(path, 'rb') as f:
                model_data = pickle.load(f)
            
            self.models = model_data['models']
            self.scaler = model_data['scaler']
            self.feature_importance = model_data.get('feature_importance', {})
            self.config = model_data.get('config', {})
            self.train_history = model_data.get('train_history', [])
            self.model_trained = True
            
            self.logger.info(f"[ML增强] 模型已加载: {path}")
            return True
        except Exception as e:
            self.logger.error(f"[ML增强] 加载失败: {e}")
            return False


# ========== 测试代码 ==========
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # 模拟数据
    dates = pd.date_range('2024-01-01', periods=200, freq='D')
    np.random.seed(42)
    
    price = 100 + np.cumsum(np.random.randn(200) * 2)
    df = pd.DataFrame({
        'date': dates,
        'open': price + np.random.randn(200),
        'high': price + abs(np.random.randn(200)) * 2,
        'low': price - abs(np.random.randn(200)) * 2,
        'close': price,
        'volume': np.random.randint(1000000, 5000000, 200)
    })
    
    # 测试
    ml = V4EnhancedML()
    
    if ml.train(df):
        pred, conf, proba = ml.predict(df)
        print(f"\n预测: {pred}, 置信度: {conf:.2f}")
        print(f"概率: {proba}")
        
        # 保存
        ml.save_model()
