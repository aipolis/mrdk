# 《明日当空》Web 版工程方案（Next.js + Tailwind + ECharts）

## 一、推荐技术栈

适合你现在的产品定位：

| 模块 | 技术 |
|---|---|
| 前端框架 | Next.js 15（App Router） |
| UI | TailwindCSS |
| 图表 | Apache ECharts |
| 状态管理 | Zustand |
| 请求 | Axios |
| 动效 | Framer Motion |
| 图标 | Lucide React |
| 主题 | next-themes |
| 部署 | Vercel / Cloudflare Pages |

---

# 二、项目目录结构

```bash
mingri-dangkong-web/
├── app/
│   ├── layout.tsx
│   ├── page.tsx
│   ├── history/
│   │   └── page.tsx
│   ├── detail/
│   │   └── [date]/page.tsx
│   ├── profile/
│   │   └── page.tsx
│   └── globals.css
│
├── components/
│   ├── layout/
│   │   ├── Sidebar.tsx
│   │   ├── Header.tsx
│   │   └── DashboardLayout.tsx
│   │
│   ├── dashboard/
│   │   ├── GaugeCard.tsx
│   │   ├── TrendChart.tsx
│   │   ├── SentimentGrid.tsx
│   │   ├── PeripheralCard.tsx
│   │   ├── AuctionCard.tsx
│   │   ├── IntradayCard.tsx
│   │   ├── DragonSignal.tsx
│   │   └── PositionBar.tsx
│   │
│   ├── history/
│   │   └── HistoryTable.tsx
│   │
│   ├── detail/
│   │   └── DetailMetrics.tsx
│   │
│   └── common/
│       ├── Card.tsx
│       ├── Loading.tsx
│       ├── Empty.tsx
│       └── ThemeToggle.tsx
│
├── lib/
│   ├── api.ts
│   ├── score.ts
│   ├── theme.ts
│   └── format.ts
│
├── store/
│   └── sentimentStore.ts
│
├── types/
│   └── sentiment.ts
│
├── public/
│   ├── logo.png
│   └── dragon.png
│
├── package.json
├── tailwind.config.ts
├── tsconfig.json
└── next.config.js
```

---

# 三、首页页面结构

路径：

```bash
app/page.tsx
```

页面结构：

```tsx
<DashboardLayout>
  <Header />

  <div className="grid grid-cols-12 gap-4">
    <GaugeCard />
    <TrendChart />

    <PeripheralCard />
    <MarketIndexCard />

    <SentimentGrid />
    <AuctionCard />
    <IntradayCard />
    <DragonSignal />

    <HistoryTable />
  </div>
</DashboardLayout>
```

---

# 四、推荐首页布局

## PC 端

```text
┌────────Sidebar────────┐┌──────────── 主内容区 ────────────┐
│ Logo                  ││ Header                         │
│ 情绪首页               ││                                │
│ 历史数据               ││ 仪表盘      趋势图             │
│ 指标详情               ││                                │
│ 仓位建议               ││ 外围情绪    指数行情           │
│ 我的订阅               ││                                │
│ 设置                   ││ 昨日情绪    竞价情绪           │
│                        ││                                │
│                        ││ 盘中情绪    连板结构           │
│                        ││                                │
│                        ││ 历史表格                     │
└───────────────────────┘└────────────────────────────────┘
```

---

# 五、核心组件设计

# 5.1 GaugeCard.tsx

作用：

- 展示 displayScore
- 仪表盘
- 龙空信号
- 仓位建议

推荐使用：

```bash
echarts-for-react
```

---

## 仪表盘结构

```text
        72
      偏乐观

龙空信号：强
建议仓位：70%
```

---

## 推荐颜色映射

```ts
const scoreColor = {
  frenzy: '#FF7A00',
  climax: '#FF4D4F',
  optimistic: '#FF6B57',
  neutral: '#F5C451',
  caution: '#5B7C99',
  cold: '#4DA3FF'
}
```

---

# 5.2 TrendChart.tsx

功能：

- 近10日情绪趋势
- baseline/live/display 对比

推荐：

```bash
Apache ECharts
```

---

## 图表建议

### 折线

| 线 | 颜色 |
|---|---|
| 展示分 | 红色 |
| 基准分 | 灰色 |
| 盘中分 | 蓝色 |

---

# 5.3 SentimentGrid.tsx

功能：

- 昨日情绪九宫格

布局：

```text
连板高度   涨停家数   封板率
晋级率     跌停家数   炸板率
一字板     市场量能   上涨占比
```

---

## 数据结构

```ts
{
  key: 'limitUp',
  label: '涨停家数',
  value: 82,
  compare: '+15',
  score: 90
}
```

---

# 5.4 DragonSignal.tsx

功能：

- 显示 emptyWarning

强风险：

```text
⚠ 龙空信号触发
建议降低节奏
```

正常：

```text
市场结构正常
```

---

# 六、Sidebar 设计

组件：

```bash
components/layout/Sidebar.tsx
```

菜单：

```text
情绪首页
历史数据
指标详情
仓位建议
持仓复盘
复盘日历
我的订阅
系统设置
```

---

## 风格

- 深蓝背景
- 左侧高亮红色 active bar
- hover 微动效
- 固定宽度 240px

---

# 七、Header 设计

包含：

```text
更新时间
主题切换
分享按钮
通知按钮
```

---

## Header 示例

```tsx
<div className="flex items-center justify-between">
  <div>
    更新时间：2026-05-23 11:28
  </div>

  <div className="flex gap-3">
    <ThemeToggle />
    <ShareButton />
  </div>
</div>
```

---

# 八、深色主题建议（重点）

建议默认深色主题。

## 背景层级

| 层级 | 颜色 |
|---|---|
| 页面背景 | #0B1020 |
| 一级卡片 | #111827 |
| 二级卡片 | #1A2235 |
| hover | #222C42 |

---

## 文字颜色

| 类型 | 颜色 |
|---|---|
| 一级文字 | #FFFFFF |
| 二级文字 | #94A3B8 |
| 弱化文字 | #64748B |

---

# 九、推荐卡片规范

统一：

```css
rounded-2xl
border border-slate-800
bg-slate-900
shadow-lg
```

---

# 十、响应式设计

## PC

12 列 grid。

## 平板

6 列。

## 手机

单列。

---

## Tailwind 示例

```tsx
<div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
```

---

# 十一、API 接入

# 11.1 api.ts

```ts
import axios from 'axios'

export const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API
})
```

---

# 11.2 获取首页数据

```ts
export async function getTodaySentiment() {
  const res = await api.get('/api/sentiment/today')
  return res.data
}
```

---

# 十二、状态管理

推荐：

```bash
zustand
```

---

# store/sentimentStore.ts

```ts
import { create } from 'zustand'

interface State {
  data: any
  setData: (v:any)=>void
}

export const useSentimentStore = create<State>((set)=>(
  {
    data:null,
    setData:(v)=>set({data:v})
  }
))
```

---

# 十三、推荐动画

## Framer Motion

用于：

- 卡片渐入
- 仪表盘数字滚动
- 趋势图加载
- hover 动效

---

## 示例

```tsx
<motion.div
  initial={{ opacity: 0, y: 10 }}
  animate={{ opacity: 1, y: 0 }}
>
```

---

# 十四、推荐开发顺序

## 第一步

先做静态页面：

- Sidebar
- Header
- 仪表盘
- 趋势图

---

## 第二步

接真实 API：

```bash
/api/sentiment/today
```

---

## 第三步

完成：

- 历史页
- 详情页
- 分享页

---

## 第四步

做：

- SSE 实时更新
- 自动刷新
- 分享截图
- SEO

---

# 十五、推荐部署方案

# 前端

推荐：

```text
Vercel
```

优势：

- 免费
- 自动 HTTPS
- 自动 CI/CD
- Next.js 原生支持

---

# 后端

你现有 FastAPI 可继续使用：

```text
Railway
Render
腾讯云轻量
阿里云 ECS
```

---

# 十六、推荐首页最终效果

风格定位：

> Bloomberg Terminal × TradingView × 东方极简风

避免：

- 过度发光
- 赌博感
- 币圈 UI
- 荐股软件感

强化：

- 风险识别
- 冷静判断
- 专业感
- 情绪周期

---

# 十七、下一步我可以继续帮你生成

我可以继续直接帮你写：

## 1. Next.js 完整初始化代码

包括：

- package.json
- tailwind.config
- layout.tsx
- Sidebar
- Header
- 首页

---

## 2. 仪表盘组件

真正可运行的：

```tsx
GaugeCard.tsx
```

---

## 3. ECharts 情绪趋势图

直接运行。

---

## 4. Tailwind 深色主题

完整 CSS Token。

---

## 5. 历史页表格

支持排序、分页、筛选。

---

## 6. 完整 Dashboard 首页

直接 npm run dev 即可运行。

---

## 7. Docker 部署

包括：

```bash
docker-compose.yml
```

---

## 8. Vercel 一键部署方案

包括环境变量与 API 配置。

