# 明日当空 · 微信云托管部署指南

## 一、前置准备

1. 已注册微信小程序，AppID：`wxf9cd48540ad006cd`（或你的 AppID）
2. 开通 [微信云托管](https://cloud.weixin.qq.com/cloudrun)
3. 开通 [云开发](https://cloud.weixin.qq.com/cloudbase)（与云托管同一环境）

---

## 二、创建云托管服务

### 1. 进入控制台

[微信云托管控制台](https://cloud.weixin.qq.com/cloudrun) → 选择你的小程序 → **新建服务**

| 配置项 | 建议值 |
|--------|--------|
| 服务名称 | `mingri-api` |
| 端口 | `80` |
| 公网访问 | **开启** |

### 2. 上传代码部署

**重要：zip 根目录必须是代码文件，不要包含 `server/` 子文件夹！**

**推荐：运行打包脚本**

```powershell
cd server
powershell -ExecutionPolicy Bypass -File pack-zip.ps1
```

会在项目根目录生成 `mingri-api.zip`，直接上传此文件。

**云托管构建设置：**

| 配置项 | 填法 |
|--------|------|
| Dockerfile 路径 | `Dockerfile` |
| 构建目录 | `.`（zip 根目录） |
| 端口 | `80` |
| 公网访问 | 开启 |

> 首次构建约 5–10 分钟。若失败，查看日志是否为 pip 安装问题（已改用官方 PyPI 源）。

### 3. 实例配置建议

| 配置 | 建议 |
|------|------|
| CPU | 0.5 ~ 1 核 |
| 内存 | 1 ~ 2 GB |
| 最小实例数 | **1**（避免交易日冷启动） |
| 最大实例数 | 3 |

---

## 三、获取访问地址

发布成功后，在服务详情页复制 **公网访问地址**，形如：

```
https://mingri-api-xxxxxxxx.sh.run.tcloudbase.com
```

浏览器访问：

```
https://你的地址/api/health
```

应返回：`{"status":"ok",...}`

---

## 四、配置小程序

### 方式 A：公网 HTTPS（推荐）

编辑 `utils/config.js`：

```js
USE_CLOUD_CALL: false,
API_BASE: 'https://mingri-api-xxxxxxxx.sh.run.tcloudbase.com',
```

### 方式 B：云调用（免 request 域名）

编辑 `utils/config.js`：

```js
USE_CLOUD_CALL: true,
CLOUD_ENV: '你的云开发环境ID',
CLOUD_SERVICE: 'mingri-api',
API_BASE: 'https://mingri-api-xxxxxxxx.sh.run.tcloudbase.com',  // OCR 上传仍需要
```

---

## 五、微信公众平台配置

登录 [mp.weixin.qq.com](https://mp.weixin.qq.com) → **开发 → 开发管理 → 开发设置 → 服务器域名**

| 类型 | 域名（不要带路径） |
|------|-------------------|
| request 合法域名 | `https://mingri-api-xxx.sh.run.tcloudbase.com` |
| uploadFile 合法域名 | 同上（持仓 OCR 上传需要） |

> 使用「方式 B 云调用」时，GET 接口可不配 request 域名，但 **uploadFile 仍需配置**。

---

## 六、上传并发布小程序

1. 微信开发者工具 → **上传** 代码
2. 公众平台 → **版本管理** → 提交审核
3. 审核通过 → **发布**

---

## 七、费用参考

- 云托管按实例运行时长 + 流量计费
- 最小实例数设为 1 时，约 **几十元/月** 起（视配置而定）
- 可在控制台设置 **费用告警**

---

## 八、常见问题

| 问题 | 处理 |
|------|------|
| 构建失败 | 查看构建日志，多为依赖安装超时，可重试 |
| 小程序请求失败 | 检查 API_BASE、服务器域名是否一致 |
| 数据加载慢 | 首次请求 akshare 较慢，属正常；可调最小实例数=1 |
| OCR 失败 | 镜像含 rapidocr，首次识别较慢；可手动输入仓位 |
| 本地开发 | `USE_CLOUD_CALL: false`，`API_BASE: 'http://127.0.0.1:8000'`，勾选不校验域名 |

---

## 九、订阅消息（按情绪动态推送）

云托管 **环境变量** 必填：

| 变量 | 说明 |
|------|------|
| `WX_SECRET` | 小程序 AppSecret（公众平台 → 开发管理 → 开发设置） |
| `WX_APPID` | 默认已填 `wxf9cd48540ad006cd`，可按需覆盖 |
| `TMPL_SENTIMENT` | 订阅模板 ID（默认已内置） |
| `CRON_SECRET` | 定时任务密钥（自选一串，用于 `/api/subscribe/cron-daily`） |

**推送内容非写死**：每日根据昨日收盘情绪计算后填入模板字段：

- `thing7`：提醒类型（如 市场情绪·中性 / 龙空龙·个人信号）
- `character_string2`：情绪分 + 状态标签（如 情绪41分·偏谨慎）
- `time3`：推送时间
- `thing12`：客观盘面描述（随情绪原因变化，不含仓位建议）

**预览今日将发什么**（部署后浏览器访问）：

`GET https://你的域名/api/subscribe/preview`

**每日 09:15 定时**：云托管「定时触发」POST  
`/api/subscribe/cron-daily`，Header：`X-Cron-Secret: 你的CRON_SECRET`

---

## 十、MySQL 数据存储（首页秒开 + 历史归档）

**不需要把密码发给任何人**，只需在云托管控制台配置环境变量，服务启动后自动连库。

### 1. 配置环境变量

云托管 → **mingri-api** → 服务设置 → 环境变量：

| 变量 | 说明 |
|------|------|
| `MYSQL_ADDRESS` | MySQL 页 **内网地址**（如 `10.x.x.x:3306`） |
| `MYSQL_USERNAME` | `root` |
| `MYSQL_PASSWORD` | 开通 MySQL 时设置的密码 |
| `MYSQL_DATABASE` | 可选，默认 `mingri` |
| `CRON_SECRET` | 定时任务密钥（与订阅推送共用） |

### 2. 自动创建的表

| 表名 | 用途 |
|------|------|
| `home_sentiment_cache` | 首页整包 JSON，接口秒回 |
| `daily_market` | 每个交易日：`metrics` / 情绪 / 8项指标 / **grid9(9) + peripheral(3) + auction(6) + indicatorSections(18)** |

> 表字符集为 **utf8mb4**（支持指标里的 emoji）。若历史同步报 `Incorrect string value`，重新部署最新代码后会自动 `ALTER TABLE` 转换字符集，再执行一次 sync-history。

查询某日归档：`GET /api/sentiment/day?date=20260521`

### 3. 部署后验证

```
GET  https://你的域名/api/cache/home-status
POST https://你的域名/api/cache/sync-history?days=60
     Header: X-Cron-Secret: 你的CRON_SECRET
```

接口会**立即返回**（后台同步约需数分钟）。用下面命令查看进度：

```
GET https://你的域名/api/cache/home-status
```

看 `historySync.running` 是否为 `false`，且 `mysql.history.rowCount > 0`。

### 4. 定时任务（两种方式，二选一）

#### 方式 A：代码内置（推荐，已默认开启）

服务启动后自动按 **北京时间、周一至周五** 执行：

| 时间 | 任务 |
|------|------|
| 06:00 | 预热首页缓存 |
| 08:50 | 再次预热首页 |
| **09:00** | **外围情绪入库**（MySQL 归档 9:00 快照） |
| **09:00–15:00** | **外围情绪每 10 分钟刷新展示** |
| **09:30–15:00** | **盘中实时情绪每 2 分钟刷新**（展示分 + 盘中板块） |
| **09:26** | **今日竞价情绪初更** → MySQL |
| **09:35** | **今日竞价情绪固化** → MySQL |
| 09:15 | 订阅消息推送 |
| **15:05** | **昨日情绪初更**（东财收盘快照 → MySQL） |
| **18:00** | **昨日情绪固化** → MySQL |
| 18:05 | 同步 60 天历史到 MySQL |

**无需在云托管控制台再配定时触发**，重新部署最新代码即可。

可选环境变量：

| 变量 | 说明 |
|------|------|
| `INTERNAL_CRON` | 默认 `true`；设为 `false` 则关闭内置定时 |
| `SYNC_HISTORY_DAYS` | 默认 `60`，18:05 同步天数 |

日志中搜 `internal cron` 可确认是否执行。

#### 方式 B：云托管控制台「定时触发」（备用）

若关闭了内置定时，或想用控制台统一管理，按下面配置。

1. 打开 [微信云托管控制台](https://cloud.weixin.qq.com/cloudrun)
2. 进入你的环境 → 左侧 **拓展功能** → **定时触发**（或 **服务管理 → mingri-api → 定时触发**）
3. 点击 **新建**，依次创建 9 条（Cron 时区均为 **UTC+8**）：

| 名称 | Cron 表达式 | 方法 | 路径 | 请求头 |
|------|-------------|------|------|--------|
| warm-home-600 | `0 6 * * 1-5` | POST | `/api/cache/warm-home` | `X-Cron-Secret: 你的CRON_SECRET` |
| warm-home-850 | `0 50 8 * * 1-5` | POST | `/api/cache/warm-home` | 同上 |
| peripheral-0900 | `0 9 * * 1-5` | POST | `/api/cache/snapshot-daily?phase=0900` | 同上 |
| auction-0926 | `26 9 * * 1-5` | POST | `/api/cache/snapshot-daily?phase=0926` | 同上 |
| auction-0935 | `35 9 * * 1-5` | POST | `/api/cache/snapshot-daily?phase=0935` | 同上 |
| subscribe-daily | `15 9 * * 1-5` | POST | `/api/subscribe/cron-daily` | 同上 |
| snapshot-1505 | `5 15 * * 1-5` | POST | `/api/cache/snapshot-daily?phase=1505` | 同上 |
| snapshot-1800 | `0 18 * * 1-5` | POST | `/api/cache/snapshot-daily?phase=1800` | 同上 |
| sync-history | `5 18 * * 1-5` | POST | `/api/cache/sync-history?days=60` | 同上 |

> 外围 10 分钟刷新由内置 `IntervalTrigger` 完成，无需控制台配置。

4. **目标服务** 选 `mingri-api`，**公网/内网** 选内网（同环境优先内网）
5. 保存后可在触发器详情 **手动执行一次** 测试

> 若控制台 Cron 为 **6 段**（无秒），则用：`0 6 * * 1-5`、`50 8 * * 1-5`、`0 9 * * 1-5`、`26 9 * * 1-5`、`35 9 * * 1-5`、`15 9 * * 1-5`、`5 15 * * 1-5`、`0 18 * * 1-5`、`5 18 * * 1-5`

手动测试（PowerShell）：

```powershell
$base = "https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com"
$secret = "mydailyjobpass123"
# 启动后台同步（秒回，不会 504）
Invoke-WebRequest -Method POST -Uri "$base/api/cache/sync-history?days=60" -Headers @{"X-Cron-Secret"=$secret}
# 停止当前同步
Invoke-WebRequest -Method POST -Uri "$base/api/cache/stop-sync-history" -Headers @{"X-Cron-Secret"=$secret}
# 轮询进度（running=false 且 rowCount>0 即完成）
Invoke-WebRequest -Uri "$base/api/cache/home-status"
```

---

## 十一、目录说明

```
server/
├── Dockerfile          # 云托管镜像
├── requirements.txt    # Python 依赖
├── app.py              # FastAPI 入口
├── home_cache.py       # 首页预计算缓存
├── db_store.py         # MySQL 持久化
├── fetcher.py          # akshare 数据
├── sentiment.py        # 情绪评分
├── subscribe_msg.py    # 订阅消息动态内容与发送
├── ocr.py              # 持仓 OCR
└── 云托管部署.md        # 本文档
```
