# Live Web MVP

一个网页多平台直播观看 MVP：

- 后端：FastAPI + StreamGet，只负责搜索直播间和解析真实直播流地址。
- 前端：Vue 3 + Vite + hls.js + mpegts.js，负责网页播放。

> 只用于你有权访问的直播内容。不同平台接口、CORS、防盗链和浏览器 codec 支持会影响可播放性。

## 已接入平台

当前只保留四个平台：

- 斗鱼
- 虎牙
- 哔哩哔哩
- 抖音

抖音、斗鱼等平台接口可能需要 Cookie、Node.js 或特定网络环境。第一版先不做账号/Cookie 管理 UI。

## Docker Compose 部署

生产方式启动：

```bash
git clone <your-repo-url>
cd live-web-mvp
docker compose up -d --build
```

访问：

```text
http://服务器IP:8080
```

前端容器内置 Nginx，会把 `/api/*` 反代到后端容器。后端不暴露到公网，只在 Compose 网络内服务。

如果需要设置抖音搜索 Cookie，可以在 `docker-compose.yml` 的 backend 服务里添加：

```yaml
environment:
  DOUYIN_COOKIE: "你的 Cookie"
```

## 本地开发

```bash
docker compose -f docker-compose.dev.yml up
```

访问：

```text
http://localhost:5173
```

也可以手动启动。

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## API

### 平台列表

```http
GET /api/platforms
```

### 搜索直播间

```http
GET /api/search?keyword=lol&platform=all&page=1&page_size=20
```

`platform` 可选：

```text
all / douyu / huya / bilibili / douyin
```

返回示例：

```json
{
  "keyword": "lol",
  "platform": "all",
  "results": [
    {
      "platform": "huya",
      "platform_name": "虎牙",
      "room_id": "138297",
      "title": "直播标题",
      "anchor_name": "主播名",
      "live_url": "https://www.huya.com/138297",
      "is_live": true,
      "cover": "https://...",
      "avatar": "https://...",
      "watching": "572792",
      "area": "英雄联盟"
    }
  ],
  "errors": {}
}
```

前端搜索结果里的“播放”按钮会自动把 `live_url` 填入解析接口并播放。

### 解析直播间

```http
POST /api/resolve
Content-Type: application/json

{
  "target": "https://www.huya.com/52333",
  "platform": null,
  "quality": "OD"
}
```

返回示例：

```json
{
  "platform": "huya",
  "platform_name": "虎牙直播",
  "anchor_name": "...",
  "title": "...",
  "is_live": true,
  "streams": [
    {
      "type": "hls",
      "quality": "OD",
      "quality_label": "原画",
      "url": "https://...m3u8"
    },
    {
      "type": "flv",
      "quality": "OD",
      "quality_label": "原画",
      "url": "https://...flv"
    }
  ]
}
```

## 使用建议

1. 当前项目已移除直播流代理，后端只做搜索和解析，不转发视频流。
2. 播放时浏览器会直连平台返回的 HLS/FLV 地址，因此直播源必须允许浏览器直连且不能被 CORS/防盗链拦截。
3. 如果 FLV 播不了，优先尝试 HLS/M3U8 流。
4. iOS/Safari 对 FLV/MSE 支持有限，优先用 HLS。
5. 抖音、斗鱼等平台接口可能会风控或要求 Node.js/Cookie，后续需要做 Cookie 配置和失败重试。

## 后续可做

- 增加 Cookie 配置页面。
- 增加直播源缓存和过期刷新。
- 增加平台分区和热门推荐。
- 增加播放失败时的直连诊断提示。
- 增加收藏、历史记录。
- 增加弹幕 WebSocket 转发。
