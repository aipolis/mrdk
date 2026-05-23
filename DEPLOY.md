# Cloudflare Pages 部署说明

## 仓库说明

网站代码在 **`web/`** 目录，并已单独关联 GitHub：

- 仓库：[github.com/aipolis/mrdk](https://github.com/aipolis/mrdk)
- 分支：`main`
- 仓库根目录即网站根（含 `index.html`），**不是**整个「明日当空」 monorepo

在 `web/` 目录内执行 git 命令：

```powershell
cd "c:\Users\Administrator\Desktop\量化交易\明日当空\web"
git status
git add .
git commit -m "说明你的修改"
git push origin main
```

---

## 一、Cloudflare Pages 连接 Git（推荐）

### 首次：从「手动上传」改为 Git 部署

若已有 `mrdk.pages.dev` 且是 Upload 创建的，建议 **新建一个 Git 项目**，或删除旧项目后重建（Custom domain 可再绑回来）。

### 步骤

1. 打开 [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create**
2. 选 **Pages** → **Connect to Git**
3. 授权 **GitHub**，选择仓库 **`aipolis/mrdk`**
4. **Build settings**（静态站，无需构建）：

| 配置项 | 填写 |
|--------|------|
| Production branch | `main` |
| Framework preset | **None** |
| Build command | （留空） |
| Build output directory | `/` |

> ⚠️ 若误填 `web`，部署会失败（本仓库根目录就是网站，没有上层 `web` 文件夹）。

5. 点 **Save and Deploy**，等待 1～2 分钟
6. 得到 `https://mrdk.pages.dev`（或 Cloudflare 分配的新子域）
7. 若之前有自定义域名：项目 → **Custom domains** → 重新绑定

### 之后每次更新

```powershell
cd web
git add .
git commit -m "更新说明"
git push origin main
```

Push 后 Cloudflare **自动重新部署**，一般 1～2 分钟生效。

---

## 二、本地预览

```powershell
cd web
.\preview.ps1
```

浏览器打开：http://127.0.0.1:8888

---

## 三、API 配置

`web/js/config.js`：

```javascript
export const API_BASE = 'https://mingri-api-260693-8-1435576840.sh.run.tcloudbase.com'
export const AUTO_REFRESH_MS = 2 * 60 * 1000  // 首页每 2 分钟自动刷新
```

---

## 四、部署后检查

- [ ] 首页情绪分、指标板块正常
- [ ] `/history.html` 上证涨跌带 `%`
- [ ] 首页约 2 分钟自动静默刷新
- [ ] 页脚免责声明可见

---

## 五、方式 A：手动上传（备用）

不想用 Git 时：Pages → **Upload assets**，将 `web/` **内部文件**打 zip（根目录含 `index.html`）上传。

---

## 目录结构

```
web/                    ← Git 仓库根（推送到 aipolis/mrdk）
  index.html
  history.html
  css/app.css
  js/
    config.js
    app.js
    history.js
    ...
  _headers
  preview.ps1
```
