"""沙盒试跑：拿一个真实病例的真实输入数据，跑一个还没发布（甚至还没存成
版本）的 prompt 草稿，只返回原始结果，不写数据库。工程师改完 prompt 想看
"这样改会不会更好"，不用先发布、不用等下一个真实病例流入才发现改坏了。

每个 agent 复用它在正式 runner 里已经在用的同一套上下文构造逻辑
（app.services.pipeline.agent_b.build_doc_summary 等）——沙盒和正式运行
用的是同一份"怎么把病例数据变成 prompt 输入"的代码，不是另外临摹一份、
容易跑出和生产不一样的结果。
"""
import json

from sqlalchemy.orm import Session

from app.core.storage import get_object_bytes
from app.db.models.case import Case
from app.services.llm_client import run_structured
from app.services.pipeline.agent_b import build_doc_summary
from app.services.pipeline.agent_c import build_persona_context
from app.services.pipeline.agent_d import real_gap_stages
from app.services.pipeline.agent_f import build_context
from app.services.pipeline.common import PipelineError
from app.services.settings_service import get_llm_provider


async def run_sandbox(db: Session, case: Case, agent_code: str, prompt_text: str, out_schema: dict | None) -> dict:
    schema = out_schema or {}
    # 沙盒要预览"真跑起来会是什么样"，所以跟正式运行用同一个当前生效的
    # 模型后端，不是单独一个开关——不然编辑器里试跑通过了，发布后用另一个
    # 模型跑又不一样，沙盒就白测了。
    provider = get_llm_provider(db)

    if agent_code == "A":
        if not case.documents:
            raise PipelineError("这个病例还没有上传单据，无法用于 A 的沙盒试跑")
        docs = sorted(case.documents, key=lambda d: d.seq)
        images = [(get_object_bytes(d.source_file), d.content_type or "image/jpeg") for d in docs]
        user_text = f"请按顺序处理这 {len(images)} 份病历图片（seq 1..{len(images)}），输出 documents 与 review_flags。"
        return await run_structured(system_prompt=prompt_text, schema=schema, user_text=user_text, images=images, provider=provider)

    if agent_code == "B":
        if not case.documents:
            raise PipelineError("这个病例还没有抽取出单据，无法用于 B 的沙盒试跑")
        user_text = (
            "以下是这位患者按 seq 排列的结构化病历时间线（JSON 数组），"
            "请输出每份病历所属的 J01–J06 阶段：\n\n" + json.dumps(build_doc_summary(case), ensure_ascii=False, indent=2)
        )
        return await run_structured(system_prompt=prompt_text, schema=schema, user_text=user_text, provider=provider)

    if agent_code == "C":
        if not case.documents:
            raise PipelineError("这个病例还没有抽取出单据，无法用于 C 的沙盒试跑")
        user_text = "以下是这位患者的全部结构化病历（JSON 数组），请输出患者画像：\n\n" + json.dumps(
            build_persona_context(case), ensure_ascii=False, indent=2
        )
        return await run_structured(system_prompt=prompt_text, schema=schema, user_text=user_text, provider=provider)

    if agent_code == "D":
        if not case.stage_map:
            raise PipelineError("这个病例还没有做阶段映射，无法用于 D 的沙盒试跑（先在正式流程里跑一次 Agent B）")
        gaps = real_gap_stages(case)
        if not gaps:
            return {"mock_entries": [], "_sandbox_note": "这个病例没有 real_gap 阶段——正式运行时 D 会跳过 LLM 调用直接返回空数组，这里同理不发请求"}
        user_text = (
            "以下是需要补丁的 real_gap 阶段（JSON 数组，只含这些，不含 uncovered 阶段——"
            "不要为列表之外的任何阶段编造内容）：\n\n"
            + json.dumps([{"stage_code": s.stage_code, "reason": s.reason} for s in gaps], ensure_ascii=False, indent=2)
        )
        return await run_structured(system_prompt=prompt_text, schema=schema, user_text=user_text, provider=provider)

    if agent_code == "F":
        if not case.stage_map or not case.persona_fields:
            raise PipelineError("这个病例还没有阶段映射或组合画像，无法用于 F 的沙盒试跑（先在正式流程里跑一次 Agent B/C）")
        context = build_context(db, case)
        user_text = (
            "以下是这位患者的旅程表、画像、推测补丁、标准场景库与通用红线目录（JSON），"
            "请生成裂点与测试 query：\n\n" + json.dumps(context, ensure_ascii=False, indent=2)
        )
        return await run_structured(system_prompt=prompt_text, schema=schema, user_text=user_text, provider=provider)

    raise PipelineError(f"未知 agent_code：{agent_code}")
