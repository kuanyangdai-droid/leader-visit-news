# Leader Visit Watch

一个静态网页项目，用来聚合公开新闻中与国家领导人、政府首脑、外长、高级官员外事访问相关的最新消息。后端脚本每日运行一次，抓取公开 RSS 或新闻列表页，生成 `public/data/visits.json`；前端只读取本地 JSON，不暴露 API key，也不在浏览器里直接请求外部新闻源。

## 技术方案

- 采集层：Python，优先读取 RSS/Atom；必要时读取公开 HTML 新闻列表。
- 数据源配置：`scripts/sources.json`，新增或停用来源只改配置。
- 去重逻辑：`scripts/dedupe.py`，按 `leader_name + visit_date` 优先去重；日期缺失时用 `leader_name + destination + published_at 日期` 辅助判断。
- 数据存储：JSON 文件，路径为 `public/data/visits.json`。
- 前端：纯 HTML/CSS/JS，支持国家筛选、访问日期筛选、关键词搜索。
- 自动更新：GitHub Actions 每天 00:00 UTC 运行一次并提交 JSON。

## 目录结构

```text
leader-visit-news/
├── public/
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── data/
│       └── visits.json
├── scripts/
│   ├── update_visits.py
│   ├── dedupe.py
│   └── sources.json
├── .github/
│   └── workflows/
│       └── update-visits.yml
├── requirements.txt
└── README.md
```

## JSON 字段

每条记录统一为：

```json
{
  "id": "唯一ID",
  "leader_name": "领导人姓名",
  "leader_title": "职务",
  "country": "国家或地区",
  "visit_date": "YYYY-MM-DD",
  "event_type": "state_visit / official_visit / working_visit / conference_attendance / arrival / departure / meeting / other",
  "destination": "访问目的地",
  "summary": "新闻摘要",
  "source_name": "来源名称",
  "source_url": "原文链接",
  "published_at": "新闻发布时间",
  "language": "新闻语言",
  "possibly_special_aircraft": false,
  "created_at": "首次写入时间",
  "updated_at": "更新时间"
}
```

`possibly_special_aircraft` 只在公开文本出现专机、government aircraft、special flight、aircraft、抵达机场等明显线索时标记为 `true`。不会追踪实时飞行轨迹、航班号、机号或未公开行程。

## 本地运行

安装依赖：

```bash
python -m pip install -r requirements.txt
```

更新 JSON：

```bash
python scripts/update_visits.py
```

本地预览：

```bash
python -m http.server 8000 -d public
```

然后打开：

```text
http://localhost:8000
```

## 添加新闻源

编辑 `scripts/sources.json`，新增 RSS 来源：

```json
{
  "name": "Example Ministry",
  "type": "rss",
  "url": "https://example.gov/news.xml",
  "language": "en",
  "country_hint": "Example Country",
  "enabled": true
}
```

新增公开 HTML 列表页：

```json
{
  "name": "Example News List",
  "type": "html",
  "url": "https://example.gov/news/",
  "language": "en",
  "country_hint": "Example Country",
  "enabled": true,
  "link_selector": "a",
  "base_url": "https://example.gov"
}
```

优先使用 RSS、Atom、官方新闻列表页或站内搜索结果页。不要抓登录页、付费墙、私人信息或 robots.txt 不允许抓取的页面。

## GitHub Pages 部署

本仓库使用 GitHub Actions 部署 Pages，因为 GitHub Pages 的分支模式只支持 `/` 或 `/docs`，不能直接选择 `/public`。

1. 把仓库推到 GitHub。
2. 进入 Settings → Pages。
3. Source 选择 `GitHub Actions`。
4. 手动运行一次 `Deploy GitHub Pages` workflow，或等待下一次 push 触发。
5. Pages 会把 `public/` 目录作为站点根目录发布。

## 自动更新

`.github/workflows/update-visits.yml` 已配置：

- `workflow_dispatch`：可以手动运行。
- `schedule`：每天 00:00 UTC 自动运行。

workflow 会执行：

```bash
python scripts/update_visits.py
```

如果 `public/data/visits.json` 有变化，就自动提交回仓库。

## 合规边界

- 只处理公开新闻和官方通稿。
- 不抓取需要登录、付费墙、私人或敏感数据。
- 不追踪实时专机位置，不推断未公开行程。
- 抓取频率控制为每日一次。
