import json
import logging
import os
import time
import uuid
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("proxy")

# ============== 配置区（直接改这里，PyCharm 点 Run 即可） ==============
UPSTREAM_BASE_URL = "https://aiadm-edps.lenovo.com.cn/ics-nm/projects/123/superagent-test/aiverse/endpoint/v1"
UPSTREAM_API_KEY = "TEST-KEY-YUXT85CCE2T"
DEFAULT_UPSTREAM_MODEL = "Qwen3.5_27B"
PORT = 18889

# 调试开关——遇到上游 400 时逐个打开 / 关闭来定位问题字段
STRIP_TOOLS = False            # True = 不转发 tools（多数自建 Qwen 后端不支持）
STRIP_STREAM_OPTIONS = True   # True = 不传 stream_options.include_usage
FORCE_NON_STREAM = True       # True = 强制用非流式调上游，再伪造 SSE 返回给插件
DROP_EMPTY_ASSISTANT = True   # True = 过滤掉 content=None 且无 tool_calls 的空 assistant 消息
MAX_TOKENS_CAP = 4096         # max_tokens 上限，超过这个会被裁剪
# ==================================================================

MODEL_MAP = {
    # Claude 3.x + 4.x → 全部映射到上游 Qwen 模型
    "claude-3-5-sonnet-20241022": DEFAULT_UPSTREAM_MODEL,
    "claude-3-5-haiku-20241022": DEFAULT_UPSTREAM_MODEL,
    "claude-3-opus-20240229": DEFAULT_UPSTREAM_MODEL,
    "claude-3-sonnet-20240229": DEFAULT_UPSTREAM_MODEL,
    "claude-3-haiku-20240307": DEFAULT_UPSTREAM_MODEL,
    "claude-sonnet-4-20250514": DEFAULT_UPSTREAM_MODEL,
    "claude-opus-4-20250514": DEFAULT_UPSTREAM_MODEL,
    "claude-haiku-3-5-20250514": DEFAULT_UPSTREAM_MODEL,
}
assert isinstance(MODEL_MAP, dict), f"MODEL_MAP must be dict, got {type(MODEL_MAP)}"

app = FastAPI()


@app.get("/")
@app.head("/")
async def root():
    return {"ok": True, "service": "anthropic-to-openai-proxy"}


def anthropic_to_openai_messages(payload: dict) -> dict:
    out_messages: list[dict] = []

    system = payload.get("system")
    if isinstance(system, str) and system.strip():
        out_messages.append({"role": "system", "content": system})
    elif isinstance(system, list):
        text = "\n\n".join(b.get("text", "") for b in system if b.get("type") == "text")
        if text:
            out_messages.append({"role": "system", "content": text})

    for msg in payload.get("messages", []):
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            out_messages.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        tool_results: list[dict] = []

        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })
            elif btype == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, list):
                    result_content = "\n".join(
                        c.get("text", "") for c in result_content if c.get("type") == "text"
                    )
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": block["tool_use_id"],
                    "content": str(result_content),
                })

        if role == "assistant":
            assistant_msg: dict = {"role": "assistant"}
            if text_parts:
                assistant_msg["content"] = "".join(text_parts)
            else:
                assistant_msg["content"] = None
            if tool_calls and not STRIP_TOOLS:
                assistant_msg["tool_calls"] = tool_calls
            # STRIP_TOOLS=True 且 assistant 只有 tool_use 无文本时，过滤掉空消息
            if DROP_EMPTY_ASSISTANT and assistant_msg.get("content") is None and "tool_calls" not in assistant_msg:
                log.debug("dropped empty assistant message")
                continue
            out_messages.append(assistant_msg)
        else:
            if text_parts:
                # 保留原 role（user 或可能的 system reminder），最后统一收敛 system
                out_messages.append({"role": role, "content": "".join(text_parts)})
            # STRIP_TOOLS=True 时，tool_result 也丢掉，保证 role 交替合法
            if not STRIP_TOOLS:
                out_messages.extend(tool_results)
            elif tool_results:
                log.debug("dropped %d tool_result messages", len(tool_results))

    # ====== 兼底：上游 Qwen 报 "System message must be at the beginning" ======
    # 把所有 role=system 的消息合并成 1 条放最前面（即便 Claude Code 在 messages 里塞了 system reminder）
    system_msgs = [m for m in out_messages if m.get("role") == "system"]
    other_msgs = [m for m in out_messages if m.get("role") != "system"]
    if system_msgs:
        merged_sys = "\n\n".join(str(m.get("content") or "") for m in system_msgs)
        out_messages = [{"role": "system", "content": merged_sys}] + other_msgs
        if len(system_msgs) > 1:
            log.warning("merged %d system messages into 1 at position 0", len(system_msgs))
    log.info("final roles=%s total=%d",
             [m.get("role") for m in out_messages], len(out_messages))

    # 裁剪 max_tokens，避免超上游上限导致 400
    requested_max = payload.get("max_tokens", 4096)
    capped_max = min(requested_max, MAX_TOKENS_CAP) if MAX_TOKENS_CAP > 0 else requested_max

    openai_payload: dict = {
        # 任何未知型号都回退到唯一的上游模型
        "model": MODEL_MAP.get(payload["model"], DEFAULT_UPSTREAM_MODEL),
        "messages": out_messages,
        "stream": payload.get("stream", False),
        "max_tokens": capped_max,
    }
    if openai_payload["stream"] and not STRIP_STREAM_OPTIONS:
        openai_payload["stream_options"] = {"include_usage": True}
    if "temperature" in payload:
        openai_payload["temperature"] = payload["temperature"]
    if "top_p" in payload:
        openai_payload["top_p"] = payload["top_p"]
    if "stop_sequences" in payload:
        openai_payload["stop"] = payload["stop_sequences"]

    if "tools" in payload and not STRIP_TOOLS:
        openai_payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            }
            for t in payload["tools"]
        ]
    elif STRIP_TOOLS and "tools" in payload:
        log.info("STRIP_TOOLS=true, dropped %d tools", len(payload["tools"]))

    return openai_payload


def openai_to_anthropic_response(openai_resp: dict, original_model: str) -> dict:
    choice = openai_resp["choices"][0]
    msg = choice["message"]

    content_blocks: list[dict] = []
    # Qwen 把最终回答放 content，思考过程放 reasoning_content。
    # max_tokens 用完仍未走完思考时，content 可能为空——这时回退到 reasoning_content，
    # 避免插件画面空白。
    visible_text = msg.get("content") or msg.get("reasoning_content") or ""
    if visible_text:
        content_blocks.append({"type": "text", "text": visible_text})
    for tc in msg.get("tool_calls") or []:
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        content_blocks.append({
            "type": "tool_use",
            "id": tc["id"],
            "name": tc["function"]["name"],
            "input": args,
        })

    finish_map = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "end_turn",
    }
    stop_reason = finish_map.get(choice.get("finish_reason"), "end_turn")

    usage = openai_resp.get("usage") or {}
    return {
        "id": "msg_" + uuid.uuid4().hex,
        "type": "message",
        "role": "assistant",
        "model": original_model,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def sse(event: str, data: dict) -> bytes:
    payload = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    log.debug("SSE -> client: event=%s data=%s", event, json.dumps(data, ensure_ascii=False)[:300])
    return payload.encode("utf-8")


async def stream_openai_to_anthropic(
    upstream: AsyncIterator[bytes],
    original_model: str,
) -> AsyncIterator[bytes]:
    message_id = "msg_" + uuid.uuid4().hex
    yield sse("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": original_model,
            "content": [],
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })

    text_block_open = False
    tool_blocks: dict[int, dict] = {}
    finish_reason = "stop"
    usage = {"input_tokens": 0, "output_tokens": 0}

    buffer = ""
    async for chunk in upstream:
        decoded = chunk.decode("utf-8", errors="ignore")
        log.debug("upstream raw chunk: %r", decoded[:300])
        buffer += decoded
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload_str = line[5:].strip()
            if payload_str == "[DONE]":
                log.debug("upstream sent [DONE]")
                continue
            try:
                data = json.loads(payload_str)
            except json.JSONDecodeError as e:
                log.warning("failed to parse upstream chunk: %s | raw=%r", e, payload_str[:200])
                continue

            if "usage" in data and data["usage"]:
                u = data["usage"]
                usage["input_tokens"] = u.get("prompt_tokens", usage["input_tokens"])
                usage["output_tokens"] = u.get("completion_tokens", usage["output_tokens"])

            choices = data.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            fr = choices[0].get("finish_reason")
            if fr:
                finish_reason = fr

            # Qwen 在思考阶段只发 reasoning_content，正式回答阶段才发 content；都当成可见文本流给插件
            text_delta = delta.get("content") or delta.get("reasoning_content")
            if text_delta:
                if not text_block_open:
                    yield sse("content_block_start", {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    })
                    text_block_open = True
                yield sse("content_block_delta", {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text_delta},
                })

            for tc in delta.get("tool_calls") or []:
                idx = tc["index"] + 1
                if idx not in tool_blocks:
                    tool_blocks[idx] = {"id": tc.get("id", ""), "name": "", "args": ""}
                    yield sse("content_block_start", {
                        "type": "content_block_start",
                        "index": idx,
                        "content_block": {
                            "type": "tool_use",
                            "id": tool_blocks[idx]["id"],
                            "name": tc.get("function", {}).get("name", ""),
                            "input": {},
                        },
                    })
                fn = tc.get("function") or {}
                if fn.get("arguments"):
                    tool_blocks[idx]["args"] += fn["arguments"]
                    yield sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": idx,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": fn["arguments"],
                        },
                    })

    if text_block_open:
        yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    for idx in tool_blocks:
        yield sse("content_block_stop", {"type": "content_block_stop", "index": idx})

    stop_reason_map = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
    }
    yield sse("message_delta", {
        "type": "message_delta",
        "delta": {
            "stop_reason": stop_reason_map.get(finish_reason, "end_turn"),
            "stop_sequence": None,
        },
        "usage": usage,
    })
    yield sse("message_stop", {"type": "message_stop"})


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
    "Content-Type": "text/event-stream; charset=utf-8",
}


async def fake_stream_from_full_response(openai_resp: dict, original_model: str) -> AsyncIterator[bytes]:
    """拿到一个完整的非流式 OpenAI 响应，伪造 Anthropic SSE 事件流发给插件。
    v1.4：补上 tool_use content block 的转发，否则 Claude Code 报
    'tool call could not be parsed'。
    """
    message_id = "msg_" + uuid.uuid4().hex
    yield sse("message_start", {
        "type": "message_start",
        "message": {
            "id": message_id, "type": "message", "role": "assistant",
            "model": original_model, "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    })
    choice = (openai_resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or msg.get("reasoning_content") or ""
    tool_calls = msg.get("tool_calls") or []
    log.info("fake-stream: text_len=%d tool_calls=%d finish=%s",
             len(text), len(tool_calls), choice.get("finish_reason"))

    block_idx = 0

    # 1) 文本块（如果有）
    if text:
        yield sse("content_block_start", {
            "type": "content_block_start", "index": block_idx,
            "content_block": {"type": "text", "text": ""},
        })
        step = 30
        for i in range(0, len(text), step):
            yield sse("content_block_delta", {
                "type": "content_block_delta", "index": block_idx,
                "delta": {"type": "text_delta", "text": text[i:i + step]},
            })
        yield sse("content_block_stop", {"type": "content_block_stop", "index": block_idx})
        block_idx += 1

    # 2) tool_use 块（v1.4 关键修复！每个 tool_call 都要发出去，否则 Claude Code 报
    # "tool call could not be parsed"）
    for tc in tool_calls:
        args_str = (tc.get("function") or {}).get("arguments") or "{}"
        # JSON 校验：上游小模型偶尔出残缺 JSON，兜底成空对象
        try:
            json.loads(args_str)
        except json.JSONDecodeError:
            log.warning("invalid tool_call arguments JSON, fallback to {}: %s", args_str[:200])
            args_str = "{}"
        tool_use_id = tc.get("id") or ("toolu_" + uuid.uuid4().hex)
        tool_name = (tc.get("function") or {}).get("name", "")
        log.info("fake-stream tool_use: name=%s id=%s args=%s",
                 tool_name, tool_use_id, args_str[:200])
        yield sse("content_block_start", {
            "type": "content_block_start", "index": block_idx,
            "content_block": {
                "type": "tool_use",
                "id": tool_use_id,
                "name": tool_name,
                "input": {},
            },
        })
        # 一次性把整个 arguments 当作 partial_json 发过去
        yield sse("content_block_delta", {
            "type": "content_block_delta", "index": block_idx,
            "delta": {"type": "input_json_delta", "partial_json": args_str},
        })
        yield sse("content_block_stop", {"type": "content_block_stop", "index": block_idx})
        block_idx += 1

    finish_map = {"stop": "end_turn", "length": "max_tokens", "tool_calls": "tool_use"}
    usage = openai_resp.get("usage") or {}
    yield sse("message_delta", {
        "type": "message_delta",
        "delta": {
            "stop_reason": finish_map.get(choice.get("finish_reason"), "end_turn"),
            "stop_sequence": None,
        },
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    })
    yield sse("message_stop", {"type": "message_stop"})


@app.post("/v1/messages")
async def messages_endpoint(request: Request):
    body = await request.json()
    original_model = body.get("model", "")
    stream = body.get("stream", False)
    log.info("incoming: model=%s stream=%s tools=%s msgs=%d",
             original_model, stream, bool(body.get("tools")), len(body.get("messages", [])))
    openai_payload = anthropic_to_openai_messages(body)
    if FORCE_NON_STREAM:
        openai_payload["stream"] = False
        openai_payload.pop("stream_options", None)
    log.debug("upstream payload: %s", json.dumps(openai_payload, ensure_ascii=False)[:600])

    headers = {
        "Authorization": f"Bearer {UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
    }
    url = UPSTREAM_BASE_URL.rstrip("/") + "/chat/completions"

    # 客户端要流式 + FORCE_NON_STREAM = 上游非流 + 伪 SSE 回客户端
    if stream and FORCE_NON_STREAM:
        async def gen_fake():
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(url, headers=headers, json=openai_payload)
                log.info("upstream (fake-stream) status=%s", r.status_code)
                if r.status_code != 200:
                    log.error("upstream error body: %s", r.text[:800])
                    async for piece in fake_stream_from_full_response(
                        {"choices": [{"message": {"content": f"[upstream {r.status_code}] {r.text[:500]}"}, "finish_reason": "stop"}]},
                        original_model,
                    ):
                        yield piece
                    return
                async for piece in fake_stream_from_full_response(r.json(), original_model):
                    yield piece
        return StreamingResponse(gen_fake(), headers=SSE_HEADERS)

    if not stream:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(url, headers=headers, json=openai_payload)
            log.info("upstream non-stream status=%s", r.status_code)
            if r.status_code != 200:
                log.error("upstream error body: %s", r.text[:500])
                return JSONResponse(status_code=r.status_code, content={
                    "type": "error",
                    "error": {"type": "api_error", "message": r.text},
                })
            return JSONResponse(content=openai_to_anthropic_response(r.json(), original_model))

    async def gen():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, headers=headers, json=openai_payload) as r:
                log.info("upstream stream status=%s content-type=%s",
                         r.status_code, r.headers.get("content-type"))
                if r.status_code != 200:
                    err = await r.aread()
                    log.error("upstream stream error: %s", err.decode("utf-8", errors="ignore")[:500])
                    yield sse("message_start", {
                        "type": "message_start",
                        "message": {
                            "id": "msg_err", "type": "message", "role": "assistant",
                            "model": original_model, "content": [],
                            "stop_reason": None, "stop_sequence": None,
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        },
                    })
                    yield sse("content_block_start", {
                        "type": "content_block_start", "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    })
                    yield sse("content_block_delta", {
                        "type": "content_block_delta", "index": 0,
                        "delta": {"type": "text_delta",
                                  "text": f"[upstream {r.status_code}] {err.decode('utf-8', errors='ignore')[:300]}"},
                    })
                    yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
                    yield sse("message_delta", {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    })
                    yield sse("message_stop", {"type": "message_stop"})
                    return
                async for piece in stream_openai_to_anthropic(r.aiter_bytes(), original_model):
                    yield piece

    return StreamingResponse(gen(), headers=SSE_HEADERS)


@app.get("/health")
async def health():
    return {"ok": True, "ts": int(time.time())}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT)