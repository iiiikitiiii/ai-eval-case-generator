"""Third export format alongside JSON/Excel — a self-contained package,
one folder per test case, with the actual image files (not seq references)
and the full standard card (not just a has_standard_card flag), plus a root-
level 测试用例总览.xlsx (identical content to the standalone Excel export) so
a recipient never has to come back to the app for either the overview table
or the per-case detail — this is for handing directly to whoever runs the
test, not for reading in the app.
"""
import time
import zipfile
from io import BytesIO

from sqlalchemy.orm import Session

from app.core.storage import get_object_bytes
from app.db.models.agent import ScenarioType
from app.db.models.case import Case, Cutpoint, Query
from app.db.models.standard import EvalCriterion, StandardCard, StandardCardCriterion
from app.services.case_service import build_query_export_dict
from app.services.export_xlsx import build_test_case_workbook

_TIERS = ["A", "B", "C", "D", "E"]


def _write(zf: zipfile.ZipFile, name: str, data: str | bytes) -> None:
    """zf.writestr(str, data) does NOT set the UTF-8 filename flag by
    default (verified empirically — Python just leaves flag_bits at 0),
    so any reader that doesn't guess UTF-8 on its own (macOS's `unzip -l`,
    older Windows tools) renders every 中文 folder/file name as mojibake.
    Every path in this archive is Chinese (case_no is the only ASCII bit),
    so this isn't an edge case to shrug off — set the flag explicitly on
    every entry."""
    zi = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.flag_bits |= 0x800  # language encoding flag: filename/comment are UTF-8
    payload = data.encode("utf-8") if isinstance(data, str) else data
    zf.writestr(zi, payload)


def _format_turns(turns: list[dict]) -> str:
    """Rn 格式——业务方自己那份 811 xlsx「已设计测试用例」sheet 里
    "R1（图片发送后连续发送）：\\n消息1\\n消息2" 的写法，不是我们发明的
    "第N轮"措辞，跑测方看着才是熟悉的格式。"""
    blocks = []
    for t in turns:
        note = f"（{t['note']}）" if t.get("note") else ""
        header = f"R{t.get('round')}{note}："
        messages = t.get("messages") or []
        blocks.append(header + "\n" + "\n".join(messages))
    return "\n\n".join(blocks)


def _query_markdown(case: Case, cp: Cutpoint, q: Query, scenario_name: str | None) -> str:
    lines = [
        f"# {case.case_no} · {q.scenario_type}" + (f" {scenario_name}" if scenario_name else ""),
        "",
        f"- 旅程阶段：{cp.stage_code}",
        f"- 来源：{'真实证据' if cp.provenance == 'real' else '推测数据'}",
        f"- 测试方向：{q.test_direction or q.text}",
        "",
        "## 测试背景（仅供评分参考，绝不发给被测产品）",
        q.test_background or "（这条用例没有单独的测试背景，query 本身即全部内容——见下方 query.text 或画像脚本）",
    ]
    if q.test_image_note:
        lines += ["", "## 图片说明", q.test_image_note]
    lines += ["", "## 预期答题要点"]
    lines += [f"- {p}" for p in q.expected_answer_points] or ["（无）"]
    lines += ["", "## 红线关注点"]
    lines += [f"- {p}" for p in q.red_line_watch] or ["（无）"]

    variants = q.variants
    if variants:
        lines += ["", "## 画像脚本"]
        for v in variants:
            picked = "（已选用）" if v.selected else ""
            lines += [
                "",
                f"### {v.persona_name or v.persona_code}{picked}",
                v.persona_note or "",
                "",
                _format_turns(v.turns),
                "",
                f"行为逻辑：{v.behavior_logic}",
            ]
    else:
        # 早期版本（多轮画像脚本上线前）生成的用例只有 query.text 这一句话。
        lines += ["", "## Query 原文", q.text]

    return "\n".join(lines)


def _standard_card_markdown(card: StandardCard, criteria: list[StandardCardCriterion], criterion_names: dict[str, str]) -> str:
    lines = [
        "# 标准卡",
        "",
        "## 患者需求",
        card.patient_need or "（无）",
        "",
        "## 评价目的",
        card.evaluation_purpose or "（无）",
        "",
        "## 观察条件",
        card.observation_conditions or "（无）",
        "",
        "## 什么是对的",
    ]
    lines += [f"- {p}" for p in card.whats_right] or ["（无）"]
    lines += ["", "## 什么是不对的"]
    lines += [f"- {p}" for p in card.whats_wrong] or ["（无）"]
    if criteria:
        lines += ["", "## 分档评分标准"]
        for c in criteria:
            lines.append(f"\n### {criterion_names.get(c.criterion_code, c.criterion_code)}（{c.criterion_code}）")
            for tier in _TIERS:
                if tier in c.tiers:
                    lines.append(f"- **{tier}**：{c.tiers[tier]}")
    return "\n".join(lines)


def build_test_case_zip(db: Session, rows: list[tuple[Query, Cutpoint, Case]]) -> bytes:
    scenario_names = {s.code: s.name for s in db.query(ScenarioType).all()}
    scenario_ids = {s.code: s.id for s in db.query(ScenarioType).all()}
    criterion_names: dict[str, str] | None = None
    card_markdown_cache: dict[str, str | None] = {}  # scenario_type code -> markdown, or None if no card

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        seq_in_case: dict[str, int] = {}
        for q, cp, case in rows:
            seq_in_case[case.case_no] = seq_in_case.get(case.case_no, 0) + 1
            n = seq_in_case[case.case_no]
            folder = f"{case.case_no}/用例{n:02d}_{q.scenario_type}"

            _write(zf, f"{folder}/query.md", _query_markdown(case, cp, q, scenario_names.get(q.scenario_type)))

            doc_by_seq = {d.seq: d for d in case.documents}
            for seq in q.test_image_seqs:
                doc = doc_by_seq.get(seq)
                if not doc or not doc.source_file:
                    continue
                try:
                    data = get_object_bytes(doc.source_file)
                except Exception:  # noqa: BLE001 — 一张图取不到不该让整个压缩包失败
                    continue
                ext = (doc.content_type or "image/jpeg").split("/")[-1]
                _write(zf, f"{folder}/images/DOC-{seq:02d}.{ext}", data)

            if q.has_standard_card and q.scenario_type not in card_markdown_cache:
                scenario_id = scenario_ids.get(q.scenario_type)
                card = db.query(StandardCard).filter(StandardCard.scenario_type_id == scenario_id).first() if scenario_id else None
                if card:
                    if criterion_names is None:
                        criterion_names = {c.code: c.name for c in db.query(EvalCriterion).all()}
                    criteria = db.query(StandardCardCriterion).filter(StandardCardCriterion.standard_card_id == card.id).all()
                    card_markdown_cache[q.scenario_type] = _standard_card_markdown(card, criteria, criterion_names)
                else:
                    card_markdown_cache[q.scenario_type] = None

            card_md = card_markdown_cache.get(q.scenario_type)
            if card_md:
                _write(zf, f"{folder}/standard_card.md", card_md)

        # 压缩包根目录再放一份汇总 Excel——跟「导出 Excel」按钮生成的是
        # 完全同一份数据（同一个 build_query_export_dict/build_test_case_workbook），
        # 不是简化版摘要。收件人不用先靠文件夹名字数用例、要看总览时也不用
        # 再回来这个页面单独点一次「导出 Excel」，一个压缩包里两种形态都有。
        test_cases = [build_query_export_dict(case, cp, q, scenario_names.get(q.scenario_type)) for q, cp, case in rows]
        _write(zf, "测试用例总览.xlsx", build_test_case_workbook(test_cases))

    return buf.getvalue()
