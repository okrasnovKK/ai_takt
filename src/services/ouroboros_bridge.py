"""Ouroboros WebSocket bridge — connects ai-takt bot to Ouroboros agent.

Sends a chat message via WebSocket and returns the assistant's response.
"""
import asyncio
import json
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

SILENCE_PERIOD = 8  # seconds of silence to consider response complete
DEFAULT_TIMEOUT = 120  # overall timeout in seconds


async def ask_ouroboros(text: str, ws_url: str = "ws://localhost:8765/ws",
                        timeout: int = DEFAULT_TIMEOUT) -> str:
    """Send a message to Ouroboros via WebSocket and return the response.

    Returns the last non-progress assistant message, or an error string.
    """
    start_time = asyncio.get_event_loop().time()
    last_assistant_time: Optional[float] = None
    assistant_messages: list[str] = []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(ws_url, heartbeat=30) as ws:
                await ws.send_json({
                    "type": "chat",
                    "content": text,
                    "sender_session_id": "telegram-bridge",
                })

                while True:
                    now = asyncio.get_event_loop().time()
                    elapsed = now - start_time
                    if elapsed >= timeout:
                        break

                    if last_assistant_time:
                        silence = now - last_assistant_time
                        if silence >= SILENCE_PERIOD:
                            break

                    if last_assistant_time:
                        wait_time = min(SILENCE_PERIOD, timeout - elapsed)
                    else:
                        wait_time = min(15, timeout - elapsed)

                    try:
                        msg = await asyncio.wait_for(
                            ws.receive(),
                            timeout=wait_time
                        )
                    except asyncio.TimeoutError:
                        if last_assistant_time:
                            break
                        continue

                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            data = json.loads(msg.data)
                        except json.JSONDecodeError:
                            continue

                        if (data.get("type") == "chat" and
                                data.get("role") == "assistant" and
                                not data.get("is_progress", False)):
                            content = data.get("content", "").strip()
                            if content:
                                assistant_messages.append(content)
                                last_assistant_time = asyncio.get_event_loop().time()

                    elif msg.type in (aiohttp.WSMsgType.CLOSED,
                                      aiohttp.WSMsgType.ERROR):
                        break

                if assistant_messages:
                    return assistant_messages[-1]
                return "⚠️ Нет ответа от Ouroboros (таймаут)"

    except aiohttp.ClientConnectorError:
        return "⚠️ Ouroboros не запущен (localhost:8765)"
    except Exception as e:
        logger.error("Ouroboros bridge error: %s", e)
        return f"⚠️ Ошибка соединения: {e}"
