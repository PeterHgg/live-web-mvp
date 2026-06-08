from __future__ import annotations

import asyncio
import base64
import re
import struct
from contextlib import suppress
from urllib.parse import urlparse

import httpx
import websockets
from fastapi import WebSocket
from websockets.asyncio.client import ClientConnection

from .resolver import normalize_platform


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
HUYA_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/90.0.4430.91 Mobile Safari/537.36"
)
HUYA_HEARTBEAT = base64.b64decode("ABQdAAwsNgBM")


class DanmakuError(RuntimeError):
    pass


def extract_room_id(_platform: str, target: str) -> str:
    value = target.strip()
    if not value:
        raise DanmakuError("缺少直播间地址或房间号")
    if not value.startswith(("http://", "https://")):
        return value

    parsed = urlparse(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        raise DanmakuError("无法从地址中识别房间号")
    return path_parts[-1]


async def run_danmaku(websocket: WebSocket, target: str, platform: str | None = None) -> None:
    platform_key = normalize_platform(platform, target)
    room_id = extract_room_id(platform_key, target)

    if platform_key == "douyu":
        await douyu_danmaku(websocket, room_id)
    elif platform_key == "huya":
        await huya_danmaku(websocket, room_id)
    else:
        raise DanmakuError("当前弹幕支持斗鱼、虎牙")


async def keep_client_alive(websocket: WebSocket) -> None:
    while True:
        await websocket.receive_text()


async def wait_with_client(websocket: WebSocket, task: asyncio.Task[None]) -> None:
    client_task = asyncio.create_task(keep_client_alive(websocket))
    try:
        done, pending = await asyncio.wait(
            {task, client_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for item in done:
            item.result()
        for item in pending:
            item.cancel()
    finally:
        client_task.cancel()
        with suppress(asyncio.CancelledError):
            await client_task


async def send_chat(websocket: WebSocket, platform: str, user_name: str, message: str, color: str | None = None) -> None:
    if not message:
        return
    await websocket.send_json({
        "type": "chat",
        "platform": platform,
        "user_name": user_name or "匿名用户",
        "message": message,
        "color": color,
    })


async def send_online(websocket: WebSocket, platform: str, online: int) -> None:
    await websocket.send_json({
        "type": "online",
        "platform": platform,
        "online": online,
    })


async def send_status(websocket: WebSocket, platform: str, message: str) -> None:
    await websocket.send_json({
        "type": "status",
        "platform": platform,
        "message": message,
    })


async def douyu_danmaku(websocket: WebSocket, room_id: str) -> None:
    async with websockets.connect(
        "wss://danmuproxy.douyu.com:8506",
        additional_headers={"user-agent": USER_AGENT},
        ping_interval=None,
        proxy=None,
    ) as upstream:
        await send_status(websocket, "douyu", "斗鱼弹幕已连接")
        await upstream.send(douyu_packet(f"type@=loginreq/roomid@={room_id}/"))
        await upstream.send(douyu_packet(f"type@=joingroup/rid@={room_id}/gid@=-9999/"))

        heartbeat = asyncio.create_task(douyu_heartbeat(upstream))
        reader = asyncio.create_task(douyu_reader(websocket, upstream))
        try:
            await wait_with_client(websocket, reader)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat


async def douyu_heartbeat(upstream: ClientConnection) -> None:
    while True:
        await asyncio.sleep(45)
        await upstream.send(douyu_packet("type@=mrkl/"))


def douyu_packet(body: str) -> bytes:
    payload = body.encode("utf-8") + b"\x00"
    length = len(payload) + 8
    return struct.pack("<IIHBB", length, length, 689, 0, 0) + payload


async def douyu_reader(websocket: WebSocket, upstream: ClientConnection) -> None:
    async for data in upstream:
        if isinstance(data, str):
            data = data.encode("utf-8")
        for message in parse_douyu_packets(data):
            fields = parse_douyu_stt(message)
            if fields.get("type") == "chatmsg" and fields.get("txt"):
                await send_chat(
                    websocket,
                    "douyu",
                    fields.get("nn", ""),
                    fields.get("txt", ""),
                    douyu_color(fields.get("col")),
                )


def parse_douyu_packets(data: bytes) -> list[str]:
    messages: list[str] = []
    offset = 0
    while offset + 12 <= len(data):
        length = struct.unpack_from("<I", data, offset)[0]
        body_start = offset + 12
        body_end = offset + 4 + length - 1
        if body_end > len(data):
            break
        messages.append(data[body_start:body_end].decode("utf-8", errors="ignore"))
        offset += length + 4
    return messages


def parse_douyu_stt(message: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for item in message.split("/"):
        if not item or "@=" not in item:
            continue
        key, value = item.split("@=", 1)
        fields[key] = value.replace("@S", "/").replace("@A", "@")
    return fields


def douyu_color(value: str | None) -> str | None:
    colors = {
        "1": "#ff0000",
        "2": "#1e87f0",
        "3": "#7ac84b",
        "4": "#ff7f00",
        "5": "#9b39f4",
        "6": "#ff69b4",
    }
    return colors.get(str(value))


async def huya_danmaku(websocket: WebSocket, room_id: str) -> None:
    ayyuid, top_sid, sub_sid = await get_huya_danmaku_args(room_id)
    async with websockets.connect(
        "wss://cdnws.api.huya.com",
        additional_headers={"user-agent": USER_AGENT},
        ping_interval=None,
        proxy=None,
    ) as upstream:
        await send_status(websocket, "huya", "虎牙弹幕已连接")
        await upstream.send(huya_join_packet(ayyuid, top_sid, sub_sid))

        heartbeat = asyncio.create_task(huya_heartbeat(upstream))
        reader = asyncio.create_task(huya_reader(websocket, upstream))
        try:
            await wait_with_client(websocket, reader)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat


async def get_huya_danmaku_args(room_id: str) -> tuple[int, int, int]:
    async with httpx.AsyncClient(timeout=10, headers={"user-agent": HUYA_MOBILE_UA}) as client:
        response = await client.get(f"https://m.huya.com/{room_id}")
        response.raise_for_status()
        text = response.text

    yyid = regex_int(text, r'"lYyid":\s*([0-9]+)') or regex_int(text, r'"yyid":\s*([0-9]+)')
    top_sid = regex_int(text, r'"lChannelId":\s*([0-9]+)')
    sub_sid = regex_int(text, r'"lSubChannelId":\s*([0-9]+)')
    if not yyid or not top_sid:
        raise DanmakuError("虎牙弹幕参数获取失败")
    return yyid, top_sid, sub_sid or top_sid


def regex_int(text: str, pattern: str) -> int:
    match = re.search(pattern, text)
    return int(match.group(1)) if match else 0


async def huya_heartbeat(upstream: ClientConnection) -> None:
    while True:
        await asyncio.sleep(60)
        await upstream.send(HUYA_HEARTBEAT)


def huya_join_packet(ayyuid: int, top_sid: int, sub_sid: int) -> bytes:
    body = b"".join([
        tars_int(ayyuid, 0),
        tars_int(1, 1),
        tars_string("", 2),
        tars_string("", 3),
        tars_int(top_sid, 4),
        tars_int(sub_sid, 5),
        tars_int(0, 6),
        tars_int(0, 7),
    ])
    return tars_int(1, 0) + tars_bytes(body, 1)


async def huya_reader(websocket: WebSocket, upstream: ClientConnection) -> None:
    async for data in upstream:
        if isinstance(data, str):
            data = data.encode("utf-8")
        await handle_huya_packet(websocket, data)


async def handle_huya_packet(websocket: WebSocket, data: bytes) -> None:
    fields, _pos = tars_parse_struct(data, 0)
    command = fields.get(0)
    payload = fields.get(1)
    if not isinstance(payload, bytes):
        return

    if command == 7:
        push, _pos = tars_parse_struct(payload, 0)
        await handle_huya_message(websocket, int(push.get(1) or 0), push.get(2))
    elif command == 22:
        push_v2, _pos = tars_parse_struct(payload, 0)
        for item in push_v2.get(1) or []:
            if isinstance(item, dict):
                await handle_huya_message(websocket, int(item.get(0) or 0), item.get(1))


async def handle_huya_message(websocket: WebSocket, uri: int, payload: object) -> None:
    if not isinstance(payload, bytes):
        return
    if uri == 1400:
        message, _pos = tars_parse_struct(payload, 0)
        sender = message.get(0) if isinstance(message.get(0), dict) else {}
        bullet = message.get(6) if isinstance(message.get(6), dict) else {}
        color = int(bullet.get(0) or 0) if isinstance(bullet, dict) else 0
        await send_chat(
            websocket,
            "huya",
            str(sender.get(2) or ""),
            str(message.get(3) or ""),
            f"#{color:06x}" if color > 0 else None,
        )
    elif uri == 8006:
        fields, _pos = tars_parse_struct(payload, 0)
        online = fields.get(0)
        if isinstance(online, int):
            await send_online(websocket, "huya", online)


def tars_head(field_type: int, tag: int) -> bytes:
    if tag < 15:
        return bytes([(tag << 4) | field_type])
    return bytes([(15 << 4) | field_type, tag])


def tars_int(value: int, tag: int) -> bytes:
    if value == 0:
        return tars_head(12, tag)
    if -128 <= value <= 127:
        return tars_head(0, tag) + struct.pack(">b", value)
    if -32768 <= value <= 32767:
        return tars_head(1, tag) + struct.pack(">h", value)
    if -2147483648 <= value <= 2147483647:
        return tars_head(2, tag) + struct.pack(">i", value)
    return tars_head(3, tag) + struct.pack(">q", value)


def tars_string(value: str, tag: int) -> bytes:
    payload = value.encode("utf-8")
    if len(payload) < 256:
        return tars_head(6, tag) + struct.pack(">B", len(payload)) + payload
    return tars_head(7, tag) + struct.pack(">I", len(payload)) + payload


def tars_bytes(value: bytes, tag: int) -> bytes:
    return tars_head(13, tag) + tars_head(0, 0) + tars_int(len(value), 0) + value


def tars_parse_struct(data: bytes, pos: int) -> tuple[dict[int, object], int]:
    fields: dict[int, object] = {}
    while pos < len(data):
        field_type, tag, pos = tars_read_head(data, pos)
        if field_type == 11:
            break
        value, pos = tars_read_value(data, pos, field_type)
        fields[tag] = value
    return fields, pos


def tars_read_head(data: bytes, pos: int) -> tuple[int, int, int]:
    head = data[pos]
    pos += 1
    field_type = head & 0x0F
    tag = (head & 0xF0) >> 4
    if tag == 15:
        tag = data[pos]
        pos += 1
    return field_type, tag, pos


def tars_read_value(data: bytes, pos: int, field_type: int) -> tuple[object, int]:
    if field_type == 0:
        return struct.unpack_from(">b", data, pos)[0], pos + 1
    if field_type == 1:
        return struct.unpack_from(">h", data, pos)[0], pos + 2
    if field_type == 2:
        return struct.unpack_from(">i", data, pos)[0], pos + 4
    if field_type == 3:
        return struct.unpack_from(">q", data, pos)[0], pos + 8
    if field_type == 6:
        length = data[pos]
        pos += 1
        return data[pos:pos + length].decode("utf-8", errors="ignore"), pos + length
    if field_type == 7:
        length = struct.unpack_from(">I", data, pos)[0]
        pos += 4
        return data[pos:pos + length].decode("utf-8", errors="ignore"), pos + length
    if field_type == 10:
        return tars_parse_struct(data, pos)
    if field_type == 12:
        return 0, pos
    if field_type == 13:
        _item_type, _item_tag, pos = tars_read_head(data, pos)
        length_type, _length_tag, pos = tars_read_head(data, pos)
        length, pos = tars_read_value(data, pos, length_type)
        length = int(length)
        return data[pos:pos + length], pos + length
    if field_type == 9:
        length_type, _length_tag, pos = tars_read_head(data, pos)
        length, pos = tars_read_value(data, pos, length_type)
        items: list[object] = []
        for _ in range(int(length)):
            item_type, _item_tag, pos = tars_read_head(data, pos)
            item, pos = tars_read_value(data, pos, item_type)
            items.append(item)
        return items, pos
    return None, tars_skip_value(data, pos, field_type)


def tars_skip_value(data: bytes, pos: int, field_type: int) -> int:
    if field_type in {0, 4}:
        return pos + 1
    if field_type == 1:
        return pos + 2
    if field_type in {2, 5}:
        return pos + 4
    if field_type == 3:
        return pos + 8
    if field_type == 6:
        return pos + 1 + data[pos]
    if field_type == 7:
        return pos + 4 + struct.unpack_from(">I", data, pos)[0]
    if field_type == 10:
        _fields, pos = tars_parse_struct(data, pos)
        return pos
    if field_type == 12:
        return pos
    if field_type == 13:
        _item_type, _item_tag, pos = tars_read_head(data, pos)
        length_type, _length_tag, pos = tars_read_head(data, pos)
        length, pos = tars_read_value(data, pos, length_type)
        return pos + int(length)
    return pos
