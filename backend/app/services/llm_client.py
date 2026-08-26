"""One function — `run_structured` — that any agent runner calls to get a
schema-conformant dict back from whichever LLM provider is active. Which
one that is comes from `app.services.settings_service.get_llm_provider()`
(a DB row callers fetch and pass in as `provider`, since it's switchable at
runtime from the Prompt 后台 page — see that module's docstring), falling
back to `settings.llm_provider` when the caller doesn't pass one. Three
backends:

- **minimax** (default): OpenAI-compatible `/chat/completions`, called
  directly via httpx rather than the `openai` SDK — MiniMax's contract has
  a few non-standard fields (`thinking`, `reasoning_split`,
  `max_completion_tokens` as the primary token-limit param) that are
  simpler to send exactly as documented than to coerce through a
  generic client. Important asymmetry vs. OpenAI/Anthropic: MiniMax's
  `/chat/completions` takes `tools` but has **no `tool_choice`** — the
  model decides whether to call a tool, it can't be forced. We compensate
  with an explicit system-prompt instruction (empirically reliable — see
  the manual test that shipped with this change) and a fallback that
  parses `message.content` as JSON if the model answers in plain text
  anyway. `reasoning_split: true` keeps `<think>` content out of
  `content` so that fallback isn't fighting reasoning text.
- **kimi** (Kimi K3 / Moonshot): also OpenAI-compatible `/chat/completions`,
  called the same direct-httpx way — but unlike MiniMax, Kimi genuinely
  supports `tool_choice="required"`, so there's no system-prompt-hint /
  content-fallback dance needed here; the model is forced to call the tool.
- **anthropic**: Claude Messages API with forced tool-use, kept as an
  alternate backend behind the same interface — no agent code needs to
  know which provider is active.

minimax/kimi are both called with `stream=True` — not for the final
result (callers still get one dict back, same as before), but so the
model's `reasoning_content` deltas can be surfaced live via `on_progress`
while the call is in flight. See `_stream_openai_compatible` for the SSE
parsing and `app.services.pipeline.common.make_progress_writer` for what
callers actually pass as `on_progress` (a rolling snapshot written to
`PipelineRun.progress_note`, polled by the trace page — no new transport
layer, just reusing the polling the frontend already does).
"""
import base64
import json
import re
import time
from collections.abc import Callable

import httpx
from anthropic import AsyncAnthropic
from anthropic.types import ToolUseBlock

from app.core.config import get_settings

settings = get_settings()

_TOOL_NAME = "emit_result"
_FORCE_TOOL_HINT = (
    "\n\n【输出方式】你必须调用 emit_result 函数返回结果，不要用纯文本回答，"
    "不要在文本里复述或解释结果，函数参数就是最终答案。"
)


class LLMStructuredError(RuntimeError):
    """Raised when the model doesn't return a schema-conformant result at all."""


async def run_structured(
    *,
    system_prompt: str,
    schema: dict,
    user_text: str,
    images: list[tuple[bytes, str]] | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    provider: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    on_usage: Callable[[dict], None] | None = None,
) -> dict:
    """images: list of (raw_bytes, content_type) pairs, sent before user_text.
    provider: which backend to use for this call — callers fetch this once
    via settings_service.get_llm_provider(db) and pass it through, since
    it's a runtime-switchable DB setting, not a static env var.
    on_progress: called (throttled, ~every 1.5s) with the model's
    accumulated reasoning/content text so far, while streaming — minimax
    and kimi only; anthropic isn't wired for this yet since neither active
    provider is anthropic in practice.
    on_usage: called once, after the call completes, with
    {"provider", "model", "prompt_tokens", "completion_tokens", "total_tokens"}
    — only if the provider actually returned usage (minimax/kimi need
    stream_options.include_usage, which is always requested, but a
    provider outage or an old API version could still omit it; anthropic
    always returns usage since it isn't streamed here)."""
    max_tokens = max_tokens or settings.llm_max_tokens
    provider = provider or settings.llm_provider
    if provider == "anthropic":
        return await _run_anthropic(system_prompt, schema, user_text, images, model, max_tokens, on_usage)
    if provider == "kimi":
        return await _run_kimi(system_prompt, schema, user_text, images, model, max_tokens, on_progress, on_usage)
    return await _run_minimax(system_prompt, schema, user_text, images, model, max_tokens, on_progress, on_usage)


async def _stream_openai_compatible(
    url: str,
    headers: dict,
    payload: dict,
    on_progress: Callable[[str], None] | None,
    error_label: str,
) -> dict:
    """POST an OpenAI-compatible /chat/completions request with stream=True
    (MiniMax and Kimi both implement this SSE contract identically) and
    return the fully-accumulated message shape once the stream ends —
    callers still get one dict back, same as a non-streaming call would;
    streaming here is purely so on_progress can be called along the way.

    stream_options.include_usage asks the provider to emit one extra chunk
    at the very end carrying real token counts — per the OpenAI-compatible
    convention that chunk has an *empty* `choices` array, so usage has to
    be read before the "no choices, skip" branch or it's silently dropped.
    """
    payload = {**payload, "stream": True, "stream_options": {"include_usage": True}}
    reasoning_text = ""
    content_text = ""
    tool_calls: dict[int, dict] = {}
    finish_reason = None
    usage: dict | None = None
    last_progress_at = 0.0

    async with httpx.AsyncClient(timeout=420) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if not resp.is_success:
                raw = await resp.aread()
                raise LLMStructuredError(f"{error_label}接口报错（HTTP {resp.status_code}）：{raw[:300]!r}")

            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage"):
                    usage = chunk["usage"]

                choices = chunk.get("choices") or []
                if not choices:
                    continue
                choice = choices[0]
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning_text += delta["reasoning_content"]
                if delta.get("content"):
                    content_text += delta["content"]
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = tool_calls.setdefault(idx, {"name": None, "arguments": ""})
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

                if on_progress:
                    now = time.monotonic()
                    preview = reasoning_text or content_text
                    if preview and now - last_progress_at > 1.5:
                        on_progress(preview[-4000:])  # 只留最近这段，别让快照无限变长
                        last_progress_at = now

    return {
        "content": content_text,
        "reasoning_content": reasoning_text,
        "tool_calls": [
            {"function": {"name": v["name"], "arguments": v["arguments"]}}
            for v in tool_calls.values()
            if v["name"]
        ],
        "finish_reason": finish_reason,
        "usage": usage,
    }


def _report_usage(on_usage: Callable[[dict], None] | None, provider: str, model: str, raw_usage: dict | None) -> None:
    """raw_usage is the provider's own usage object (already OpenAI-shaped
    for minimax/kimi) — normalize to the one shape callers persist, and
    just skip silently if the provider didn't send one rather than making
    every caller null-check."""
    if not on_usage or not raw_usage:
        return
    on_usage(
        {
            "provider": provider,
            "model": model,
            "prompt_tokens": raw_usage.get("prompt_tokens"),
            "completion_tokens": raw_usage.get("completion_tokens"),
            "total_tokens": raw_usage.get("total_tokens"),
        }
    )


async def _run_minimax(
    system_prompt: str,
    schema: dict,
    user_text: str,
    images: list[tuple[bytes, str]] | None,
    model: str | None,
    max_tokens: int,
    on_progress: Callable[[str], None] | None,
    on_usage: Callable[[dict], None] | None,
) -> dict:
    content: list[dict] = []
    for raw, content_type in images or []:
        b64 = base64.b64encode(raw).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}})
    content.append({"type": "text", "text": user_text})

    payload = {
        "model": model or settings.minimax_model,
        "messages": [
            {"role": "system", "content": system_prompt + _FORCE_TOOL_HINT},
            {"role": "user", "content": content},
        ],
        "thinking": {"type": "adaptive"},
        "reasoning_split": True,
        "max_completion_tokens": max_tokens,
        "tools": [
            {
                "type": "function",
                "function": {"name": _TOOL_NAME, "description": "输出结构化结果", "parameters": schema},
            }
        ],
    }

    message = await _stream_openai_compatible(
        f"{settings.minimax_base_url}/chat/completions",
        {"Authorization": f"Bearer {settings.minimax_api_key}", "Content-Type": "application/json"},
        payload,
        on_progress,
        "MiniMax ",
    )
    # 无论最终解析成不成功都要报——截断/解析失败的调用照样花了 token，
    # 看板要看到真实花销，不是只统计"成功"的那部分。
    _report_usage(on_usage, "minimax", model or settings.minimax_model, message["usage"])

    if message["finish_reason"] == "length":
        raise LLMStructuredError(
            f"响应在完成前被截断（finish_reason=length，max_completion_tokens={max_tokens}）——"
            "多半是 thinking 用掉了大半预算，调大 max_tokens 或简化这次调用的上下文再试"
        )

    for call in message["tool_calls"]:
        if call["function"]["name"] == _TOOL_NAME:
            args = call["function"]["arguments"] or ""
            try:
                return json.loads(args)
            except json.JSONDecodeError as exc:
                # 之前这里只报 json 库自己的报错，看不出模型到底吐了什么——
                # 调试一次真实失败花了大量来回。带上原始内容的前后片段，
                # 下次直接在运行记录里就能看出是格式错误还是内容本身有问题。
                raise LLMStructuredError(
                    f"emit_result 的参数不是合法 JSON：{exc}\n"
                    f"原始内容开头 300 字：{args[:300]!r}\n"
                    f"原始内容结尾 300 字：{args[-300:]!r}"
                ) from exc

    # 没有 tool_choice 可以强制——退一步，把 content 当 JSON 解析（剥掉可能的
    # ```json 代码块围栏），content 已经因 reasoning_split=true 而不含思考文本。
    text = re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", (message["content"] or "").strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMStructuredError(
            f"模型既没有调用 {_TOOL_NAME}，返回内容也不是合法 JSON（前 300 字：{text[:300]!r}）"
        ) from exc


async def _run_kimi(
    system_prompt: str,
    schema: dict,
    user_text: str,
    images: list[tuple[bytes, str]] | None,
    model: str | None,
    max_tokens: int,
    on_progress: Callable[[str], None] | None,
    on_usage: Callable[[dict], None] | None,
) -> dict:
    content: list[dict] = []
    for raw, content_type in images or []:
        b64 = base64.b64encode(raw).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{b64}"}})
    content.append({"type": "text", "text": user_text})

    payload = {
        "model": model or settings.kimi_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ],
        "max_completion_tokens": max_tokens,
        "reasoning_effort": settings.kimi_reasoning_effort,
        "tools": [
            {
                "type": "function",
                "function": {"name": _TOOL_NAME, "description": "输出结构化结果", "parameters": schema},
            }
        ],
        # Kimi 真的支持强制调用，不用像 MiniMax 那样靠 prompt 提示 + 内容
        # 兜底解析——这是选它的理由之一。
        "tool_choice": "required",
    }

    message = await _stream_openai_compatible(
        f"{settings.kimi_base_url}/chat/completions",
        {"Authorization": f"Bearer {settings.kimi_api_key}", "Content-Type": "application/json"},
        payload,
        on_progress,
        "Kimi ",
    )
    _report_usage(on_usage, "kimi", model or settings.kimi_model, message["usage"])

    if message["finish_reason"] == "length":
        raise LLMStructuredError(
            f"响应在完成前被截断（finish_reason=length，max_completion_tokens={max_tokens}）——"
            "调大 max_tokens 或简化这次调用的上下文再试"
        )

    for call in message["tool_calls"]:
        if call["function"]["name"] == _TOOL_NAME:
            args = call["function"]["arguments"] or ""
            try:
                return json.loads(args)
            except json.JSONDecodeError as exc:
                raise LLMStructuredError(
                    f"emit_result 的参数不是合法 JSON：{exc}\n"
                    f"原始内容开头 300 字：{args[:300]!r}\n"
                    f"原始内容结尾 300 字：{args[-300:]!r}"
                ) from exc

    raise LLMStructuredError(
        f"Kimi 没有调用 {_TOOL_NAME}（tool_choice=required 理论上应该强制调用，"
        f"finish_reason={message['finish_reason']}，这是需要留意的异常情况）"
    )


async def _run_anthropic(
    system_prompt: str,
    schema: dict,
    user_text: str,
    images: list[tuple[bytes, str]] | None,
    model: str | None,
    max_tokens: int,
    on_usage: Callable[[dict], None] | None,
) -> dict:
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    content: list[dict] = []
    for raw, content_type in images or []:
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": content_type, "data": base64.b64encode(raw).decode("ascii")},
            }
        )
    content.append({"type": "text", "text": user_text})

    response = await client.messages.create(
        model=model or settings.llm_model,
        max_tokens=max_tokens,
        system=system_prompt,
        tools=[{"name": _TOOL_NAME, "description": "输出结构化结果", "input_schema": schema}],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": content}],
    )
    if on_usage and response.usage:
        on_usage(
            {
                "provider": "anthropic",
                "model": model or settings.llm_model,
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }
        )

    for block in response.content:
        if isinstance(block, ToolUseBlock) and block.name == _TOOL_NAME:
            return block.input  # type: ignore[return-value]

    raise LLMStructuredError("模型没有返回结构化结果（未命中 tool_use）")
