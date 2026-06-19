# Live Web MVP

一个网页多平台直播观看 MVP：

- 后端：FastAPI + StreamGet，只负责搜索直播间和解析真实直播流地址。
- 前端：Vue 3 + Vite + hls.js + mpegts.js，负责网页播放。

> 只用于你有权访问的直播内容。不同平台接口、CORS、防盗链和浏览器 codec 支持会影响可播放性。

## 已接入平台

当前保留的平台：

- 斗鱼
- 虎牙
- 哔哩哔哩

## NAS 部署

推荐在 NAS 里直接使用预构建镜像的 Compose 文件：

[docker-compose.nas.yml](docker-compose.nas.yml)

内容如下：

```yaml
services:
  backend:
    image: ghcr.io/peterhgg/live-web-mvp-backend:latest
    container_name: live-web-mvp-backend
    restart: unless-stopped
    expose:
      - "8000"

  frontend:
    image: ghcr.io/peterhgg/live-web-mvp-frontend:latest
    container_name: live-web-mvp-frontend
    restart: unless-stopped
    ports:
      - "8080:80"
    depends_on:
      - backend
```

启动：

```bash
docker compose -f docker-compose.nas.yml up -d
```

访问：

```text
http://NAS_IP:8080
```

如果 NAS 的 `8080` 端口被占用，把：

```yaml
ports:
  - "8080:80"
```

改成例如：

```yaml
ports:
  - "8090:80"
```

然后访问：

```text
http://NAS_IP:8090
```

## 镜像自动构建

GitHub Actions 会在推送到 `main` 或推送 `v*` tag 时自动构建并发布镜像到 GHCR：

```text
ghcr.io/peterhgg/live-web-mvp-backend:latest
ghcr.io/peterhgg/live-web-mvp-frontend:latest
```

同时支持：

```text
linux/amd64
linux/arm64
```

适合常见 x86 NAS 和 ARM NAS。

## 从源码部署

如果不想用预构建镜像，也可以在服务器/NAS 上源码构建：

```bash
git clone https://github.com/PeterHgg/live-web-mvp.git
cd live-web-mvp
docker compose up -d --build
```

访问：

```text
http://服务器IP:8080
```

前端容器内置 Nginx，会把 `/api/*` 反代到后端容器。后端不暴露到公网，只在 Compose 网络内服务。

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
all / douyu / huya / bilibili
```

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

## 使用建议

1. 当前项目已移除直播流代理，后端只做搜索和解析，不转发视频流。
2. 播放时浏览器会直连平台返回的 HLS/FLV 地址，因此直播源必须允许浏览器直连且不能被 CORS/防盗链拦截。
3. 如果 FLV 播不了，优先尝试 HLS/M3U8 流。
4. iOS/Safari 对 FLV/MSE 支持有限，优先用 HLS。
5. 斗鱼、虎牙平台接口可能会风控，后续需要做失败重试和提示优化。

## 后续可做

- 增加 Cookie 配置页面。
- 增加直播源缓存和过期刷新。
- 增加平台分区和热门推荐。
- 增加播放失败时的直连诊断提示。
- 增加收藏、历史记录。
- 增加弹幕 WebSocket 转发。
