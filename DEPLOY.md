# Cloudflare Pages 部署说明

## 一、本地预览

在项目根目录执行：

```powershell
cd web
python -m http.server 8080
```

浏览器打开：http://127.0.0.1:8080

> 必须用 HTTP 服务打开（ES Module 不支持 file:// 协议）。

## 二、Cloudflare Pages 部署

### 方式 A：直接上传（最快）

1. 登录 [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create**
2. 选择 **Pages** → **Upload assets**
3. 将整个 `web/` 文件夹内容打包为 zip（zip 根目录需包含 `index.html`）
4. 上传后获得地址：`https://xxx.pages.dev`

### 方式 B：连接 Git（推荐长期）

1. 将项目 push 到 GitHub / GitLab
2. Cloudflare Pages → **Connect to Git**
3. 构建设置：

| 项 | 值 |
|----|-----|
| Production branch | `main` 或 `master` |
| Build command | （留空） |
| Build output directory | `web` |

4. 保存并部署

## 三、API 配置

编辑 `web/js/config.js` 中的 `API_BASE`：

```javascript
export const API_BASE = 'https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com'
```

后端 CORS 已允许跨域（`allow_origins=["*"]`），无需额外配置。

## 四、自定义域名（可选）

Cloudflare Pages → 项目 → **Custom domains** → 添加你的域名。

## 五、部署后检查

1. 首页能显示情绪分仪表盘
2. 四大指标板块有数据
3. `/history.html` 历史列表正常
4. 页脚免责声明可见

若显示「缓存预热中」，等待 5 秒自动重试，或调用：

```
POST https://你的API/api/cache/warm-home
Header: x-cron-secret: 你的密钥
```

## 六、目录结构

```
web/
  index.html          首页
  history.html        历史页
  css/app.css         样式
  js/
    config.js         API 地址
    app.js            首页逻辑
    history.js        历史页
    gaugeDraw.js      仪表盘 Canvas
    theme.js          等级/语录
    indicators.js     指标板块
  _headers            Cloudflare 安全头
```
