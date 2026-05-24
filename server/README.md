# 明日当空 · 数据服务

## 启动

```bash
cd server
pip install -r requirements.txt
python app.py
```

或双击 `start.bat`

服务地址：`http://127.0.0.1:8000`

## API

| 接口 | 说明 |
|------|------|
| GET /api/health | 健康检查 |
| GET /api/sentiment/today | 首页情绪数据 |
| GET /api/sentiment/history?days=30 | 历史数据 |
| GET /api/sentiment/day?date=YYYYMMDD | 某日指标归档 |
| GET /api/cache/home-status | 缓存与 MySQL 状态 |
| POST /api/ocr/position | 持仓截图 OCR |

## 小程序配置

1. 微信开发者工具 → 详情 → 本地设置 → **不校验合法域名**
2. 修改 `utils/config.js` 中 `API_BASE`
3. 真机调试时改为电脑局域网 IP，如 `http://192.168.1.100:8000`

## 订阅消息

在微信公众平台申请订阅消息模板，填入 `utils/config.js` 的 `SUBSCRIBE_TEMPLATES`
