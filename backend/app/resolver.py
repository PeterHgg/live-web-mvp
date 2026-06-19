from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any
from urllib.parse import urlparse

from streamget import BilibiliLiveStream, DouyuLiveStream, HuyaLiveStream
from streamget.data import wrap_stream


class CustomBilibiliLiveStream(BilibiliLiveStream):
    async def fetch_stream_url(self, json_data: dict, video_quality: str | int | None = None):
        platform_str = "哔哩哔哩"
        anchor_name = json_data.get('anchor_name')
        room_url = json_data.get('room_url')

        if not json_data["live_status"]:
            return wrap_stream(
                {"platform": platform_str, "anchor_name": anchor_name, "is_live": False, "live_url": room_url}
            )

        video_quality_options = {
            "OD": '10000',
            "BD": '400',
            "UHD": '250',
            "HD": '150',
            "SD": '80',
            "LD": '80'
        }

        if not video_quality:
            video_quality = "OD"
        else:
            if str(video_quality).isdigit():
                video_quality = list(video_quality_options.keys())[int(video_quality)]
            else:
                video_quality = video_quality.upper()

        select_quality = video_quality_options.get(video_quality, '10000')
        play_url = await self.get_bilibili_stream_data(
            room_url, qn=select_quality, platform='h5')
        data = {
            'platform': platform_str,
            'anchor_name': json_data['anchor_name'],
            'is_live': True,
            'title': json_data['title'],
            'quality': video_quality,
            'record_url': play_url,
            'live_url': room_url
        }
        return wrap_stream(data)


QUALITY_LABELS = {
    "OD": "原画",
    "BD": "蓝光",
    "UHD": "超清",
    "HD": "高清",
    "SD": "标清",
    "LD": "流畅",
}


PLATFORMS: dict[str, dict[str, Any]] = {
    "douyu": {
        "name": "斗鱼",
        "class": DouyuLiveStream,
        "hosts": ["douyu.com", "www.douyu.com", "m.douyu.com"],
        "room_url": lambda value: f"https://www.douyu.com/{value}",
    },
    "huya": {
        "name": "虎牙",
        "class": HuyaLiveStream,
        "hosts": ["huya.com", "www.huya.com", "m.huya.com"],
        "room_url": lambda value: f"https://www.huya.com/{value}",
    },
    "bilibili": {
        "name": "哔哩哔哩",
        "class": CustomBilibiliLiveStream,
        "hosts": ["live.bilibili.com"],
        "room_url": lambda value: f"https://live.bilibili.com/{value}",
    },
}


ALIASES = {
    "douyu": "douyu",
    "斗鱼": "douyu",
    "huya": "huya",
    "虎牙": "huya",
    "bili": "bilibili",
    "bilibili": "bilibili",
    "哔哩": "bilibili",
    "哔哩哔哩": "bilibili",
    "b站": "bilibili",
}


class ResolveError(RuntimeError):
    pass


def supported_platforms() -> list[dict[str, str]]:
    return [
        {"key": key, "name": value["name"]}
        for key, value in PLATFORMS.items()
    ]


def normalize_platform(platform: str | None, target: str) -> str:
    if platform:
        key = ALIASES.get(platform.strip().lower(), platform.strip().lower())
        if key in PLATFORMS:
            return key
        raise ResolveError(f"暂不支持平台：{platform}")

    parsed = urlparse(target if "://" in target else "https://" + target)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host_without_www = host[4:]
    else:
        host_without_www = host

    for key, info in PLATFORMS.items():
        for candidate in info["hosts"]:
            if host == candidate or host_without_www == candidate or host.endswith("." + candidate):
                return key
    raise ResolveError("无法从地址识别平台，请手动选择平台")


def normalize_url(platform: str, value: str) -> str:
    target = value.strip()
    if not target:
        raise ResolveError("请输入直播间地址或房间号")
    if target.startswith("http://") or target.startswith("https://"):
        return target
    return PLATFORMS[platform]["room_url"](target)


def stream_data_to_dict(stream_data: Any) -> dict[str, Any]:
    if is_dataclass(stream_data):
        return asdict(stream_data)
    if hasattr(stream_data, "__dict__"):
        return dict(stream_data.__dict__)
    if isinstance(stream_data, dict):
        return dict(stream_data)
    raise ResolveError(f"无法识别解析结果：{type(stream_data).__name__}")


def build_streams(data: dict[str, Any]) -> list[dict[str, Any]]:
    quality = data.get("quality") or "OD"
    quality_label = QUALITY_LABELS.get(str(quality).upper(), str(quality))
    streams: list[dict[str, Any]] = []
    if data.get("m3u8_url"):
        streams.append({
            "type": "hls",
            "quality": quality,
            "quality_label": quality_label,
            "url": data["m3u8_url"],
        })
    if data.get("flv_url"):
        streams.append({
            "type": "flv",
            "quality": quality,
            "quality_label": quality_label,
            "url": data["flv_url"],
        })
    if data.get("record_url") and not any(item["url"] == data["record_url"] for item in streams):
        stream_type = "hls" if ".m3u8" in data["record_url"].lower() else "flv"
        streams.append({
            "type": stream_type,
            "quality": quality,
            "quality_label": quality_label,
            "url": data["record_url"],
        })
    return streams


async def resolve_live_stream(
    target: str,
    platform: str | None = None,
    quality: str = "OD",
    cookies: str | None = None,
) -> dict[str, Any]:
    platform_key = normalize_platform(platform, target)
    live_url = normalize_url(platform_key, target)
    info = PLATFORMS[platform_key]
    cls = info["class"]

    fetcher = cls(cookies=cookies)
    raw_data = await fetcher.fetch_web_stream_data(live_url)
    stream_data = await fetcher.fetch_stream_url(raw_data, quality)
    data = stream_data_to_dict(stream_data)

    streams = build_streams(data)
    return {
        "platform": platform_key,
        "platform_name": data.get("platform") or info["name"],
        "anchor_name": data.get("anchor_name"),
        "title": data.get("title"),
        "is_live": bool(data.get("is_live")),
        "quality": data.get("quality") or quality,
        "live_url": data.get("live_url") or live_url,
        "streams": streams,
        "raw": data,
    }
