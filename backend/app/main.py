from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .danmaku import DanmakuError, run_danmaku
from .resolver import ResolveError, resolve_live_stream, supported_platforms
from .search import search_rooms


app = FastAPI(title="Live Web MVP API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ResolveRequest(BaseModel):
    target: str = Field(..., description="直播间 URL 或房间号")
    platform: str | None = Field(None, description="平台 key；为空时尝试从 URL 自动识别")
    quality: str = Field("OD", description="OD/UHD/HD/SD/LD")
    cookies: str | None = Field(None, description="可选 Cookie；仅本地测试时使用")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Live Web MVP API",
        "frontend": "http://localhost:5173",
        "health": "/api/health",
        "docs": "/docs",
    }


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/platforms")
async def platforms() -> list[dict[str, str]]:
    return supported_platforms()


@app.post("/api/resolve")
async def resolve(req: ResolveRequest) -> dict:
    try:
        return await resolve_live_stream(
            target=req.target,
            platform=req.platform,
            quality=req.quality,
            cookies=req.cookies,
        )
    except ResolveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"解析失败：{exc}") from exc


@app.get("/api/search")
async def search(
    keyword: Annotated[str, Query(min_length=1, description="搜索关键词")],
    platform: Annotated[str | None, Query(description="douyu/huya/all")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=30)] = 20,
) -> dict:
    try:
        return await search_rooms(keyword=keyword, platform=platform, page=page, page_size=page_size)
    except ResolveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"搜索失败：{exc}") from exc


@app.websocket("/api/danmaku")
async def danmaku(websocket: WebSocket) -> None:
    await websocket.accept()
    target = websocket.query_params.get("target", "")
    platform = websocket.query_params.get("platform")
    try:
        await run_danmaku(websocket, target=target, platform=platform)
    except WebSocketDisconnect:
        return
    except (ResolveError, DanmakuError) as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": f"弹幕连接失败：{exc}"})
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
