# -*- coding: utf-8 -*-
import os
from datetime import datetime, timezone, timedelta

BJT = timezone(timedelta(hours=8))

def bj_now() -> datetime:
    """返回北京时间（Asia/Shanghai, UTC+8）的当前 datetime。
    所有涉及时段判断、交易日期计算的地方都应使用此函数替代 datetime.now()。
    """
    return datetime.now(BJT)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))

# 首页预计算缓存（/api/sentiment/today 秒回）
HOME_CACHE_FILE = os.getenv("HOME_CACHE_FILE", "/tmp/mingri_home_cache.json")
HOME_CACHE_MAX_STALE_SEC = int(os.getenv("HOME_CACHE_MAX_STALE_SEC", str(86400 * 2)))

# 云托管 MySQL（控制台 MySQL 页 → 内网地址 + 账号）
MYSQL_ADDRESS = os.getenv("MYSQL_ADDRESS", "")
MYSQL_USERNAME = os.getenv("MYSQL_USERNAME", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "mingri")

# 内置定时任务（默认开启；设 INTERNAL_CRON=false 可关闭）
INTERNAL_CRON = os.getenv("INTERNAL_CRON", "true").lower() not in ("0", "false", "no")
SYNC_HISTORY_DAYS = int(os.getenv("SYNC_HISTORY_DAYS", "60"))

# 小程序凭证（发送订阅消息、code 换 openid）— 在云托管环境变量中配置
WX_APPID = os.getenv("WX_APPID", "wxf9cd48540ad006cd")
WX_SECRET = os.getenv("WX_SECRET", "")

# 定时推送鉴权（云托管定时触发 / 手动调用时携带）
# 生产环境必须配置此值以保护管理接口安全
CRON_SECRET = os.getenv("CRON_SECRET", "")

# 生产环境标识（prod/production 时强制要求 CRON_SECRET）
# 云托管部署时应设置 APP_ENV=prod 或 ENV=prod
APP_ENV = os.getenv("APP_ENV", os.getenv("ENV", "")).lower()

# 微信订阅消息模板（公众平台 → 订阅消息 → 模板 ID）
TMPL_MARKET_SENTIMENT = os.getenv(
    "TMPL_SENTIMENT",
    "2PJYcWlocC15xg2W7YDLzT5B1Qff5Hc24O-mLEsw4tU",
)

SUBSCRIBE_TEMPLATES = {
    "sentiment_daily": TMPL_MARKET_SENTIMENT,
    "empty_alert": os.getenv("TMPL_EMPTY", TMPL_MARKET_SENTIMENT),
}

# 模板字段：thing7 策略类型 | character_string2 关键数据 | time3 时间 | thing12 温馨提示
SUBSCRIBE_FIELD_KEYS = {
    "strategy": "thing7",
    "key_data": "character_string2",
    "time": "time3",
    "tips": "thing12",
}
