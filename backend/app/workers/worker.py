"""arq worker process — runs the A/B/C/D/F pipeline steps out of band, so
the API never blocks a request on an LLM call. Every step follows the same
shape: the API layer has already created a `PipelineRun` row (status=queued)
before enqueueing; this worker loads it, hands it to the matching
`run_agent_x(db, case, run)`, and that function does the rest (mark
running, do the work, mark succeeded/failed) — same code path whether it's
invoked from here or, in phase 3, from a sandbox test run.

Run locally with:  arq app.workers.worker.WorkerSettings
"""
import asyncio
import logging
import uuid

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.db.models.case import Case, PipelineRun
from app.db.session import SessionLocal
from app.services.pipeline import agent_a, agent_b, agent_c, agent_d, agent_f
from app.services.pipeline.common import finish_failed

settings = get_settings()
logger = logging.getLogger("worker")

# 所有五个 agent 都已经完成 Agent 统一架构改造方案的迁移（阶段 0-4，
# 见 README）：各自的 run_agent_x() 现在就是 UnifiedAgentRunner 版本，
# 旧的手写实现和阶段迁移用的特性开关都已经删掉——不再需要在这里按开关
# 选路径。
_RUNNERS = {
    "A": agent_a.run_agent_a,
    "B": agent_b.run_agent_b,
    "C": agent_c.run_agent_c,
    "D": agent_d.run_agent_d,
    "F": agent_f.run_agent_f,
}


async def run_pipeline_step(ctx: dict, run_id: str, agent_code: str) -> dict:
    if agent_code not in _RUNNERS:
        raise ValueError(f"未知 agent_code：{agent_code}")

    db = SessionLocal()
    try:
        run = db.get(PipelineRun, uuid.UUID(run_id))
        if run is None:
            logger.error("pipeline run %s 不存在，跳过", run_id)
            return {"run_id": run_id, "status": "missing"}

        case = db.get(Case, run.case_id)
        if case is None:
            logger.error("pipeline run %s 引用的 case %s 不存在", run_id, run.case_id)
            return {"run_id": run_id, "status": "missing_case"}

        try:
            await _RUNNERS[agent_code](db, case, run)
            return {"run_id": run_id, "agent_code": agent_code, "status": "succeeded"}
        except asyncio.CancelledError:
            # arq 用 job_timeout 强制取消跑超时的任务走的是这条路，不是普通
            # Exception——CancelledError 是 BaseException 的子类，
            # run_agent_x 自己那层 `except Exception` 接不住，所以之前
            # 一旦真的超时，PipelineRun 就会永远卡在 running：真实撞见过
            # 一次，一条 F 的记录卡了 9.5 小时没有任何东西把它标记失败，
            # 前端只会一直显示"运行中"。这里兜底明确写一条 failed，
            # 再按 asyncio 的规矩把 CancelledError 重新抛出去，不吞掉。
            logger.warning("pipeline run %s (%s) cancelled (job_timeout=%ss)", run_id, agent_code, WorkerSettings.job_timeout)
            try:
                finish_failed(
                    db, case, run,
                    RuntimeError(f"运行超时被强制取消（超过 job_timeout={WorkerSettings.job_timeout}s）——不是模型或网络报错，直接重试即可"),
                )
            except Exception:  # noqa: BLE001 — 兜底写失败状态这一步本身不能再抛出去把 worker 拖垮
                logger.exception("marking cancelled run %s as failed also raised", run_id)
            raise
        except Exception as exc:  # noqa: BLE001 — run_agent_x already wrote the failure to the DB; just don't crash the worker
            logger.warning("pipeline run %s (%s) failed: %s", run_id, agent_code, exc)
            return {"run_id": run_id, "agent_code": agent_code, "status": "failed"}
    finally:
        db.close()


async def on_startup(ctx: dict) -> None:
    logger.info("worker started, redis=%s", settings.redis_url)


class WorkerSettings:
    functions = [run_pipeline_step]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    on_startup = on_startup
    job_timeout = 600  # F has been observed to take ~4 minutes; leave headroom
    # arq's own default is 10 — well past what either LLM provider actually
    # allows concurrently (MiniMax/Kimi accounts here are capped at 3
    # concurrent requests). Left at the default, enough cases queued at once
    # would fire more than 3 simultaneous calls at the provider and start
    # eating 429s instead of finishing faster — capping the worker itself is
    # the fix, not a retry/backoff band-aid on top of an oversized queue.
    max_jobs = 3
