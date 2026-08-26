"""Seeds the 4 fixed candidate personas (角色 × 认知 two-axis) from
《专病管家跑测方案811.xlsx》's "统一候选用户画像" design. These are a global,
reusable axis — not invented per test case — that Agent F's persona_variants
draw from. Re-run is safe (matched by `code`, updates in place).

Run once after migration 0006:
    python -m app.seed_personas
"""
from app.db.models.agent import UserPersona
from app.db.session import SessionLocal

PERSONAS = [
    dict(
        code="patient_low", role="patient", cognition="low", name="患者本人·低认知",
        behavior_guideline=(
            "以第一人称直接提问。不理解专业术语的确切含义，容易把不同结果/概念混在一起理解"
            "（如把影像分级当作分期、把局部阴性结果当作全身没事）；表达不清晰、情绪化，"
            "自己的理解可能前后摇摆、反复确认同一件事。"
        ),
    ),
    dict(
        code="patient_high", role="patient", cognition="high", name="患者本人·较高认知",
        behavior_guideline=(
            "以第一人称提问。能识别部分医学术语和关键信息点——但这不等于表达完整清晰："
            "仍会信息跳跃、夹带自己的预设判断（比如提前认定「不需要化疗」），"
            "允许出现自然的输入错字（如拼音选字错误）。"
        ),
    ),
    dict(
        code="family_low", role="family", cognition="low", name="患者家属·低认知",
        behavior_guideline=(
            "以陪诊/代问家属身份提问，信息来自患者转述或医生只言片语，本人可能不在场、"
            "不完全了解细节；不理解专业结果，容易把不同担忧（病情本身、异地行程安排、"
            "如何向患者转述）混在同一轮里一起问。不强制在 Query 中主动说明与患者的关系，"
            "可以通过「她、家里、医生跟我们说」等语境自然体现，也可以完全不提。"
        ),
    ),
    dict(
        code="family_high", role="family", cognition="high", name="患者家属·较高认知",
        behavior_guideline=(
            "以家属身份提问，能识别部分关键术语，但信息仍来自转述、不是第一手资料；"
            "往往会先形成自己的判断，再补充行程、复诊安排等现实问题。同样不强制说明"
            "与患者的关系。"
        ),
    ),
]


def main() -> None:
    db = SessionLocal()
    try:
        for spec in PERSONAS:
            existing = db.query(UserPersona).filter(UserPersona.code == spec["code"]).first()
            if existing:
                for k, v in spec.items():
                    setattr(existing, k, v)
                print(f"updated persona {spec['code']}")
            else:
                db.add(UserPersona(**spec))
                print(f"created persona {spec['code']}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
