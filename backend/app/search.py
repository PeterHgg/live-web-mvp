from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, asdict
from typing import Any

import httpx

from .resolver import ALIASES, PLATFORMS, ResolveError


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)


@dataclass
class SearchRoom:
    platform: str
    platform_name: str
    room_id: str
    title: str
    anchor_name: str
    live_url: str
    is_live: bool = True
    cover: str | None = None
    avatar: str | None = None
    watching: str | None = None
    area: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def abs_url(value: Any) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    return url


def clean_html(value: Any) -> str:
    return str(value or "").replace("<em class=\"keyword\">", "").replace("</em>", "").replace("<em>", "")


def random_hex(length: int = 32) -> str:
    return "".join(random.choice("0123456789abcdef") for _ in range(length))


def normalize_platform(platform: str | None) -> str | None:
    if not platform or platform == "all":
        return None
    key = ALIASES.get(platform.strip().lower(), platform.strip().lower())
    if key not in PLATFORMS:
        raise ResolveError(f"暂不支持平台：{platform}")
    return key


async def search_douyu(client: httpx.AsyncClient, keyword: str, page: int, page_size: int) -> list[SearchRoom]:
    did = random_hex()
    response = await client.get(
        "https://www.douyu.com/japi/search/api/searchShow",
        params={"kw": keyword, "page": page, "pageSize": page_size},
        headers={
            "user-agent": USER_AGENT,
            "referer": "https://www.douyu.com/search/",
            "cookie": f"dy_did={did};acf_did={did}",
        },
    )
    data = response.json()
    if data.get("error") != 0:
        raise RuntimeError(data.get("msg") or "斗鱼搜索失败")

    rooms: list[SearchRoom] = []
    for item in data.get("data", {}).get("relateShow", []) or []:
        room_id = str(item.get("rid") or "")
        if not room_id:
            continue
        is_live = str(item.get("isLive")) == "1" and str(item.get("roomType", "0")) == "0"
        rooms.append(SearchRoom(
            platform="douyu",
            platform_name="斗鱼",
            room_id=room_id,
            title=str(item.get("roomName") or ""),
            anchor_name=str(item.get("nickName") or ""),
            cover=abs_url(item.get("roomSrc")),
            avatar=abs_url(item.get("avatar")),
            area=str(item.get("cateName") or ""),
            watching=str(item.get("hot") or ""),
            is_live=is_live,
            live_url=f"https://www.douyu.com/{room_id}",
        ))
    return rooms


async def search_huya(client: httpx.AsyncClient, keyword: str, page: int, page_size: int) -> list[SearchRoom]:
    response = await client.get(
        "https://search.cdn.huya.com/",
        params={
            "m": "Search",
            "do": "getSearchContent",
            "q": keyword,
            "uid": 0,
            "v": 4,
            "typ": -5,
            "livestate": 0,
            "rows": page_size,
            "start": (page - 1) * page_size,
        },
        headers={"user-agent": USER_AGENT, "referer": "https://www.huya.com/"},
    )
    data = response.json()
    live_docs = data.get("response", {}).get("3", {}).get("docs", []) or []
    anchor_docs = data.get("response", {}).get("1", {}).get("docs", []) or []

    def find_room_id(uid: Any, yyid: Any) -> str | None:
        for item in anchor_docs:
            if item.get("uid") == uid and item.get("yyid") == yyid:
                return str(item.get("room_id") or "")
        return None

    rooms: list[SearchRoom] = []
    for item in live_docs:
        room_id = find_room_id(item.get("uid"), item.get("yyid")) or str(item.get("room_id") or "")
        if not room_id:
            continue
        cover = str(item.get("game_screenshot") or "")
        if cover and "?" not in cover:
            cover += "?x-oss-process=style/w338_h190&"
        title = str(item.get("game_introduction") or item.get("game_roomName") or "")
        rooms.append(SearchRoom(
            platform="huya",
            platform_name="虎牙",
            room_id=room_id,
            title=title,
            anchor_name=str(item.get("game_nick") or ""),
            cover=abs_url(cover),
            avatar=abs_url(item.get("game_imgUrl")),
            area=str(item.get("gameName") or ""),
            watching=str(item.get("game_total_count") or ""),
            is_live=True,
            live_url=f"https://www.huya.com/{room_id}",
        ))
    return rooms


async def search_bilibili(client: httpx.AsyncClient, keyword: str, page: int, page_size: int) -> list[SearchRoom]:
    try:
        await client.get("https://www.bilibili.com/", headers={"user-agent": USER_AGENT})
    except Exception:
        pass

    response = await client.get(
        "https://api.bilibili.com/x/web-interface/search/type",
        params={
            "context": "",
            "search_type": "live",
            "cover_type": "user_cover",
            "order": "",
            "keyword": keyword,
            "category_id": "",
            "__refresh__": "",
            "_extra": "",
            "highlight": 0,
            "single_column": 0,
            "page": page,
            "page_size": page_size,
        },
        headers={
            "user-agent": USER_AGENT,
            "referer": "https://search.bilibili.com/",
            "origin": "https://search.bilibili.com",
        },
    )
    data = response.json()
    result = data.get("data", {}).get("result", {})
    live_rooms = result.get("live_room", []) if isinstance(result, dict) else []

    rooms: list[SearchRoom] = []
    for item in live_rooms or []:
        room_id = str(item.get("roomid") or "")
        if not room_id:
            continue
        is_live = int(item.get("live_status") or 0) == 1
        rooms.append(SearchRoom(
            platform="bilibili",
            platform_name="哔哩哔哩",
            room_id=room_id,
            title=clean_html(item.get("title")),
            anchor_name=clean_html(item.get("uname")),
            cover=abs_url(item.get("cover")),
            avatar=abs_url(item.get("uface")),
            area=str(item.get("cate_name") or ""),
            watching=str(item.get("online") or ""),
            is_live=is_live,
            live_url=f"https://live.bilibili.com/{room_id}",
        ))
    return rooms


SEARCHERS = {
    "douyu": search_douyu,
    "huya": search_huya,
    "bilibili": search_bilibili,
}


async def search_rooms(keyword: str, platform: str | None = None, page: int = 1, page_size: int = 20) -> dict[str, Any]:
    keyword = keyword.strip()
    if not keyword:
        raise ResolveError("请输入搜索关键词")

    platform_key = normalize_platform(platform)
    platform_keys = [platform_key] if platform_key else list(SEARCHERS.keys())
    page = max(page, 1)
    page_size = max(1, min(page_size, 30))

    results: list[SearchRoom] = []
    errors: dict[str, str] = {}
    timeout = httpx.Timeout(12.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        tasks = [SEARCHERS[key](client, keyword, page, page_size) for key in platform_keys]
        settled = await asyncio.gather(*tasks, return_exceptions=True)

    for key, value in zip(platform_keys, settled):
        if isinstance(value, Exception):
            errors[key] = str(value)
        else:
            results.extend(value)

    results.sort(key=lambda item: (not item.is_live, item.platform))
    return {
        "keyword": keyword,
        "platform": platform_key or "all",
        "results": [item.to_dict() for item in results],
        "errors": errors,
    }
