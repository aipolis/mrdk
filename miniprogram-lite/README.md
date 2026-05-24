# 明日当空 Lite · 开发说明

独立精简版小程序，与完整版共用同一后端 API。

## 打开方式

1. 微信开发者工具 → 导入项目
2. 目录选择本文件夹 `miniprogram-lite/`
3. AppID：可与完整版相同，或新建独立小程序 AppID
4. 详情 → 本地设置 → 勾选「不校验合法域名」（开发者工具直连 API 时需要）

## 功能

| 页面 | 说明 |
|------|------|
| 今日 | 龙/中/空 → 天气文案 + 与君共勉 + 分享图 |
| 历史 | 近 30 日日期 + 天气结论 |
| 我的 | 可选登录、每日天气提醒、关于/说明 |

## 后端

配置见 `utils/config.js`（`API_BASE`、`CLOUD_ENV`、`SUBSCRIBE_TEMPLATES`）。

## 图标

如需重新生成 tab 图标：`python scripts/gen_icons.py`
