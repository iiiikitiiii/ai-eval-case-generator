"""Agent 统一架构改造方案（doc/Agent统一架构改造方案.md）：
UnifiedAgentRunner + AgentSpec + 有界修复循环。A/B/C/D/F 五个 agent
（阶段 0-4）都已经迁移完成并经过真实 LLM 调用验证，各自的
`run_agent_x()` 现在就是这里定义的统一入口——旧的手写实现（阶段 5）已经
删除，不再有并行的两条路径或特性开关。

不是开放式 agent loop——每个 Agent 的输入在运行开始时已经完备，这里不
给模型规划/调用工具的自由，只给它"输出没通过校验时，照着错误清单再试
一次"的有限自我修正机会（方案 2.1 节的结论）。三类失败分开处理（方案
5.1 节）：

- 瞬时基础设施错误（连接失败/超时）：指数退避重试，不消耗修复次数。
- 可修复输出错误（LLM 没有返回可解析结果，或返回了但没通过领域校验）：
  把错误清单和上一次的原始输出带回给模型，要求"只修复问题、保留合法
  内容"，有限次数。
- 不可修复业务错误（没有输入素材、没有已发布版本、前置人工关卡未完成、
  校验发现不可修复的问题）：不重试，直接失败。

每个 Agent 通过一个 `AgentSpec` 接入这个统一 runner，只需要提供三个函数
（构造请求 / 校验输出 / 落库）和一个重试策略；运行状态记录、进度/token
写入、成功失败收口这些跟具体 Agent 无关的机制全部在这里做一次。
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx
from sqlalchemy.orm import Session

from app.db.models.case import Case, PipelineRun
from app.services.llm_client import LLMStructuredError, run_structured
from app.services.pipeline.common import (
    PipelineError,
    finish_failed,
    finish_succeeded,
    get_published_version,
    make_progress_writer,
    make_usage_writer,
    mark_running,
)
from app.services.settings_service import get_llm_provider

# httpx 抛出的这几类是真正的"基础设施"问题（连不上、超时），跟
# LLMStructuredError（模型返回了东西，但解析/校验没通过）是两种不同性质
# 的失败，前者该重试，后者该走修复循环，不能用同一套重试次数混着算。
_TRANSIENT_EXCEPTIONS = (httpx.TransportError, httpx.TimeoutException)


@dataclass
class AgentRequest:
    user_text: str
    images: list[tuple[bytes, str]] | None = None
    # 跳过 LLM 调用，直接把这个当成"模型输出"送进 validate/persist——用于
    # D 这种"结构性答案已经从输入就能推出来"的情况（没有 real_gap 阶段时，
    # 补丁数组必然是空的，不该为一个已知答案花一次 token）。留空（默认）
    # 就是正常调用 run_structured。
    precomputed_result: dict | None = None
    # build_request 算出来、validate/persist 都需要复用的派生状态（比如
    # F 的 allowed_scenario_codes/persona_id_by_code）——不是发给模型的
    # 内容，只是三个阶段之间共享，避免同样的东西在三处分别算一遍、算出
    # 三份可能悄悄不一致的结果。大多数 agent 用不到，留空字典即可。
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationIssue:
    code: str  # 机器可读，如 missing_field / invalid_doc_ref
    message: str  # 给运行记录和修复 prompt 看的中文说明
    repairable: bool = True
    path: str | None = None


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.issues

    @property
    def has_unrepairable(self) -> bool:
        return any(not i.repairable for i in self.issues)


@dataclass
class RetryPolicy:
    max_network_retries: int = 2
    max_repairs: int = 1


@dataclass
class AgentSpec:
    code: str
    build_request: Callable[[Session, Case, PipelineRun], AgentRequest]
    # validate/persist 都额外收到 `request.context`（build_request 算出来的
    # 共享派生状态）——大多数 agent 用不到，签名里照样收着并忽略，理由
    # 跟下面 persist 收 `run` 一样：契约统一比"用不到就不传"更重要。
    validate: Callable[[Session, Case, dict, dict[str, Any]], ValidationResult]
    # persist 收到 `run`（不只是 case）——不是为了对称好看：Agent A 的
    # Document 行要写 agent_version_id，而 mark_running() 早就把解析出来
    # 的已发布版本 id 写进了 run.agent_version_id，persist 直接读它，不用
    # 自己再查一次 get_published_version()（那会是一次多余的重复查询，
    # 也可能跟本次运行实际用的版本不是同一个——已发布版本理论上可能在这
    # 次运行的过程中被人切换）。
    persist: Callable[[Session, Case, dict, PipelineRun, dict[str, Any]], dict]
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)


def _repair_user_text(original_user_text: str, previous_output: dict | None, issues: list[ValidationIssue]) -> str:
    """方案 5.2 节的修复 prompt 原则：带上一次的原始输出和错误清单，明确
    要求只修复问题、保留合法内容、不得补充输入资料里没有的事实，用的还是
    同一个 schema 和同一个 prompt 版本（system_prompt 不变，只在这里换
    user_text）。"""
    issue_lines = "\n".join(f"{i + 1}. {issue.message}" for i, issue in enumerate(issues))
    previous_block = (
        json.dumps(previous_output, ensure_ascii=False, indent=2)
        if previous_output is not None
        else "（上一次调用没有返回可解析的结构化结果）"
    )
    return (
        "上次输出未通过系统校验。请仅修复下列问题，并按既定 Schema 重新返回完整结果：\n"
        f"{issue_lines}\n\n"
        "保留所有已合法内容；不得补充输入资料中不存在的事实。\n\n"
        "【你上一次的原始输出】\n" + previous_block + "\n\n"
        "【原始任务】\n" + original_user_text
    )


async def run_with_framework(db: Session, spec: AgentSpec, case: Case, run: PipelineRun) -> None:
    try:
        version = get_published_version(db, spec.code)
        if version is None:
            raise PipelineError(f"Agent {spec.code} 没有已发布的版本，请先在 Prompt 后台发布一个")
        mark_running(db, run, version.id)

        request = spec.build_request(db, case, run)
        provider = get_llm_provider(db)
        on_progress = make_progress_writer(db, run)
        on_usage = make_usage_writer(db, run)

        network_retries = 0
        repairs = 0
        current_user_text = request.user_text
        last_raw_output: dict | None = None
        attempts: list[dict[str, Any]] = []
        result: dict | None = None

        if request.precomputed_result is not None:
            # 结构性答案已经从输入推出来了（比如没有 real_gap 阶段，补丁
            # 数组必然是空的）——不调用模型，但仍然过一遍 validate()，跟
            # 正常路径一样不允许"跳过校验"这个例外；只是这条路径没有 LLM
            # 输出可言，校验不通过就直接失败，不进修复循环（没有什么好
            # "发回给模型重试"的，这本来就不是模型给的答案）。
            result = request.precomputed_result
            attempts.append({"kind": "skipped_llm_call"})
            validation = spec.validate(db, case, result, request.context)
            if not validation.valid:
                raise PipelineError("；".join(i.message for i in validation.issues))
        else:
            while True:
                try:
                    result = await run_structured(
                        system_prompt=version.prompt_text, schema=version.out_schema,
                        user_text=current_user_text, images=request.images,
                        provider=provider, on_progress=on_progress, on_usage=on_usage,
                    )
                except _TRANSIENT_EXCEPTIONS as exc:
                    attempts.append({"kind": "network_error", "detail": str(exc)})
                    if network_retries >= spec.retry_policy.max_network_retries:
                        raise PipelineError(f"网络/基础设施错误，重试 {network_retries} 次后仍失败：{exc}") from exc
                    network_retries += 1
                    await asyncio.sleep(min(2**network_retries, 8))
                    continue
                except LLMStructuredError as exc:
                    attempts.append({"kind": "llm_output_error", "detail": str(exc)})
                    if repairs >= spec.retry_policy.max_repairs:
                        raise PipelineError(f"模型输出解析失败，修复 {repairs} 次后仍失败：{exc}") from exc
                    repairs += 1
                    current_user_text = _repair_user_text(request.user_text, last_raw_output, [ValidationIssue(code="output_parse_error", message=str(exc))])
                    continue

                last_raw_output = result
                validation = spec.validate(db, case, result, request.context)
                if validation.valid:
                    attempts.append({"kind": "success"})
                    break

                attempts.append({"kind": "validation_error", "issues": [i.message for i in validation.issues]})
                if validation.has_unrepairable or repairs >= spec.retry_policy.max_repairs:
                    raise PipelineError("；".join(i.message for i in validation.issues))
                repairs += 1
                current_user_text = _repair_user_text(request.user_text, result, validation.issues)

        assert result is not None
        output_ref = spec.persist(db, case, result, run, request.context)
        output_ref = {**output_ref, "attempt_count": len(attempts), "repair_count": repairs, "attempts": attempts}
        finish_succeeded(db, run, output_ref)
    except Exception as exc:  # noqa: BLE001 — every failure here must still park the case as `blocked`, not hang it in `running`/`queued`
        finish_failed(db, case, run, exc)
        raise
