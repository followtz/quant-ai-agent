# TOOLS.md — 本地工具配置

## 服务器
- **IP/主机**: VM-0-16-ubuntu（腾讯云轻量）
- **用户**: ubuntu
- **配置**: 4C / 16G / 180G / 2000G月流量
- **OS**: Ubuntu 22.04, Linux 6.8.0-111-generic

## Futu OpenD
- **版本**: 10.4.6408
- **PID**: 215479（当前）
- **Python SDK**: futu-api 10.4.6408
- **运行方式**: AppImage GUI 已登录

## 模型
- **主模型**: DeepSeek V4 Flash (deepseek/deepseek-v4-flash)
- **深度思考**: DeepSeek V4 Pro (手动切换)
- **外脑 API**:
  - 千问 Qwen3.6-plus（阿里云）
  - 豆包 Seed 2.0 Pro（免费~200万Token/日）

## GitHub
- **用户**: followtz
- **仓库**: (待创建)
- **SSH**: ed25519 密钥已认证

## 企业微信
- **Bot**: StreamableHttp MCP 端点
- **接收人**: TongZhuang
- **端点 Key**: 从 wechat_push.py 提取

## QQ邮箱
- **账号**: 126959876@qq.com
- **SMTP**: smtp.qq.com:465 (SSL)
- **授权码**: xhnymfksajsobgfj

## Python 关键包
- futu-api==10.4.6408
- numpy
- pandas
