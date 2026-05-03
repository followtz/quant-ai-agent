# AI助手Edge CDP使用规则

> **⚠️ 强制规则（2026-04-23生效）**

## 核心规则：永远不重新打开已登录的AI助手标签页

### 原因
Edge浏览器CDP模式下的已登录标签页：
- 豆包 Tab 0：已扫码登录 ✅
- 元宝 Tab 1：已扫码登录 ✅  
- 千问 Tab 2：已扫码登录 ✅

如果用 `xb run --browser edge open <url>` 重新打开，会创建一个**新的未登录标签页**，导致：
1. 需要重新扫码/登录
2. 无法复用已登录状态
3. 浪费测试时间

### 正确的操作方式

#### 查看当前标签页列表
```bash
& node "C:\Program Files\QClaw\resources\openclaw\config\skills\xbrowser\scripts\xb.cjs" run --browser edge tab
```
返回示例：
```json
{
  "tabs": [
    {"index": 0, "title": "豆包", "url": "...", "active": false},
    {"index": 1, "title": "元宝", "url": "...", "active": false},
    {"index": 2, "title": "千问", "url": "...", "active": true}
  ]
}
```

#### 切换到指定标签页
使用xb `tab N` 命令（从0起）：
```bash
# 切换到Tab 0（豆包）
& node "xb.cjs" run --browser edge tab 0

# 切换到Tab 1（元宝）
& node "xb.cjs" run --browser edge tab 1

# 切换到Tab 2（千问）
& node "xb.cjs" run --browser edge tab 2
```

⚠️ 错误方式：`press Control+1` 不生效！必须用 `tab N` 命令。

#### 验证当前页面URL
```bash
& node "xb.cjs" run --browser edge get url
```
必须返回正确的助手URL才可继续操作。

### DOM元素交互标准流程（每个助手通用）

```
1. press "Control+N"         → 切换到目标标签
2. wait --load networkidle   → 等待页面加载完成
3. snapshot -i               → 获取元素快照（每次操作前必须重新snapshot）
4. fill @eXXX "消息内容"      → 填写输入框
5. snapshot -i               → 重新获取（发送按钮状态可能变化）
6. click @eYYY               → 点击发送按钮
7. wait --load networkidle   → 等待回复
8. get text @eZZZ            → 读取回复内容（或截图验证）
```

### 各助手DOM元素（已验证，2026-04-23）

| 助手 | 标签 | 输入框 ref | 发送方式 | 状态 |
|------|------|-----------|---------|------|
| 千问 | Tab 2 | e152 (textbox "向千问提问") | click e153 | ✅ 已验证 |
| 豆包 | Tab 0 | e501 (textbox "发消息...") | click e502 | ✅ 已验证 |
| 元宝 | Tab 1 | e40 (contenteditable div) | press Enter | ✅ 已验证 |

**关键注意**：
- 豆包发送按钮在展开菜单(e432)内，fill后需重新snapshot获取e502
- 元宝无独立发送按钮，必须用 `press Enter`
- 千问发送按钮fill后从disabled变为enabled，需重新snapshot获取最新ref
- 所有ref在页面重新渲染后会变化，每次操作前必须先 `snapshot -i`

### 错误操作示例

❌ 错误做法：
```bash
# 绝对禁止！会创建新未登录标签页
& node "xb.cjs" run --browser edge open "https://www.doubao.com/chat/"
& node "xb.cjs" run --browser edge open "https://yuanbao.tencent.com/chat/naQivTmsDa"
& node "xb.cjs" run --browser edge open "https://www.qianwen.com/chat/"
```

✅ 正确做法：
```bash
# 切换到Tab 0（豆包）
& node "xb.cjs" run --browser edge press "Control+1"

# 切换到Tab 1（元宝）
& node "xb.cjs" run --browser edge press "Control+2"

# 切换到Tab 2（千问）
& node "xb.cjs" run --browser edge press "Control+3"
```

### 遇到登录页面时的处理

如果 `get url` 返回登录页面URL，说明该标签页已过期登出：
1. **不重新打开**：不要用 `open` 创建新标签
2. **通知用户**：推送企业微信告警，告知哪个助手需要重新扫码登录
3. **等待用户操作**：用户扫码完成后继续

### 相关文件
- 路由SOP：`utils/ai_routing_sop.md`
- 桥接模块：`utils/ai_assistant_bridge.py`
- 监控脚本：`utils/assistant_monitor.py`
