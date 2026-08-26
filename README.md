# 病例流水线中枢

病例工坊（单病例人工复核）· Prompt 维护后台（流水线版本管理）· 用例总览看板（跨病例聚合）
三页共用一套数据模型，见 `doc/`（架构设计草案）。当前状态：**阶段 0/1/2/4 完成，阶段 3 完成，
阶段 5 的异步队列完成**（阶段 5 剩下的审计日志落地/合规存储按范围暂不做）——六个 Agent 全部
接入，六步向导走完整条链路且**全部异步化**（点按钮立刻返回，实际执行在 `arq` worker 里跑，
不再卡住 HTTP 请求）；Prompt 后台能建草稿、发布、回滚、**沙盒试跑**（拿草稿内容对真实病例预览，
不用先发布）、**回归测试**（金标准病例 + 机械断言，发布前门禁）；用例看板能看跨病例的病例
进度、用例库、覆盖矩阵、质量信号。

## 目录结构

```
backend/    FastAPI + SQLAlchemy + Alembic，六个 Agent（S0/A/B/C/D/F）的编排与病例数据
frontend/   React + TypeScript + Vite，/workshop /prompts /board 三个路由
infra/      docker-compose：postgres · redis · minio · backend · worker · frontend
```

内部部署（公司内网服务器，不是本地开发）看 `doc/内部部署指南.md`——生产用的
`infra/docker-compose.prod.yml`/`backend/Dockerfile.prod`/`frontend/Dockerfile.prod`
是单独维护的一套，不要跟下面这节"本地开发"用的配置搞混。

## 快速开始（全容器化，推荐）

```bash
cd infra
cp .env.example .env        # 按需修改，至少确认 JWT_SECRET；要跑 Agent A 就填 MINIMAX_API_KEY
docker compose up --build
```

启动后：
- 后端 API：http://localhost:8000/docs
- 前端：http://localhost:5173
- MinIO 控制台：http://localhost:9001（caseflow / caseflow-secret）

首次启动后创建一个登录账号、并把六个 Agent 的初始 prompt 种进数据库（容器内各执行一次即可）：

```bash
docker compose exec backend python -m app.seed \
  --email you@hospital.example --name "你的名字" --password "change-me" --role admin
docker compose exec backend python -m app.seed_agents
```

`seed_agents` 会把 A/B/C/D/F 全部标记为 `published`（S0 是 `draft`——它不调用模型，只是
让场景库在版本列表里可见）。用刚才建的账号登录前端。`admin` 角色能看到全部三个页面；
日常账号建议按角色分配 `reviewer`（病例工坊）/ `engineer`（Prompt 后台）/ `manager`（看板）。

## 本地开发（不进容器，更快的热重载）

只用 docker 起基础设施，后端/前端在宿主机跑：

```bash
cd infra && cp .env.example .env && docker compose up postgres redis minio

# 另开一个终端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # 已经指向 localhost:5432 等
alembic upgrade head
python -m app.seed --email you@hospital.example --name "你的名字" --password "change-me" --role admin
python -m app.seed_agents
uvicorn app.main:app --reload

# 再开一个终端
cd frontend
npm install
npm run dev
```

## 完全不用 docker（Homebrew 原生，这台机器就是这么跑的）

```bash
brew install postgresql@16 redis minio/stable/minio python@3.12
brew services start postgresql@16
brew services start redis
createuser -s caseflow -P    # 密码设成和 backend/.env.example 里的 DATABASE_URL 一致，或自己改那行
createdb -O caseflow caseflow

minio server ~/minio-data --console-address ":9001" &   # MINIO_ROOT_USER/PASSWORD 环境变量按需设

cd backend
/opt/homebrew/bin/python3.12 -m venv .venv   # 别用系统自带 python3——版本可能低于 3.10，本项目用了 `X | None` 语法
./.venv/bin/pip install -r requirements.txt
cp .env.example .env    # 填 MINIMAX_API_KEY
./.venv/bin/alembic upgrade head
./.venv/bin/python -m app.seed --email you@example.com --name "你的名字" --password "..." --role admin
./.venv/bin/python -m app.seed_agents
./.venv/bin/uvicorn app.main:app --reload &

cd ../frontend && npm install && npm run dev &
```

**两个在这台机器上真实遇到过的坑，遇到了不用再debug一遍：**

- Homebrew 的 Redis 默认配置文件里带了几行 `loadmodule`（redisbloom/redisearch 等），
  但对应 `.so` 文件不存在，Redis 会直接拒绝启动。把 `/opt/homebrew/etc/redis.conf` 里那几行
  `loadmodule` 注释掉。
- `passlib` 和新版 `bcrypt`（≥4.1）不兼容，建账号时哈希密码会报
  `password cannot be longer than 72 bytes` 这种文不对题的错——已经在 `requirements.txt` 里把
  `bcrypt` 锁定到 `4.0.1`，正常 `pip install -r requirements.txt` 不会再踩到。

## 验证过什么

后端 `pytest tests/ -q`、`alembic upgrade head --sql`（离线 DDL 校验，0001~0003 三版）、前端
`npx tsc --noEmit` / `npm run build`——这些不需要真实服务也能过，不是这次验证的重点。

**真正的验证是一次完整的活链路**：本机 Homebrew 起 Postgres/Redis/MinIO → 建病例、传两张
合成但结构真实的病历图片（CT 报告 + 病理报告，故意在两份之间埋了一个年龄矛盾）→
**A** 正确 OCR 中文全文、抽出结构化字段、抓出年龄矛盾生成核对冲突 → 人工确认 → **B** 正确把
两份病历映射到 J02/J04，并推断出 J03（穿刺活检）是真实发生过但未被记录的缺口 → **C** 正确
组合出患者画像，年龄字段带 inconsistent 标记 → **D** 只为 J03 这个 real_gap 阶段生成了 1 条
推测记录，**没有**为 J05–J08 那些尚未发生的阶段编造任何内容（这正是要落地的那条边界约束）→
**F** 生成 8 条裂点用例，query 的语气、边界坦诚度、红线约束都合格，且完全没有编造 C3/C4/C5
这类需要未来数据支撑的裂点类型 → 人工纳入 → 导出。全程记录在运行记录页里，测试数据事后已清除。

**过程中真实遇到并修复的问题**（不是假设，是这次跑出来的）：

- MiniMax 的结构化输出偶尔漏必填字段（如 `severity`）导致 `KeyError` 崩溃——五个 Agent 的
  runner 现在统一用 `require_fields()` 校验后再落库，核心字段缺失就明确报错，非核心字段缺失
  就给合理默认值，不再是一个裸 `KeyError` 崩到 500。
- 默认 `max_tokens=16000` 对 Agent F 这种重上下文任务不够，`thinking` 用掉大半预算导致响应
  在拼完整参数前被截断——调到 65536，并在 `llm_client.py` 里加了 `finish_reason=="length"` 的
  专门诊断信息，下次再截断能立刻看出原因而不是一头雾水。

LLM 提供方默认是 MiniMax（`LLM_PROVIDER=minimax`），代码里也保留了 Anthropic 后端
（`llm_provider=anthropic`），两者共享同一个 `run_structured()` 接口，切换只改一个环境变量，
agent 代码不用动。MiniMax 的 `/chat/completions` 没有 `tool_choice` 可以强制调用工具（和
OpenAI/Anthropic 不同，模型自己决定要不要调用），这一点已经在 prompt 里用系统指令 + 内容兜底
解析双重保险处理，见 `backend/app/services/llm_client.py` 顶部注释。

## 运行日志在哪

本机原生跑（当前这台机器的状态）：

| 服务 | 日志路径 |
|---|---|
| 后端 FastAPI | `.local/backend.log` |
| arq worker（真正跑 Agent 的地方，异步化之后） | `.local/worker.log` |
| 前端 Vite | `.local/frontend.log` |
| MinIO | `.local/minio.log` |
| Postgres | `/opt/homebrew/var/log/postgresql@16.log` |
| Redis | `/opt/homebrew/var/log/redis.log` |

应用层面更常用的是**运行记录页**（病例详情页右上角"运行记录"链接，或 `GET /cases/{id}/pipeline/runs`）——
每次 Agent 调用的状态、用时、prompt 版本、失败原因都在这里，比翻 uvicorn 日志定位问题快得多。
Docker 化部署时改用 `docker compose logs -f <service>`。

## 下一步（阶段路线图）

| 阶段 | 内容 |
|---|---|
| ~~0~~ | ~~仓库脚手架、docker-compose、DB迁移、登录鉴权、三个前端路由空壳~~ ✅ |
| ~~1~~ | ~~病例 CRUD · 上传单据 · Agent A 真实调用 · 核对冲突 UI + 服务端关卡~~ ✅ |
| ~~2~~ | ~~B/C/D/F 全部接入并真实验证 · 运行记录（trace）页 · 全部步骤的服务端关卡~~ ✅ |
| ~~3~~ | ~~Prompt 版本管理 · 编辑器 · 场景库管理界面 · 沙盒试跑 · 回归测试~~ ✅ |
| ~~4~~ | ~~看板聚合接口 · 病例看板 / 用例库 / 覆盖矩阵 / 质量信号 UI~~ ✅ |
| 5（部分） | ~~`arq` 异步任务队列~~ ✅ · **按范围暂不做：审计日志落地使用、为合规收紧存储/日志脱敏** |
| 6 | ~~用户画像库 · 裂点用例改为多轮 + 行为逻辑脚本 · 用例导出含真实 query/图片 · 推测抽查可跳过 · 单据导入图片预览/缩略图~~ ✅ |
| 7 | ~~画像库维护 UI · 触发 F 时可选画像子集 · 用例导出 Excel/JSON（单病例 + 看板批量）· Agent 运行的乐观进度条~~ ✅ |
| 8 | ~~LLM 模型可在页面上切换（MiniMax / Kimi K3），运行时生效、不用重启~~ ✅ |
| 9 | ~~worker 并发上限对齐供应商限速 · 运行记录自动轮询 + 实时进度 · 用例库/看板批量导出 · 覆盖矩阵转置+裂点类型标注 · 运行中实时显示模型推理过程（流式）~~ ✅ |
| 10 | ~~真实 token 用量统计（看板）· 去掉发明出来的 C1-C6 裂点分类，改用业务方真实六阶段旅程模型重设计 Agent B/F · worker 超时不再卡死运行记录~~ ✅ |
| 11 | ~~全流程病历图片可点击查看大图（灯箱）· 用例库点一行看完整用例（不再只是截断的表格摘要）~~ ✅ |
| 12 | ~~用例库/看板批量导出新增压缩包格式（真实图片文件 + 标准卡 + 多轮画像脚本）· 修复用例库加载失败（schema 回归）· 老格式用例的 query 原文不再被漏渲染~~ ✅ |
| 13（第一阶段） | ~~《交互体验优化需求》第一阶段：产出页改为可读用例预览 · 审计日志基础设施（写入/查询/展示）落地使用 · 发布门禁强门禁+明确例外 · 模型切换审计与二次确认 · B/C 局部重试~~ ✅ |
| 14（第二阶段） | ~~病例检索（编号/别名/诊断）与状态筛选、队列"当前待办" · 用例库批量审核（业务语言 + 批量纳入/不纳入 + 可选原因）· 导入阶段单据删除与重编号 · 顺带补上 Agent F 的场景选择（跟已有的画像选择同一个模式）~~ ✅ |
| 15 | ~~压缩包导出补一份汇总 Excel · Agent 统一架构改造方案阶段 0：A/B/C/D/F 五个 agent 的回归测试护栏（43 个新测试）~~ ✅ |
| 16 | ~~Agent 统一架构改造方案阶段 1：`UnifiedAgentRunner` + `AgentSpec` 框架落地，迁移 Agent C（特性开关默认关闭，旧路径仍是默认）~~ ✅ |
| 17 | ~~Agent 统一架构改造方案阶段 2：迁移 Agent A（图片输入 + 文档数量一一对应校验）~~ ✅ |
| 18 | ~~真实 bug：Agent F 场景选择从上线起就没在 worker 里生效过（进程 15 小时没重启），已定位并重启修复；顺带完成阶段 3（迁移 B）、阶段 4（迁移 D、F）、五个 agent 的统一横向验收~~ ✅ |
| 19 | ~~清理受 F 场景选择 bug 影响的 6 条历史用例（批量不纳入 + 审计留痕）· 真实 LLM 端到端验证全部 5 个统一 runner（真实病例、真实图片、真实 token 消耗，验证完删除）· Agent 统一架构改造方案阶段 5：删除 A/B/C/D/F 的旧手写实现和迁移特性开关，五个 agent 现在只有一套实现~~ ✅ |
| 20 | ~~内部部署打包：生产级 Dockerfile（多阶段构建、非 root、nginx 反代静态前端）+ `docker-compose.prod.yml`（数据库/队列/对象存储不对外暴露端口）+ 部署指南，整套流程真实跑通验证过（build → 迁移 → 种子数据 → 真实登录 → 真实取数据）；顺手补上 `.dockerignore`（原来会把 .env 真实密钥和 148MB 的 .venv 都打进构建上下文）和 `.gitignore` 缺口（backend/.env 之前完全没被排除）~~ ✅ |

Prompt 后台已经真实验证过完整的版本工作流：新建草稿 → 发布 → 再发布一个旧版本做回滚，
`agents.published_version_label` 全程正确跟着变。**Agent A 的 v2（1:1 数量约束那次修复）就是
用这套机制真实发布的**，不是补测出来的样例。场景库的增删改也验证过。沙盒试跑（编辑后立刻拿
一个真实病例的单据跑一次预览）和回归测试（金标准病例 + 断言，发布前门禁）还没做——这两个是
阶段 3 剩下最有价值的部分，之前调 Agent A/B 时反复出现的"改了 prompt 却不知道会不会更好/更坏"
正是它们要解决的问题。

用例看板四个视图都用真实病例数据验证过（`GET /board/cases`、`/board/testcases`、`/board/coverage`、
`/board/quality`）：病例看板正确按六步分列、覆盖矩阵正确统计出裂点类型×场景类型的真实分布、
质量信号正确算出核对冲突/推测通过率/Pipeline 失败率。覆盖矩阵和产能公式（`用例数 = Σ(裂点 ×
适用场景数)`）现在是同一份数据，不是分别维护的两套口径。

## 场景库已经是业务方的真实数据，不是占位示例

`doc/专病管家测评标准-场景清单+标准.xlsx` 落地了（`app/import_scenario_standards.py`，
幂等、可重跑）：

- **场景库**从 7 条占位示例换成 **49 条真实场景**，精确覆盖 J01–J08，每条带场景来源
  （医学覆盖补充/实际客户咨询）和真实咨询量（如"初始治疗方案选择"一条就有 162 次真实咨询）。
- **20 项评分标准**（`eval_criteria`）：医学专业能力 40% / 沟通能力 20% / 人文关怀能力 10% /
  模型与系统能力 30%，四类权重对应的满分（40/20/10/30）已用真实数据自校验过，加总正好 100。
- **11 条案例级通用红线**（`red_lines`）+ **7 条法规依据**（`legal_basis_refs`，
  《生成式人工智能服务管理暂行办法》《个人信息保护法》《医师法》、WHO AI 伦理指南等）——
  Agent F 现在从这 11 条里选 `red_line_watch`，不再自己发明"A1/A3"这类临时标签。
- **标准卡**（`standard_cards` / `standard_card_criteria`）：49 个场景目前只有 1 个有完整评分卡
  （J04"综合多项检查结果了解病情"，20 项标准各自的 A~E 五档场景化描述都在）。**这是模板，不是
  完成度**——F 对没有卡的场景照常生成 query，但会在 `queries.has_standard_card` 上如实标注，
  看板和导出能区分"这条用例有严谨评分依据"和"这条是模型自由生成的"。

Agent F 已经用这套新数据发版（v2）并在真实病例上重跑验证过：10 条裂点全部生成，
`scenario_type` 全部是真实场景 code（SCN04/SCN07/SCN11...），`has_standard_card` 精确只在
SCN14（唯一有标准卡的场景）上为 true，`red_line_watch` 全部是"{seq} {name}"格式、能在 11 条
目录里查到对应项，而且选得上下文相关（比如"可疑症状的风险与就医紧急程度"这条选中的是
"未识别明确急重症或危险信号"，不是随便挑的）。

## 异步队列：点按钮不再卡住

之前每个 run-X 接口是同步阻塞的——发个请求，后端在这个请求里干等 LLM 返回，F 实测卡过 4 分钟。
现在改造成：

1. `POST /cases/{id}/pipeline/run-x` 建一条 `status=queued` 的 `PipelineRun`，扔进 `arq`
   队列，**立刻**返回（实测 0.01s，不是"变快了"，是"这步压根不在请求里做了"）。
2. `arq` worker（独立进程，`app/workers/worker.py`）捞到任务才真正调用对应的 `run_agent_x`。
3. 前端拿到 `queued` 状态后轮询 `GET /cases/{id}/pipeline/runs`，看到 `succeeded`/`failed`
   才刷新界面，中途显示"运行中，已等待 Ns"，可以离开页面。
4. 双击/重复提交有幂等保护——同一病例同一 agent 已经在 `queued`/`running`，第二次点击拿回
   同一个 run，不会真的起两个任务抢着写同一批数据。

**真实跑通过完整链路**（A→B→C→D→F 全部走异步）：上传病历 → 每一步 enqueue 都在 0.01s 内
返回 → worker 异步执行 → 轮询到终态。过程中 B 第一次输出没覆盖全部 8 个阶段，被服务端校验
逮到、清楚报错、病例安全 blocked；**重试**（还是异步）第二次就过了——这正是这套机制该有的
行为：模型偶发失误不会造成脏数据或卡死，只是需要人工点一次重试。

## Prompt 后台补完：沙盒试跑 + 回归测试

- **沙盒试跑**（`POST /agents/{code}/sandbox`）：编辑器里的草稿文本，不用先存成版本，直接对
  一个真实病例的真实数据跑一次，只返回原始结果，不写数据库。跟正式 runner 共用同一套"病例数据
  怎么变成 prompt 输入"的构造逻辑（`agent_b.build_doc_summary` 等直接复用，不是另外临摹一份），
  保证沙盒看到的和发布后线上真跑的是同一个输入形状。
- **回归测试**（`regression_cases` / `regression_runs`，阶段 0 就建好但一直没用起来的表，
  这次真正接上了）：金标准病例 + 机械断言（`count_eq`/`count_gte`/`field_eq`/`field_contains`），
  跑的时候拿目标版本的 prompt 通过沙盒对金标准病例执行一次，再逐条判定断言。**已经用真实数据
  验证过**：拿 CASE-20260816-002（9 份真实病历照片）建了一条 Agent A 的回归用例
  ——断言"必须严格产出 9 条记录"+"必须至少发现 1 处跨病历问题"——对 A 当前发布版本
  （就是那个"1 张图 = 1 条记录"约束修复后的 v2）跑了一次，**两条断言全部通过**。

六阶段版的场景分组（`doc/` 里同一份 xlsx 的另一个 sheet，把我现在的 8 阶段合并成 6 阶段）
先没有采用——采用它意味着重新设计 Agent B 的阶段模型，是个更大的决定，先记录着。

设计背景和三页的数据闭环见对话中产出的架构说明；数据库表结构见
`backend/app/db/models/`，是当前唯一的权威来源。六个 Agent 的种子 prompt 见
`backend/app/seed_agents.py`——这是重建自两份原型设计的起草版本，已用真实 API 验证过基本可用，
现在可以直接在 Prompt 后台里继续打磨，不用再改源码重跑种子脚本了。

`doc/需求细节澄清.md` 里的两条笔记已经落地：mock 编造边界收紧到只补 real_gap（见上面的验证
记录），场景库加了 journey_stages / feature_scenario 两个维度（`scenario_types` 表，`app/seed_agents.py`
里的 `SCENARIO_TYPES`）——具体分类和产品功能场景命名是占位示例，需要业务侧在阶段 3 的场景库
管理界面里重新过一遍。

## 跑测方案落地：用户画像 · 多轮对话 · 用例真实可跑 · D 步骤可跳过 · 图片预览

`doc/专病管家跑测方案811.xlsx` 落地了当前完整的跑测设计——这之前"裂点用例"页面只产出一句话
`query.text`，跟业务方实际要跑的"一条测试用例 = 方向 + 背景 + 精确到张的图片 + 最多 4 套画像
脚本的多轮对话"差得远。这次补的是这个差距，不是另起一套：

- **用户画像库**（`user_personas` 表，`app/seed_personas.py`）：患者本人/家属 × 低/较高认知，
  4 个固定候选，每个带一段真实的行为准则（比如"患者本人·低认知"会把影像分级误当分期、把局部
  阴性当全身没事；"家属·低认知"不强制在 query 里说明与患者的关系，可以完全不提）——这是业务方
  跑测方案里"统一候选用户画像"设计的直接落地，不是我们发明的分类。
- **Agent F 从"一句话 query"改成"方向 + 背景 + 图片 + 4 套画像脚本"**（v3，`agent_f.py` +
  `seed_agents.py` 重写）：`test_direction`/`test_background` 描述这条用例测什么、`test_background`
  只给评分方看、**绝不出现在发给被测产品的 query 原文里**；`test_image_seqs` 精确到病历原始张数
  （不是"发全部图"）；`persona_variants` 是该用例在 4 个画像下各自的完整多轮脚本
  （`query_variants` 表，`turns` 是 JSONB 存的按轮次的消息数组），每套都带 `behavior_logic`
  说明这几轮问下来在考验被测产品什么（能不能顶住追问压力、能不能拆解患者的认知混淆…）。
- **推测抽查（Agent D）不再是必经步骤**：`case_service.advance_step` 里"进入裂点用例"这一关
  原来会因为存在 real_gap 阶段又没有 mock 记录而硬挡，现在去掉了这条——已生成的推测条目仍然
  必须逐条裁定，但可以完全不跑 D 直接往下走。
- **单据导入有图片预览了**：选完文件、还没点上传，先用 `URL.createObjectURL` 在本地渲染缩略图；
  已经上传的单据卡片也带缩略图——但 MinIO 从不直接对前端开放（鉴权都在后端），所以缩略图走
  `GET /cases/{id}/documents/{doc_id}/image`，前端拿到字节后自己转成 `blob:` URL，不是裸 `<img src>`
  指到后端地址。
- **导出真的带上了要发给被测产品的内容**：`GET /cases/{id}/export` 现在每条用例都带
  `test_direction`/`test_background`/`test_images`（seq + 图片类型）/`persona_variants`
  （人工选中的脚本；没选就把 4 套全带出去留给跑测方自己挑）。

**真实验证过完整链路**（不是只过了 `pytest`/`tsc`）：拿 CASE-20260816-002 的 9 张真实病历图片
建了一个新病例，跑 A（9 份单据，6 处核对问题）→ 裁定核对 → 跑 B+C（8 阶段全覆盖，J02 判定为
real_gap，3 处边界待裁定）→ 裁定边界 → **直接从"d"跳到"f"，不跑 Agent D、不建任何 mock 记录**，
服务端放行 → 跑 F v3（5 个裂点、5 条用例、20 套画像脚本，正好 5×4）。抽查生成结果：
`test_direction`/`test_background` 语义清楚且边界感对（会显式写"故意不向被测系统提供病理报告"）；
`test_image_seqs` 只引用了病例里真实存在的图片序号；4 套画像脚本的多轮对话读起来确实是同一件事
从低认知到较高认知、患者到家属四种问法，`behavior_logic` 准确描述了每套在考验什么。

过程中真实揪出一个 bug：病例详情接口 `_to_detail()` 里几个字段（`cutpoints`/`boundary_decisions`/
`mocks` 等）之前用 ORM 关系原始列表直接覆盖已经校验过的 Pydantic 字段，绕开了嵌套模型的
`from_attributes` 校验——`QueryVariant.persona_code`/`persona_name`（`persona` 关系上的 `@property`）
因此在真实接口响应里彻底消失，只有直接调用 `QueryVariantOut.model_validate()` 才看得到，是一次
真跑通全链路才暴露、光看 `pytest`/`tsc` 绝对测不出来的问题。修法是把那几行"验证完又用原始 ORM
对象覆盖回去"的赋值去掉，只保留 ORM 关系名和 schema 字段名对不上的三个（`flags`/`persona`/
`mocks`）继续显式赋值，但赋值前也过一遍对应的 `*Out.model_validate()`。修完重新跑了一遍上面
整条链路确认字段都在。测试用例和 MinIO 里的图片事后已清除。

## 画像库维护 UI · 触发 F 时选画像 · 用例导出 Excel/JSON · 运行进度条

上一轮把画像库和多轮用例落了地，但三处还留着口子：画像只能改源码种子脚本、F 每次都固定生成
全部 4 套画像脚本没得选、"导出"只是一个返回 JSON 的接口，页面上除了一段 `<pre>` 没别的。
这次把这三处补上，另外顺手修了一个体验问题：

- **画像库维护 UI**（Prompt 后台新增「用户画像库」tab，跟场景库同一个模式）：新增/停用画像、
  改行为准则，不用再碰 `app/seed_personas.py` 改完重跑。`code`/`role`/`cognition` 创建后不可改——
  改这几个字段等于换了一个画像，该新建不该编辑，Agent F 的 schema 里 `persona_code` 是枚举，
  悄悄改跑不通。
- **触发 F 时选画像子集**：病例工坊「裂点用例」步骤，运行 F 之前勾选这次要覆盖哪些画像
  （默认全选启用中的）。后端把选择存进 `pipeline_runs.input_ref`（这列建表时就有、之前一直没用上）
  随着 arq 任务一起传给 worker，`agent_f.build_context()` 只把选中的画像塞进模型看到的
  `persona_library`，且落库时只认这次真实喂给模型的画像集合——即便模型没听指令、把一个库里
  存在但没选中的 `persona_code` 编进结果里，也会被过滤掉，不会绕过人工在触发运行时做的筛选。
  F 的 prompt 也从"固定产出 4 套"改成"persona_library 给几个就产出几套"。**真实验证过**：只勾
  `patient_low`+`family_high` 跑 F，4 个裂点 × 2 个画像 = 8 套脚本，落库后逐条核对 `persona_code`
  确认只有这两个，没有另外两个画像的痕迹。
- **用例导出 Excel/JSON，单病例 + 看板批量两个入口**：
  - 病例工坊「产出」步骤新增「下载 Excel」「下载 JSON」两个按钮，`GET /cases/{id}/export?format=xlsx`
    返回真正的 `.xlsx` 文件（`app/services/export_xlsx.py`，一行 = 一条用例的一套画像脚本，
    case/裂点/query 级字段按行重复，跟业务方自己那份 811 方案 xlsx 的展开方式对齐，不是我们
    发明的新格式）。
  - 看板「病例看板」tab 新增勾选 + 批量导出（`GET /board/export?case_ids=...`，不选 = 导出全部
    病例）——单病例导出和看板批量导出共用同一个 `build_query_export_dict()`，字段形状不会跑偏。
  - 后端返回受鉴权保护，前端不能用裸 `<a href>` 拿文件（带不上 Bearer token），走
    `downloadFile()`：fetch 字节 → `blob:` URL → 隐藏 `<a download>` 触发保存，跟图片预览是
    同一个模式。**真实验证过**：单病例导出 4 条用例、看板批量导出跨 4 个病例共 45 行，`xlsx`
    用 `openpyxl` 读回来字段核对无误。
- **Agent 运行的乐观进度条**：F 实测跑到近 5 分钟，纯文字"已等待 Ns"焦虑感很重、像卡住了。
  `RunningProgress` 组件（病例工坊 + Prompt 后台沙盒试跑共用）按每个 Agent 历史观测到的真实
  耗时区间画一条条形进度——不谎称"已完成 X%"，封顶在 92%，永远留出"最后一段在收尾"的空间，
  但持续的推进 + "预计 N–Ms" 的文字比死气沉沉的秒数计时器安心得多。

顺带修了 F 的 prompt 措辞：从硬编码"四套画像都要产出"改成"persona_library 给几个就产出几套"，
连带 `checks` 列表里的断言也从"应覆盖 4 个固定画像"改成"覆盖的画像集合必须跟 persona_library
一一对应"，发布为 F v4（直接在 Prompt 后台走"新建草稿 → 发布"这套机制，不是改源码重跑种子）。

测试画像、测试病例和 MinIO 里的图片事后已清除；过程中发现一个不是我创建的病例
（`CASE-20260817-002`，`patient_meta` 为空、但完整跑过 A→B→C→F），推断是这台机器上正在跑的
前端被直接使用过——没有清理它，不是我的测试数据。

## 模型可在页面上切换：MiniMax / Kimi K3

`LLM_PROVIDER` 原来是个只在进程启动时读一次的环境变量，改一次要改 `.env` 再重启。现在顶栏
（三个页面共用同一个 `AppShell`，不是塞进某一个页面里）常驻一个 MiniMax/Kimi 切换器，工程师/
管理员可以直接点，审核员/测试经理能看到当前用的是哪个（只读）。

- **为什么要落库，不能是内存变量**：实际发起 LLM 调用的是 arq worker，跟处理这个切换请求的
  FastAPI 进程是两个独立的操作系统进程，进程内存互相看不见。所以设置存在新表 `app_settings`
  （通用 key/value，这次只用了 `llm_provider` 一行）——API 进程写这一行，worker 进程每次跑
  agent 前都重新读一次（`settings_service.get_llm_provider(db)`），不用重启任何东西就生效。
- **Kimi K3 后端**（`llm_client._run_kimi`）：OpenAI 兼容协议，直接 httpx 调用，跟 MiniMax
  那条路线一致；但 Kimi 真的支持 `tool_choice="required"`，不用像 MiniMax 那样靠 system prompt
  硬提示 + `content` 兜底解析——是选它的理由之一，见 `doc/需求细节澄清.md` 底部贴的官方文档。
  API key 已从那份笔记里移到 `backend/.env` 的 `KIMI_API_KEY`，处理方式跟当初 MiniMax 的 key
  一样（明文密钥不留在可能被提交进 git 的笔记文件里）。
- **页面上只暴露 kimi/minimax 两个选项**（`settings_service.SELECTABLE_LLM_PROVIDERS`），
  跟用户的原话对齐；anthropic 仍是代码里保留的备用后端，但这次不通过页面开关暴露。

**真实验证过**：

1. 直接调 `_run_kimi`——纯文本 schema 抽取和真实病历图片的 vision 抽取都正确返回结构化结果。
2. 通过 `PUT /settings/llm-provider` 切到 kimi，走完整异步链路（enqueue → arq worker 读设置 →
   调用 Kimi）跑一次 Agent A：39.5 秒完成，1 份单据、1 处核对问题，抽取内容跟 MiniMax 跑同一
   份病历时质量相当——比 MiniMax 同类任务常见的 80–140 秒明显快，但这是单次样本，不是严谨
   benchmark，仅供参考。
3. 传一个不存在的 provider（如 `"gpt4"`）会被 400 拒绝，不会静默落到某个默认值。

验证过程中，为了让新代码生效重启了 arq worker，误伤了一个真实用户（不是我）当时正在跑的
Agent A 任务——它被从 `running` 卡死变成了明确的 `failed`，错误信息如实说明是运维重启导致的
中断、直接重试即可，不是模型或网络问题；不是留一条查不出原因的死状态。这是本地开发环境下
worker 不支持热重载的已知代价，前面"运行日志在哪"一节也提过同类情况。

## 等待体验一次性补完：并发上限 · 实时进度 · 用例库导出 · 覆盖矩阵转置

这一轮全部围绕"等太久了、看不见在干什么"这个真实反馈来，不是各自独立的小改动：

- **worker 并发上限对齐供应商限速**（`app/workers/worker.py` 的 `max_jobs = 3`）：`arq` 自己的
  默认值是 10，明显超过 MiniMax/Kimi 账号实际允许的 3 并发——多个病例同时在跑时，原来的默认值
  会让请求量冲过供应商限速吃 429，而不是排队排得更快。这是这次真实检查后发现的确实存在的口子，
  之前没有显式配置过。
- **运行记录页不用再手动点刷新**（`TracePage.tsx`）：只要还有排队/运行中的记录就自动每 3 秒轮询，
  运行中的那一行现在跟病例工坊共用同一个 `RunningProgress` 组件——之前必须手动点「刷新」才能看到
  状态变化，运行中的行会一直停在原地不动，看着像卡住了。
- **运行中能看到模型真实在想什么**（`llm_client._stream_openai_compatible`、`PipelineRun.progress_note`、
  `common.make_progress_writer` 三处配合）：MiniMax/Kimi 调用现在都用 `stream=True`，把模型的
  `reasoning_content` 流式增量滚动写进 `PipelineRun.progress_note`（每～1.5 秒覆盖一次快照，不是
  追加，避免无限变长），病例工坊和运行记录页原本就在轮询的地方直接把这段文字显示出来——不是新建
  一条 WebSocket/SSE 传输链路，是让已有的轮询"顺便"看到流式内容。真实验证过：跑一次 Agent A，
  能在运行记录里实时看到模型读三份病历、发现跨文档字段不一致（科别不一样、检查日期先后矛盾）、
  组织最终结构化结果的完整推理过程；同一次验证里第一次运行恰好撞上 MiniMax 结构化输出的已知
  偶发问题（模型返回了 0 份记录），符合"清楚报错、直接重试"的既有设计，重试后正常通过——
  这不是流式改造引入的新 bug，两次独立的直接调用（1 份单据 / 3 份单据）都没能复现，是 MiniMax
  本就有的偶发行为。
- **用例库 tab 也能导出了**（`GET /board/export` 现在除了 `case_ids` 也接受
  `scenario_type`/`cutpoint_type`/`journey_stage`/`provenance`/`decision`，跟 `/board/testcases`
  是同一套参数）：导出内容严格对齐表格当前的筛选结果，所见即所得——期间自己发现并修正了一处
  不一致：一开始图省事让"未选 decision"在导出时悄悄默认成"只要 accept"，这跟表格本身"未选=
  accept+reject 都显示"对不上，改成了由调用方（前端）显式决定默认值：病例看板批量导出没有
  decision 选择器，走 `{decision:"accept"}`；用例库 tab 保持跟表格一致，不做隐藏收窄。
- **覆盖矩阵转置 + C1–C6 标注名字**（`BoardPage.tsx`）：原来是 6 行（裂点类型）× 49 列（场景
  类型），49 列必须横向滚动才能看全；换成 49 行 × 6 列，可读性好得多。C1–C6 之前只有代码没有
  名字，现在列头下面带上了 Agent F prompt 里的官方定义（结果已出·定性未明 / 确诊已出·分期未定 /
  方案待选 / 治疗中新症状 / 随访指标异常 / 信息本身有缺口）。

裂点类型（C1–C6）与场景类型之间的结构性对应关系（哪些组合本来就不该出现，不是"还没生成"而是
"生成不了"）目前还没有体现在矩阵里——这需要业务侧确认的规则，不是我能替业务方定的，先如实记录
这个缺口，等有真实依据了再补一版空值/灰格标注，不编一份自己猜的对应表出来。

## 真实 token 用量 · 去掉发明的 C1-C6，改用业务方真实六阶段旅程

这轮做了两件事：一件是加功能（token 用量统计），一件是纠正一个此前没意识到的设计错误
（C1-C6 裂点分类从来不是业务方给的概念）。后者是用户直接指出来的，不是自己发现的。

### Token 用量统计

`stream_options.include_usage`（MiniMax/Kimi 都支持，OpenAI 兼容协议里的标准选项）让流式响应
在最后一个 chunk 里带上真实的 `prompt_tokens`/`completion_tokens`/`total_tokens`——之前
`_stream_openai_compatible` 只解析 `choices`，这个 usage-only chunk 的 `choices` 是空数组，
不加这个请求参数、不在"没有 choices 就跳过"之前先取 usage 的话，这个字段永远拿不到。落库到
`pipeline_runs.token_usage`（新迁移 0009），看板「质量信号」tab 新增总用量 + 按 Agent/按模型
分布。运行记录页也在每条记录旁边显示这次用了多少 token。真实验证过一次完整链路（A→B→C→F）：
7 次运行全部拿到真实 usage，共 85,626 tokens，按 Agent 分布（F 24,867 / A 44,664 / B 12,575 /
C 3,520）看着就合理——A 处理 9 张图，token 最多。

### C1-C6 从来不是业务方的概念——用户当场指出，现场核实，现场改

用户看到看板上 C1-C6 的名字后问"这些你是从哪里总结出来的"。查证结果：**两份业务方 xlsx 和
`doc/*.md` 笔记里，"C1""裂点""T时点/K已知/U未知"这些词一次都没出现过**。这一整套分类是早期
某次会话写 Agent F prompt 时自己发明的草稿（`seed_agents.py` 文件头的注释其实早就写了"重建自
两份原型设计的起草版本，不是逐字复制"，但这句免责声明没有真的传达到"这是我编的，不是业务方的"
这个程度）。真正的业务方材料（`doc/专病管家测评标准-场景清单+标准.xlsx`「整合场景清单 (六阶段)」）
只有一个真实维度：Patient Journey（六阶段）× 用户场景，没有第二个分类轴。

**六阶段不是把旧 8 阶段随便合并**，是业务方真实调整过的照护路径模型——逐条比对 49 个场景在
新旧两个 sheet 里的 scenario_number 算出来的真实映射：

| 旧 8 阶段 | 新 6 阶段 | 场景数 |
|---|---|---|
| J01+J02+J03 | J01 疑诊/初筛期 | 10 |
| J04+J05 | J02 确诊后治疗方案决策期 | 10 |
| J06 | J03 初诊治疗实施期 | 10 |
| J08（主要） | J04 复发/进展/耐药后治疗方案调整 | 9 |
| J07（主要） | J05 康复随访期 | 8 |
| J07/J08 各拆出几条 | J06 姑息照护期（全新阶段） | 2 |

J06 姑息照护期是全新的——旧模型里专门讲舒缓照护/临终关怀的场景之前被塞进"治疗后恢复"或
"复发决策"里，新模型把它们单独拆出来了，不是我们凑出来的第六类。

**改了什么**：

- **场景库重新打标**：`import_scenario_standards.import_scenarios_six_stage()`（新函数，旧的
  `import_scenarios` 保留但标记弃用），按 scenario_number 匹配、原地更新 49 条 `journey_stages`。
  顺带清理了一批遗留死数据——早期占位场景（`result_interpretation` 等 7 条，`kind` 注释里
  写明"该被真实数据替换"但从没真的清理过）还在 `active=true`，混进了 Agent F 实际看到的场景库，
  这次一并停用。
- **Agent B**：`STAGE_CODES` 8→6，schema 和 prompt 重写为真实六阶段定义（B v2，已发布）。
- **Agent F**：`cutpoint_type`/C1-C6 从 schema、prompt、DB 全部移除（F v5，已发布）。
  `Cutpoint.type_code` 字段改为可为空（迁移 0010），不是删列——历史数据保留原值，新裂点不再
  写这个字段。T/K/U/J 四要素的定义留着（这是构造用例的手段，不是分类体系），去掉的只是"再扣
  一个 C1-C6 标签"这一步。
- **覆盖矩阵重新设计**：不再是"裂点类型 × 场景类型"的人造网格（本来 6×49，删掉 cutpoint_type
  之后这条轴就没有意义了），改成按六阶段分组的场景覆盖视图——49 个真实场景各自的已纳入
  真实/推测用例数，包含还是 0 的场景。这才是"空白格是下一批病例该往哪个方向找的信号"这句话
  原本想说的东西；旧版本因为轴选错了，从来没有真正做到过。
- 三处前端阶段标签（病例工坊阶段裁定页、Prompt 后台场景库表单、看板筛选器）同步换成新六阶段。

**没有改的**：已经 `exported` 的历史病例数据（`stage_map`/`Cutpoint.type_code` 等）原样保留，
没有做回填迁移——那些是已经人工审核通过、导出给下游用的真实工作成果，不该因为分类方式换代就
被覆写。看板的覆盖矩阵能正确把新旧数据放在同一个视图里，是因为它按场景类型（场景库统一维护的
真实标签）分组，不依赖 Cutpoint 自己那份历史 stage_code。

**真实验证过完整链路**：新建病例、9 张真实图片、A→B（6 阶段，正确判断 J03 治疗实施期是
real_gap——"确诊后应实施了初始治疗但时间线内无任何记录"，这是模型自己推理出来的，不是提示词
硬塞的）→ 人工裁定边界 → C →跳过 D → F（4 个裂点、4 条用例，`type_code` 全部为 `null`，
`scenario_type` 精确落在场景库里该场景真实标注的阶段上，其中一条命中 SCN14 的标准卡）→ 纳入 →
导出 → 覆盖矩阵正确聚合。测试数据事后已清除，两份真实生产病例未受影响。

### 顺带修的一个真实 bug：worker 超时会让运行记录永远卡死

验证过程中发现一条 F 的运行记录卡在 `running` 状态 9.5 小时——根因是 `arq` 用 `job_timeout`
强制取消超时任务时抛的是 `asyncio.CancelledError`，它是 `BaseException` 的子类，
`run_agent_x` 自己那层 `except Exception` 接不住，取消信号直接绕过了`finish_failed()`，
状态永远停在 `running`，前端只会一直显示"运行中"。已在 `app/workers/worker.py` 加了一层
专门捕获 `CancelledError` 的处理：明确写一条 `failed`（错误信息如实说明是超时取消，不是模型
报错），再照 asyncio 的规矩把异常重新抛出去，不吞掉。这类"进程重启/超时导致运行记录卡死"的
问题在这次开发过程中出现过好几次（本地 worker 不支持热重载是已知代价，前面"运行日志在哪"
一节提过），这次是第一次真正把根因修掉，不只是手动清理一次数据库。

## 病历图片全流程可点开看大图，用例库点一行看完整内容

之前图片只在病例工坊「导入」步骤有 44px 缩略图，其它步骤（核对冲突的 DOC-03、阶段裁定的
边界判断、裂点用例要发的图）全是纯文字引用，看不到图；看板「用例库」tab 更彻底——只有一行
被截断到 320px 宽的 query 摘要，测试方向、背景、图片、画像脚本这些实际内容完全看不到。

- **`Lightbox`**（`shared/ui/Lightbox.tsx`）：全屏图片查看器，‹/› 或方向键翻页、Esc 或点背景
  关闭，拿的是同一个鉴权接口（`GET /cases/{id}/documents/{doc_id}/image`），跟缩略图共用一套
  取图逻辑，不是另开一条路。
- **`DocThumb` 从 CaseWizardPage 挪成共享组件**，加了 `onClick`——现在点缩略图直接开灯箱，
  不再是个看不清楚的死角。
- **`DocRefLink`**：核对冲突的"涉及 DOC-03"、阶段裁定的 stage_map 单据列表、边界判断，之前
  都是纯文字，现在是可点的链接，点了直接开灯箱定位到那张图。病例工坊页头新增常驻的
  「查看病历图片（N）」入口——不管当前在哪一步，随时能把整个病例的单据当画廊翻一遍。
- **`QueryCard` 从裂点用例步骤抽成共享组件**：场景、测试方向/背景、要发的图（灯箱可点）、
  预期答题要点、红线关注点、每套画像的多轮对话，一个组件两个上下文复用——病例工坊里是可交互的
  （纳入/引用、选画像），看板用例库里传 `readOnly` 就是只读展示，两边保证展示的是同一份数据、
  同一套排版，不会因为"看板要好看点"另画一套跟实际字段对不上的卡片。
- **用例库点一行弹出详情**（`QueryDetailModal`）：懒加载完整病例（`GET /cases/{id}`），按
  `case_id`/`query_id` 找到对应的裂点和用例，用同一个 `QueryCard` 渲染，带图片灯箱。之前那行
  摘要看到的信息，现在只是个入口。

## 两个真实 bug：用例库加载失败 + 展开信息不全

- **加载失败**：`BoardTestCaseItem.cutpoint_type` 还是 `str`（必填），但 C1-C6 重设计之后新裂点
  的 `type_code` 是 `None`——只要用例库里有一条新格式的用例，FastAPI 校验响应模型时整个列表
  就直接 500，前端拿到的就是"加载失败"。改成 `str | None`，是这次修复里唯一真正的代码 bug。
- **展开信息不全**：点开发现只有阶段/来源/场景徽标和两个空的 details，没有测试方向、背景、
  图片、画像脚本——查了一下，这条用例（`CASE-20260816-002`，SCN06）是这个项目最早那批真实
  病例之一，生成于多轮画像脚本功能上线之前，数据库里 `test_direction`/`test_background`/
  `test_image_seqs`/`variants` 本来就是空的，`QueryCard` 只是如实展示了它拥有的全部内容——
  不是渲染 bug。但过程中真的发现一个疏漏：这种老格式用例唯一的实际内容——`query.text`
  （当时生成的那一句 query 原文）——`QueryCard` 从来没有渲染过它，直接漏显示了。现在按有没有
  `test_direction` 区分新旧格式：旧格式套一个「旧版格式」标签、完整显示 `query.text` 原文 +
  一行说明"为什么这条用例信息比较少、要补全需要怎么做"；新格式保持原来的方向/背景/图片/画像
  脚本渲染。两种情况现在都不会再让人怀疑是不是哪里坏了。

## 压缩包导出 + 对照业务方真实 sheet 结构

用户要求先核对导出内容是否覆盖了业务方 `专病管家跑测方案811.xlsx`「已设计测试用例」sheet 的真实
结构——查证结果：那张 sheet 是 7 列（用例｜Journey-场景及方向｜病例与测试背景｜统一候选用户
画像｜对应实际Query(R1/R2...)｜用户行为与对话逻辑｜测试时发送图片），逐列对照下来我们的数据
模型已经覆盖了全部实质内容（journey_stage+scenario+test_direction、test_background、
persona_code/name+persona_note、turns(R1/R2 多轮)、behavior_logic、test_image_seqs），
不存在结构性缺口——但导出呈现上有两处没对齐业务方的真实格式：

- **Excel 导出**：去掉了"裂点类型"列（C1-C6 已经不存在了，这一列全是空值，纯噪音）；新增
  "场景名称"列（之前只有 SCN06 这样的代码，业务方 sheet 里场景名称和编号是一起给的）；多轮
  对话格式从"第N轮：msg1 / msg2"改成业务方原本的"R1（备注）：\n msg1\n msg2"——不是我们
  发明的新写法，是对齐已有格式。
- **多轮画像脚本上线之前生成的老用例**：导出时"多轮对话"列整个是空的——这类用例只有
  `query.text` 这一句话（跟看板详情卡片是同一个疏漏），现在导出也回填了。

**新增压缩包（.zip）导出**，用户明确要求"每个用例包含标准卡、输入的图片、输入的query"：单
病例「产出」步骤和看板（病例看板批量、用例库筛选后）都新增了这个选项，跟 Excel/JSON 并列。
一个用例一个文件夹（`{病例编号}/用例01_{场景代码}/`），文件夹里是：

- `query.md`——测试方向、背景、预期答题要点、红线关注点、每套画像的完整多轮脚本（Rn 格式，
  对照业务方 sheet）；没有画像脚本的老格式用例回退到 `query.text` 原文。
- `images/DOC-XX.jpg`——**真实图片文件**，不是文件名引用，从 MinIO 现取现打包。
- `standard_card.md`（有标准卡才有）——患者需求、评价目的、观察条件、什么是对的/不对的，
  以及 20 项标准里适用项的完整 5 档（A-E）评分描述，不是只标一个"有标准卡"的布尔值。

过程中真实踩到一个 bug：Python `zipfile.writestr(str, data)` **不会**自动给文件名设置 UTF-8
标志位（验证过，`flag_bits` 就是 0）——每个用例文件夹名和文件名全是中文，不设这个标志位的话，
不主动猜编码的解压工具（`unzip -l`、老版本 Windows 资源管理器）会把所有路径显示成乱码。改成
显式构造 `ZipInfo` 并设 `flag_bits |= 0x800`，用 Python 自己的 `zipfile` 读回来验证过文件名正确
（`unzip -l` 在这台机器上仍然显示乱码，但那是这个 shell 环境本身的终端编码问题，不是压缩包
本身的问题——用 Python `zipfile.ZipFile().infolist()` 读回来的 `filename` 和 `flag_bits` 都是对的，
这是压缩包实际会不会正确解压的权威判断依据，不是终端里好不好看）。

真实验证过：看板批量导出压缩包（60 个文件条目，含图片和 1 份标准卡）、单病例压缩包导出、
Excel 新列结构和老格式用例回填，全部对着真实数据核对过内容。

## 《交互体验优化需求》第一阶段：产出预览 · 审计日志 · 发布门禁 · 模型切换审计 · B/C 局部重试

`doc/交互体验优化需求.md` 是体验团队提的一份完整需求文档（8 条 P0/P1/P2 需求）；先做了一份
逐条核实过现状代码的技术评估（`doc/交互体验优化需求-技术评估.md`），文档末尾留了 5 个需要
产品拍板的开放问题。用户逐条给出了决策，并明确要求"审计日志的实际写入、查询展示和测试一并
补齐，作为后续审核、发布、设置变更留痕的通用基础能力"——这是本阶段除产出页改造外最大的一块。

### 产出页改成可读用例预览（P1，第一优先）

之前"产出"步骤默认展示整段原始 JSON，体验人员判断一条用例合不合格必须自己在 JSON 里找。
改成默认摘要（已纳入用例总数、按旅程阶段/来源的分布徽标）+ 逐条 `QueryCard` 卡片（跟看板详情
弹窗复用同一个组件，`readOnly` 模式），原始 JSON 折进"技术详情"折叠区，不删除、只是不再是
默认视图。

### AuditLog 从建好没人用，到成为真正的审计基础设施

`audit_log` 表在最早的迁移里就建好了，但一直没有代码写过它。这次补上：

- `app/services/audit_service.py`：`write_audit()`（写入，独立 commit，不跟调用方那个更大的
  事务绑在一起——即使后续业务逻辑失败，"有人试图做过这个操作"这件事也该留下来）和
  `list_audit_log()`（按 `action` 前缀 / `entity_type` / `entity_id` 过滤，按时间倒序）。
- `AuditLog` 加了到 `User` 的 relationship 和 `actor_name` 计算属性（跟 `QueryVariant.persona_code`
  同一个既有模式），`GET /settings/audit-log` 暴露查询，`engineer` 角色可见。
- 两个真实调用方：模型切换（见下）、Prompt 发布（见下）。
- `backend/tests/test_audit_service.py`：7 个测试，覆盖写入字段完整性、`actor_name` 跟随关系、
  无 actor 的系统操作、前缀/实体类型/实体 ID 过滤、按时间倒序、`limit` 生效。用
  `backend/tests/conftest.py` 里新加的 `db_session` fixture（SAVEPOINT 包一层事务，测试结束
  整体回滚，不污染真实库）跑在真实开发库上，不是 mock。

### 发布规则："强门禁 + 明确例外"

用户的产品决策：配置了回归用例的 Agent，最近一次回归必须全通过才能发布；没配置的 Agent 允许
发布，但必须显式确认"无回归门禁发布"并留痕。落地在 `regression_service.gate_status()`（每条
`RegressionCase` 各自最新一次运行的 pass/fail，从没跑过算未通过）和 `agent_service.publish_version()`
（未配置且未确认 → 409；配置了但没全过 → 400；其余情况发布成功并写一条
`agent_version.publish` 审计记录，`after` 里带门禁状态和是否走了无门禁例外）。`RegressionRun`
新增 `triggered_by` 外键（迁移 0011）+ `triggered_by_name` 属性，版本列表接口现在附带
`regression_configured` / `regression_all_passed` / `last_regression_at` / `last_regression_by`
四个字段，对应 P0-1 验收标准"已发布版本可在 10 秒内看清其最近验证结果"。

`backend/tests/test_publish_gate.py`：11 个测试，覆盖门禁矩阵的每个格子（未配置/配置但未跑过/
全通过/部分失败/忽略停用用例）、未确认时 409、确认后成功、配置但未通过时 `confirm_no_gate`
不能绕过、审计记录内容、连续发布正确归档旧版本。真实跑过一次端到端：用 F 的 v4/v5 走了一次
"未确认 409 → 确认后 200 → 写入审计" 的完整链路（用真实 JWT，不是 mock），验证完之后把 F 的
发布状态改回了 v5（不能因为测试就把线上真实用的版本换掉）。

### 模型切换：切换前确认、切换后提示、可查历史

`AppShell.tsx` 的 `ModelSwitch` 从"点一下立刻切"改成"点一下弹确认（写清楚会影响下一次流水线
和沙盒试跑）→ 确认后才真正切换 → 切换成功给一个 3 秒的浮层提示"，旁边加一个"切换记录"按钮，
点开是最近 20 条 `setting.llm_provider` 审计记录（谁、什么时候、从哪个模型切到哪个模型）。
后端 `settings_service.set_llm_provider()` 只在值真的变化时才写审计（重复点同一个选项不产生
噪音记录）——真实验证过：切到 kimi 再切回 minimax，`GET /settings/audit-log?action_prefix=setting.`
只多了一条记录（切到 kimi 那次因为当时已经是 kimi，是空操作，没有落审计）。

### B / C 局部重试：不再绑定重跑

之前"阶段裁定"步骤只有一个合并按钮，B 和 C 一起跑；C 失败要重试就必须连 B 一起重来。后端其实
一直支持独立重试（`run_agent_b`/`run_agent_c` 是两个独立的 arq 任务，`agent_c.py` 从不触碰
`stage_map`/`boundary_decisions`），只是前端从没把这个能力露出来。现在改成：首次进入这一步、
B 和 C 都还没跑过时保留原来的合并入口（省一次点击）；只要跑过一次，就换成两行独立的
`AgentRetryRow`（各自的最近一次运行状态徽标 + 完成时间 + "查看运行详情"链接 + 独立重试按钮，
失败时把 `run.error` 直接摊在下面，不用跳到运行记录页才看得到）。

重试 C 不需要任何确认——它天然不影响 B 的既有结果。重试 B 会先弹一个确认框："将清空当前边界
裁定并重新生成"，因为 `agent_b.py` 每次重跑都无条件清空 `boundary_decisions`（这是用户明确
确认保留的既有行为，前端要做的只是在动手前把这句话说清楚，不是悄悄清空）——只有已经有阶段
结果时才需要这层确认，真正的首次运行没什么可清空的，直接跑。

用真实数据核对过：当前 7 个病例里 `CASE-20260819-001`（B: 成功→失败→失败）、
`CASE-20260817-002` 和 `CASE-20260816-002`（B: 失败→成功）都是这个改动要解决的真实场景——
过去这几次失败重试都是连着 C 一起重跑的，现在同样的情况可以只点 B 那一行。

## 《交互体验优化需求》第二阶段：病例检索与待办 · 批量审核 · 资料整理 + Agent F 场景选择

### 病例检索与待办

`cases.alias`（新迁移 0012，非唯一约束，纯团队检索标签，新建病例时可选填）+ `case_service.list_cases()`
新增 `search` 参数，按病例编号/别名/`patient_meta.dx` 做不区分大小写的子串匹配（三个字段任意命中）。
状态筛选沿用已有的 `status_filter`，前端下拉换成需求文档点名的几档业务口径（待导入/待人工裁定的
四个子步骤/运行失败/已产出），不是照搬 `CaseStatus` 枚举全部值。

"当前待办"是新加的 `case_service.todo_label()`：blocked 状态优先展示"Agent X 运行失败，需要处理"
（`last_failed_step()` 从该病例的 `PipelineRun` 里找最近一条 `failed`）；其余按 `current_step` 翻成
一句人话（"待裁定 3 项核对冲突""待裁定 2 项边界判断""待运行裂点生成"……），不需要先认识
`staging`/`cutpoint_review` 这些工程状态码。

### 用例库批量审核

之前审核按钮的中文是"纳入 / 引用"——"引用"在这里其实是"拒绝"的意思，容易被读成别的意思。
改成"纳入 / 不纳入"（`QueryCard.tsx`、看板用例库两处一起改，只读态"已引用"→"未纳入"）。用例库
表格原来直接显示 `it.decision`（字面literal "accept"/"reject"）、`it.journey_stage`（"J05"）、
`it.scenario_type`（"SCN17"）这些工程字段——现在阶段用 `JOURNEY_STAGE_LABEL` 转成"J05 · 康复
随访期"，场景用后端新回填的 `scenario_name` 转成"SCN17 · 场景名称"，决策转成"已纳入/未纳入"
徽标，code 仍然在（title 属性里），只是不再是主信息。

批量操作：新增 `PATCH /board/queries/batch-decide`（`board_service.batch_decide_queries`），
用例库表格加了勾选框（含表头"全选当前筛选结果"），选中后弹出一条操作栏——"批量纳入"直接生效，
"批量不纳入"会先展开一个可选的原因输入框（`queries.reject_reason`，新迁移 0012 加的字段，纳入
时自动清空）再确认。每次批量操作写一条 `AuditLog`（`query.batch_decide`，`after` 里带
decision/reason/受影响的 query_id 列表），影响面比单条操作大，值得留痕。

"已审核 X / 共 Y 条"的进度不是另建一个字段算出来的——`Query.decided_by` 在 Agent F 生成时是
`null`（`decision` 默认值是 `accept`，但那只是初始值，不代表人工确认过），只有人工点过纳入/
不纳入之后才会被设置，`decided_by is not null` 直接就是"这条真的被人看过"的信号，用例库表格
每一行未审核的会多显示一个"（未审核）"提示。

### 资料整理：导入阶段可以删单据了

新增 `DELETE /cases/{case_id}/documents/{document_id}`（`case_service.delete_document`）：只允许
`current_step == "up"` 时删除——过了这一步，B 的阶段映射、boundary_decisions 的 `doc_seq` 引用
都已经开始按 seq 认单据了，这时候重编号会让引用全部指向错误的资料。真实验证过这个门禁：拿一个
已经在"产出"步骤的真实病例（`CASE-20260816-002`，9 份单据）测试删除，返回 400"只能在运行
Agent A 抽取之前删除单据"，单据数量核实过没有变化。删除时真会调 MinIO 的 `remove_object`
（新增 `core/storage.delete_object`），剩余单据在同一个事务里重新连续编号（1..N，不留空洞）。
前端「导入」步骤每张单据卡片加了"删除"按钮 + 二次确认弹窗（说明会重新编号、不可恢复）。

### 顺带修的一处：Agent F 一直不能选场景

用户提的问题："agentF 裂点用例页面，理论上可以让用户选择要构建的场景吧？"——查证后发现
`agent_f.build_context()` 早就支持"只用选中的画像"（`persona_codes`），但场景库那部分一直是
无条件查全部启用中的场景，同一个页面上却从来没让用户选过要不要收窄。照着 `persona_codes`
一模一样的模式补上 `scenario_codes`：不传等于老行为（全部启用中的场景，模型自己判断哪些阶段
命中哪些场景）；传了就只把选中的塞进上下文。顺手把这条路径也做了跟画像同等级别的服务端硬化——
模型如果编出一个不在这次选中范围内的 `scenario_type`，那一行会被直接丢弃（不让它绕过人工在
触发运行时做的筛选），整条裂点如果因此一个场景都不剩就不生成空壳 cutpoint。

前端候选清单不是甩出全部 49 个场景让人选，也不是摊平成一个名字列表——用户追问"场景是和
Journey 有对应关系的，候选集应该也是和该病例的 Journey 对应吧""也需要展示出来 Journey-场景，
方便用户理解"：按这个病例 `stage_map` 里 covered/real_gap 的每个阶段分组展示适用场景（同一个
场景适用多个阶段就在每个相关分组里都出现），默认全选（跟画像默认全选同一个体验），运行按钮上
显示"N 个画像 × M 个场景"。3 个新测试（`test_agent_f_scenario_selection.py`）覆盖不传/按选择
过滤/选了不存在的 code 三种情况。

---

这一阶段全部改动跑过 `pytest tests/`（41 个测试全过，比第一阶段结束时新增 22 个）和前端
`tsc --noEmit`（无错误）；`DELETE /cases/{id}/documents/{id}` 的 400 门禁和病例检索的
`search` 参数都对着真实数据库里的病例做过 curl 验证。做完最后一次改动时确认了 arq worker
里正好有一个真实的病例（`CASE-20260816-002`）在跑 Agent F——所有涉及后端的改动都只触发了
`uvicorn --reload`（跟 arq worker 是两个独立进程），没有碰 worker 进程本身，那次运行没有被
这一阶段的任何改动打断。

## 压缩包导出补一份汇总 Excel；核实了标准卡导出本身没问题

用户反馈"压缩包没有按要求导出标准卡和测试 excel"。先查证标准卡这半句：对着真实数据跑了两条
导出路径（单病例 `/cases/{id}/export?format=zip`、看板批量 `/board/export?format=zip`），两条
路径对 `CASE-20260816-002`/`CASE-20260817-001`/`CASE-20260820-001`（这三个病例各有一条命中
SCN14 的已纳入用例）都正确生成了 `standard_card.md`，内容完整（患者需求/评价目的/观察条件/
对错示例/20 项 A-E 分档标准全部齐全）。往上查了一层：`StandardCard` 表里目前全库只有 1 行——
不是导入或导出的 bug，是业务方源表 `doc/专病管家测评标准-场景清单+标准.xlsx` 的"标准卡示例"
sheet 本身就只给了一个场景（J04·综合多项检查结果了解病情，对应 SCN14）的完整标准卡作为模板，
其余 48 个场景业务方还没有提供对应的标准卡数据——这是数据覆盖范围的问题，不是代码问题，那 1 个
真实标准卡的导出链路（agent_f 生成时打标 → 导出时查库 → 渲染成 md）本身是对的。

"测试 excel"这半句是真的缺——压缩包之前只有分文件夹的 `query.md`/`images/`/`standard_card.md`，
没有一份跟点击"导出 Excel"拿到的同等内容的总览表，翻文件夹数用例、看总览还得回到页面上单独点
一次导出。`export_zip.build_test_case_zip` 现在额外在压缩包根目录写入 `测试用例总览.xlsx`——
复用跟独立 Excel 导出完全同一份数据构造（`case_service.build_query_export_dict` +
`export_xlsx.build_test_case_workbook`），不是精简摘要版。同样踩了一遍这个项目已知的坑：UTF-8
中文文件名要显式设 `flag_bits |= 0x800`，写完用 `openpyxl` 把压缩包里的这份 xlsx 读回来验证过
表头和数据行都对得上。新增 4 个测试（`test_export_zip.py`）：根目录确实有这个文件、xlsx 能被
正常打开且内容匹配、文件名 UTF-8 flag 生效、新增的总览表不会把已有的 `standard_card.md` 挤掉。
两个下载按钮的 tooltip 也同步更新，注明"根目录另附一份汇总 Excel"。

## Agent 统一架构改造方案 · 阶段 0：先补测试护栏

用户之前问过一个架构判断题："我们的 Agent 是不是应该是一个 agent loop，执行错了能不能反思重新
修正？"——结论写进了 `doc/Agent统一架构改造方案.md`：不做开放式 agent loop（这几步的输入在运行
开始时已经完备，让模型自己规划、无限重试不会增加可验证事实，只会增加成本和越界风险），但要建
**有界修复循环 + 统一运行框架**，分阶段迁移、每阶段都保持可回滚。方案本身的阶段 0 明确写了："在
不重构前，为每个现有 Agent 建立最小回归测试：成功落库、模型漏字段、无效引用、LLM 异常、运行状态
最终收口。测试不依赖真实 LLM，使用可注入的 run_structured fake。"——这次做的就是这一步，不改动
任何 A/B/C/D/F 的现有实现，纯粹补测试。

### 43 个新测试，覆盖 A/B/C/D/F 五个 agent

`tests/pipeline_fixtures.py`（共享测试基础设施，不是测试文件本身）：`make_case`/`make_run` 构造
最小可用的 Case/PipelineRun（复用真实种子 Agent 行，只加一个新 published 版本，不碰真实数据）；
`fake_run_structured(result)`/`raising_run_structured(exc)` 是"模型返回了什么"和"LLM 调用本身
失败了"两种桩，monkeypatch 到每个 agent 模块自己的 `run_structured` 名字上（每个 agent 是
`from app.services.llm_client import run_structured` 各自 import 到自己的命名空间，桩必须打在
调用方模块上，打在 `llm_client.run_structured` 源头上不生效）。

五个文件（`test_agent_a_regression.py` 到 `test_agent_f_regression.py`）按方案阶段 0 点名的
五类各自覆盖：成功落库、模型漏字段、无效引用、LLM 异常、运行状态最终收口（不管哪种失败，run 不能
停在 `queued`/`running`）。真实发现并锁死了几个各 agent 之间不一样的行为，不是照抄一套模板：

- **A**：documents 数量跟实际上传单据数不一致——直接失败，不是"部分处理"。
- **B**：重跑幂等替换（不是累加）；boundary_decision 引用不存在的 doc seq 或非法阶段代码都直接
  失败；6 个阶段少一个都直接失败。
- **C**：`source` 里混进非整数杂质元素（`int_array()` 的既有防御）会被剔除但不致命，跟 B 的
  "越界引用直接失败"是两种不同的容错策略，都测了。
- **D**：没有 `real_gap` 阶段时**跳过 LLM 调用直接成功**（用 `called["n"] == 0` 断言真的没调用，
  不只是断言最终状态对）；模型为 `uncovered`（未来）阶段编造内容是全项目最该焊死的一条红线，专门
  测了这条会让整条裂点直接失败、一条都不落库。
- **F**：策略上跟 A/B/C 明显不同——场景越界引用、图片 seq 越界、画像代码编造，这三种"坏数据"都是
  **静默丢弃那一行，不整体失败**（run 仍然 `succeeded`，只是产出更少或者 0 个 cutpoint）。这是
  读代码时发现的真实设计差异，不是我认为"应该"统一的行为——阶段 0 的测试如实记录现状，不在这一步
  改行为；改不改、往哪个方向统一，是后面阶段要做的决定。

### 一个真实的测试基础设施坑：`session.rollback()` 和手写 SAVEPOINT recipe 不兼容

写 Agent A 的测试时，前 5 个用例全部炸在同一个地方：`ObjectDeletedError`。`db_session` fixture
（手写 `begin_nested()` + `after_transaction_end` 监听器重开 SAVEPOINT 的经典写法）是这次会话
早些时候补 AuditLog 基础设施时写的，此前十几个测试文件（AuditLog、发布门禁、批量审核……）全部
用它跑得好好的，唯独这次栽了。真正原因：`pipeline.common.finish_failed()`
每次 agent 失败都会调用 `db.rollback()`——这是前面所有测试都没走到过的代码路径（写 audit log、
批量审核这些操作只 `commit()`，从不 `rollback()`）。用一个最小复现脚本确认了：手写的 SAVEPOINT
recipe 在 `session.commit()` 下工作正常，但显式 `session.rollback()` 会把 SAVEPOINT 的记账搞乱，
连早就应该已经"提交"到外层事务的数据都被牵连着回滚掉。换成 SQLAlchemy 2.0.30+ 的
`Session(bind=connection, join_transaction_mode="create_savepoint")`（内置的、更健壮的等价实现）
后问题消失——写了一个独立探测脚本逐步验证：commit 后数据还在、mutate+rollback 后数据回到 mutate
之前的状态、外层整体 rollback 后数据从真实数据库里彻底消失，三种情况都对。`tests/conftest.py`
的 `db_session` fixture 已经切到这个新写法，之前所有测试（AuditLog、发布门禁、批量审核……）重新
跑过一遍，88 个全过，不是只测新加的这部分。

### 顺带查出并修掉两个真实的历史遗留 bug

追查"J01–J08"这个字符串时，顺手发现两处真实问题，都不是这次要做的事，但既然碰到了就顺手处理了：

1. `agent_b.py` 和 `sandbox.py` 里发给模型的 **prompt 原文**（不是注释，是真的会被发送给 LLM 的
   `user_text`）还在说"请输出每份病历所属的 J01–J08 阶段"——业务方真实旅程只有六阶段（J01–J06），
   这行字面上就在暗示模型可能存在 J07/J08，跟 `agent_b.py` 自己的 `STAGE_CODES`（`range(1, 7)`，
   六个）自相矛盾。两处都改成 J01–J06。
2. 查 Agent B 的 `oneline` 字段时发现真实数据库里还是"J01–J08"，而 `seed_agents.py` 源码里这行
   早就改成"J01–J06"了——播种脚本是"不存在才插入"，源码改了不会回头更新已经种过的行。往深挖了一层：
   `seed_agents.py` 里还有一份 7 条的 `SCENARIO_TYPES` 占位场景表（`med_safety`/`symptom_report`/
   `psych_crisis`/`info_verify` 等），这正是 `ScenarioType` 模型 docstring 里提到的"阶段 1 的 7
   条占位示例"——按文档说法早就该被业务方真实的 49 个场景取代，但从来没人真的把这 7 行从数据库删掉，
   种子脚本也一直没删这份死代码。真实查证：这 7 行确实还在库里（`scenario_number IS NULL` 精确框
   出了它们），已经被标成 `active=False`（说明之前有人发现过问题、做了停用，但没做完），
   `Query`/`StandardCard` 都没有任何一行真实数据引用它们——安全删除，不是停用。新迁移 0013 删掉这
   7 行、顺带修正 Agent B 的 `oneline`；`seed_agents.py` 里的 `SCENARIO_TYPES` 定义和播种循环也一并
   删除，不然干净环境重新播种又会把这批假数据种回来。删除前后场景库总数从 56 变成真实的 49，
   `GET /scenario-types` 现场 curl 验证过。

全部改动跑过 `pytest tests/`（88 个测试全过，其中 43 个是这次新增的）；`alembic upgrade head`
真实跑过两次迁移（0012 已在第二阶段应用，0013 是这次的场景清理），跑完确认活跃 PipelineRun 数量
没受影响、backend 健康检查正常。

## Agent 统一架构改造方案 · 阶段 1：`UnifiedAgentRunner` 框架落地，迁移 Agent C

阶段 0 只补测试、不改行为；这一步是真正开始按方案改架构，但严格只做方案里阶段 1 划定的范围：
"选择 C 作为首个迁移目标（它不读图片、不删除重建 B 的边界裁定、落库关系最简单），建立框架并迁移，
验收是 C 的 API/前端行为/生成数据/失败状态与现状兼容，外加一次可修复输出错误的自动修复测试"。
不碰 A/B/D/F，不碰任何前端代码，不碰数据库 schema。

### 新增 `app/services/pipeline/framework.py`

四个方案里定义的核心概念，照着 `doc/Agent统一架构改造方案.md` 4.1/4.3/5.1 节的形状落地：

- `AgentRequest`（`user_text` + 可选 `images`）、`ValidationIssue`（`code`/`message`/`repairable`/`path`）、
  `ValidationResult`（issue 列表 + `valid`/`has_unrepairable` 两个便利属性）、`RetryPolicy`
  （`max_network_retries`/`max_repairs`，C 用的是 2/1）、`AgentSpec`（`code` + `build_request`/
  `validate`/`persist` 三个函数 + 一个 `retry_policy`）。
- `run_with_framework(db, spec, case, run)`：真正的统一 runner。查已发布版本、标 running、调用
  `spec.build_request()` 构造输入、调 `run_structured()`、`spec.validate()` 校验、不通过就进有界
  修复循环、通过就 `spec.persist()` 落库、写 `attempt_count`/`repair_count`/`attempts`（方案 6.1
  节建议的"先塞进 output_ref，不用为调试信息急着拆新表"）、成功失败统一收口——跟每个 agent 自己的
  领域规则完全解耦，C 的 `_validate`/`_persist` 里看不到任何"该重试几次""该不该修复"这类机制性
  判断。

### 三类失败，真的分开处理，不是概念上分开

方案 5.1 节表格的三行，在 `run_with_framework` 里对应三条不同的 `except` 分支：

1. **瞬时基础设施错误**（`httpx.TransportError`/`httpx.TimeoutException`——连接失败、超时，这两类
   在 `llm_client.py` 里是原样往外抛的，没被包进 `LLMStructuredError`）：指数退避重试，不消耗修复
   次数，重试到上限还失败才算数。
2. **可修复输出错误**：两种情况共用同一条修复路径——`LLMStructuredError`（模型压根没返回可解析
   结果）和 `spec.validate()` 发现的领域校验问题（缺字段、引用了不存在的病历），都会把"上一次的
   原始输出 + 结构化错误清单"拼进新的 `user_text`（system_prompt/schema/版本不变），要求模型"只
   修复列出的问题、保留其余合法内容、不得补充原始资料里没有的事实"（方案 5.2 节原文的修复 prompt
   原则），照样有次数上限。
3. **不可修复业务错误**：没有输入素材、没有已发布版本——这些在 `spec.build_request()` 或
   `run_with_framework` 一开始就抛出 `PipelineError`，从来没进过重试循环，跟原来的行为完全一致。

### Agent C 的 `AgentSpec` 实现 + 一个真实的行为提升

`agent_c.py` 里新增 `C_SPEC`（`_build_request`/`_validate`/`_persist` 三个函数）和入口函数
`run_agent_c_unified`，原来的 `run_agent_c` **一行没动**，两条路径并存。`_validate` 照搬旧版本的
校验规则（缺字段、`source` 引用了不存在的病历 seq），但把"发现问题直接 raise"改成"收集成
`ValidationIssue` 列表返回"——这不只是重构，是真实的行为提升：旧版本一旦模型编造了一个不存在的
病历 seq，这条用例当场失败，只能人工点重试；新路径下同样的问题会先把错误清单发回给模型，给它一次
自己改对的机会，改不对才真正失败。这正是用户问的那个架构问题（"执行错了能不能反思重新修正"）在
最小范围内的真实答案。

`worker.py` 的 `_RUNNERS["C"]` 现在按 `settings.agent_c_unified_runner`（新配置项，默认 `False`）
在两条路径之间选择——不是两套并行的分发表，是同一处按开关判断，任何时刻只有一条路径真正生效。
默认关闭，符合方案 8 节"迁移版本应可通过特性开关回退，直至真实运行验证通过"；真的要切换默认值，
需要先拿真实病例跑几次新路径确认没问题，这次没有做（会真的消耗 LLM 调用、真的改动某个真实病例的
`persona_fields`，不是这一步该做的事）。

### 11 个新测试，专门测框架机制本身

`test_agent_c_unified_regression.py`——跟已有的 `test_agent_c_regression.py`（测旧 `run_agent_c`）
分工不同，这边测的是框架特有的行为，用一个新的测试桩 `sequenced_run_structured(*outcomes)`
（`pipeline_fixtures.py` 新增，每次调用弹出队列里的下一个结果，可以是正常返回也可以是异常，
用来模拟"第一次失败、第二次改好了"这种跨调用的行为变化，之前的 `fake_run_structured` 只能返回
固定值，测不了这个）：

- 新旧两条路径对同一份"模型行为良好"的输出，落库的 `PersonaField` 逐字段比对完全一致（方案要求的
  "生成数据兼容"，不是我自己认为应该一致）。
- 引用不存在的病历 seq → 触发一次修复 → 模型改对了 → 成功；同样的场景但修复后仍然错 → 失败，
  错误信息里带着"不存在的病历"这个可读描述。
- `LLMStructuredError`（模型没调用工具）→ 修复 → 成功；两次都没调用工具 → 失败。
- 瞬时网络错误（`httpx.ConnectError`/`httpx.ReadTimeout`）连续两次、第三次成功 → 成功，且
  `repair_count` 仍然是 0（网络重试不占修复配额，两者要分开计数，测试专门断言了这一点）；连续三次
  网络错误（正好打满 `max_network_retries=2`）→ 失败。
- 没有单据/没有已发布版本 → 不调用模型直接失败（沿用阶段 0 建立的"前置校验前置到 build_request，
  从不浪费一次 LLM 调用"这个习惯）。
- 运行状态最终收口——任何失败路径，run 都不会停在 `queued`/`running`。

测试里对 `asyncio.sleep` 打了桩（`autouse` fixture，全文件生效）——瞬时错误重试之间的指数退避在
真实运行时是有意义的等待，在测试里没必要真的等 2/4/8 秒。

全部改动跑过 `pytest tests/`（99 个测试全过，其中 11 个是这次新增的，之前 88 个原样重跑一遍确认
没受影响）；`agent_c_unified_runner` 特性开关默认值确认为 `False`（`worker._RUNNERS["C"]` 现场
打印验证过绑定的是旧的 `run_agent_c`，不是新路径）；backend 健康检查正常，跑完确认没有活跃的
PipelineRun 被打断。

## Agent 统一架构改造方案 · 阶段 2：迁移 Agent A（图片输入 + 数量一一对应校验）

跟 C 同一个模式：`agent_a.py` 新增 `A_SPEC`/`run_agent_a_unified`，`run_agent_a` 一行没动，
`agent_a_unified_runner` 特性开关默认关闭。这一步给框架添了一处真实需要的扩展——A 的 `Document`
行要写 `agent_version_id`，但 `AgentSpec.persist` 原来的签名只有 `(db, case, result)`，没地方拿
`version.id`。改成 `persist(db, case, result, run)`：`mark_running()` 早就把已发布版本 id 写进了
`run.agent_version_id`，`persist` 直接读，不用自己再查一次（也避免"这次运行实际用的版本"和
"persist 时刻查到的已发布版本"理论上可能不是同一个的隐患）。C 的 `_persist` 签名同步加了这个
参数，虽然用不上，直接忽略——"契约统一比用不到就不传更重要"。

"文档数量一一对应"这条校验原来是当场失败，migrate 时改成了可修复问题——数量对不上多半是模型
漏处理或多输出了一份，跟 C 的越界引用是同一类"模型该自己能改对"的错误。阶段 2 的验收重点是方案
原文点的名："验证图片字节读取只发生一次，不在修复调用中重复读取/变更输入集合"——`_build_request`
只在整次运行开始前读一次 MinIO，框架的重试循环复用同一个 `AgentRequest`，专门写了一个用计数器
包一层 `get_object_bytes` 的测试验证：两份单据、触发一次修复重试，读取次数是 2 次不是 4 次。
11 个新测试，覆盖数量不对/字段缺失两种修复路径、新旧路径落库结果比对一致。

## 真实 bug：Agent F 场景选择从上线起就没在 worker 里生效过

用户反馈："F 步骤虽然让用户选了场景，但实际生成没有仅限于选定的场景，而是非常随机"。查真实数据
坐实了这个问题——`CASE-20260820-002` 这次运行 `input_ref` 里明确记录只选了 `SCN21`，但实际落库
的 7 条用例里有 6 条是别的场景（SCN04/SCN12/SCN13/SCN14/SCN24/SCN26）。

根因：arq worker 进程从 8 月 19 日 09:27 就没重启过，而场景选择的过滤/硬化逻辑是 8 月 20 日 00:41
才写进 `agent_f.py` 的，中间隔了 15 小时。`uvicorn --reload` 会自动重载，所以 API 层正确把
`scenario_codes` 写进了 `PipelineRun.input_ref`（数据库里能看到"记录对了"）；但 worker 没有热
重载，这段时间的每一次实际执行走的都是进程内存里那份旧代码——旧代码压根没有 `scenario_codes`
这个概念，不管前端选没选、选了什么，实际都是拿全量启用场景库生成，跟"随机"的观感完全吻合。这也
顺带回答了用户的第二个问题（"画像定义是否真的传入给 LLM"）：`persona_library` 里每个画像带的是
完整 `behavior_guideline` 原文，不是裸 code，这部分逻辑写得比这次 worker 卡住的时间窗口更早，
一直是对的，没受影响。

确认没有活跃运行后重启了 worker（新 PID，日志正常）。受影响的历史数据（`CASE-20260820-002` 那
6 条不该出现的用例，目前 `decision` 都还是默认的 `accept`）如实告知了用户，是否清理没有擅自处理，
留给用户决定——不是这次修复应该单方面动的数据。

## Agent 统一架构改造方案 · 阶段 3、阶段 4：迁移 B、D、F，加一次横向统一验收

用户要求"继续阶段 3 和阶段 4，然后再统一验证"，一次性把剩下三个 agent 迁完再收尾，不是逐个交付。

### 框架补了两处真实需要的扩展

写 B 之前先给 A/C 的 `persist` 签名做了一次性延伸；写 F 之前发现框架还缺两样东西，这两样都是先
在 `framework.py` 里加好、再回头把 A/C 的签名对齐，不是每个 agent 各自变出一套形状：

- **`AgentSpec.validate`/`persist` 都加了 `context: dict` 参数**——F 的 `build_request` 要算出
  一堆 validate/persist 都要用的派生状态（`allowed_scenario_codes`/`persona_id_by_code`/
  `doc_seqs`/`cards_by_code`，后两者还要查库），如果 validate 和 persist 各自重算一遍，理论上
  可能算出三份不完全一致的结果（尤其 `persona_id_by_code` 涉及一次 DB 查询）。改成 `build_request`
  算一次塞进 `AgentRequest.context`，后两步直接复用同一份。A/B/C/D 目前用不上，签名里照样收着、
  忽略即可。
- **`AgentRequest.precomputed_result`**——D 有个跳过 LLM 调用的既有优化（没有 `real_gap` 阶段时，
  补丁数组的答案已经从 `stage_map` 结构性地推出来了，不该为一个已知答案花一次 token），但框架的
  主循环原来是"一定会调 `run_structured`"。加一个字段：非空时框架直接把它当"模型输出"送进
  `validate()`（跳过校验这件事本身不允许例外，只是没有 LLM 输出可言时不进修复循环——校验不通过
  直接失败，没有什么好"发回给模型重试"的）。

### B：产品规则已经定过，迁移不重新讨论

`B_SPEC` 照搬旧版本的六阶段覆盖 + 边界判断校验，唯一的变化是"发现问题直接 raise"改成"收集成
`ValidationIssue`"——跟 C 一样，越界的 `boundary_decision`（引用不存在的病历 seq、阶段代码不合法）
现在会先给模型一次修复机会。重跑仍然无条件清空 `stage_map`/`boundary_decisions`（前端已有的确认
弹窗覆盖了这个产品决策），这次迁移原样保留，不是要重新讨论的范围。11 个新测试。

### D：红线焊死的方式——校验不通过，persist 就不会跑

D 的迁移把"没有 real_gap 阶段"接到了新的 `precomputed_result` 机制上，新旧路径对着"跳过 LLM
调用、直接成功、mock_count=0"这个具体结果做了比对。核心红线（不能为非 real_gap 阶段编造内容）
从"当场失败"改成了可修复问题，但这不是放宽——`persist()` 只有在 `validate()` 完全没有 issue 时
才会被调用，给模型一次修复机会不代表给它一次"蒙混过关"的机会：专门测过"两次都编造"的情况，最终
0 条落库，跟旧版本行为完全一致。12 个新测试。

### F：最复杂的一个，也是唯一保留"静默丢弃"策略而不是"报修复"的

`F_SPEC` 的 `_validate` 只检查必填字段缺失（触发修复），刻意**不**把"场景越界引用""图片 seq
越界""画像代码编造"这三类坏数据转成 `ValidationIssue`——这是 F 一直以来的既有策略（丢弃那一行/
那一套画像脚本，不整体失败），这次migrate 原样保留，不是趁机往 A/B/C/D 那种"报出来走修复循环"
上靠。要不要统一，是后面的产品/架构决定，不是这次迁移单方面拍板的事——专门写了三个
`_still_dropped_not_fatal` 测试锁定这个"不变"。12 个新测试。

### 统一验收：把方案第 9 节的验收标准变成可执行的横向测试

新增 `test_unified_framework_acceptance.py`，不是每个 agent 自己文件里的测试再拼凑一次结论，是
直接对着方案原文的验收标准写断言：五个 agent 真的经同一个 `run_with_framework` 函数对象执行
（不是"看起来像"，`inspect.getsource` 确认过）；`RetryPolicy` 形状统一且当前数值一致；对五个
agent 各自触发一次"未发布版本"必然失败的路径，统一断言 `run.status` 不会停在 `queued`/
`running`；D 和 F 的两条核心红线（不编造非 real_gap 内容、不落库越界场景）连续两次都触发也不会
被放行；五个特性开关在代码里声明的默认值确认全部是 `False`（直接查 Pydantic 字段声明，不实例化
`Settings`，避免这台机器的环境变量把"当前值"误当成"默认值"）。

全部改动跑过 `pytest tests/`（155 个测试全过，这两个阶段加统一验收新增 57 个）；确认五个特性
开关在真实 `worker._RUNNERS` 里现场打印都还是绑定旧的 `run_agent_x`；backend 健康检查正常；跑完
确认没有活跃 PipelineRun 被打断；场景库总数仍是 49，五个 agent 的真实已发布版本（A: v4 / B: v2 /
C: v1 / D: v1 / F: v5）都还是各自唯一一条，没有被测试过程中创建的临时版本污染。

**没做、且明确说了不做的**：真实 LLM 调用下的验证（这次全部是 fake 驱动）、切换任何一个特性开关
的默认值、方案阶段 5（删除 `run_agent_a/b/c/d/f` 里的旧样板代码）——三者都要等真的拿真实病例跑过
新路径、确认没问题之后才做，不是这次"迁移 + 测试"顺带完成的事。

## 收尾：处理历史脏数据 → 真实 LLM 端到端验证 → 阶段 5 删旧代码

用户要求按顺序做三件事："先处理 6 条用例，再真实 LLM 验证，阶段 5"——上一节末尾明确留下的三个
"没做"，这次依次做完。

### 6 条历史脏用例：批量不纳入，不是删除

`CASE-20260820-002` 因为那次 worker 场景选择 bug（见上一节）生成了 6 条不该出现的用例。处理
方式选的是"不纳入 + 写清楚原因"，不是硬删除——这批数据本身没有错（不是伪造的医学内容），只是
不该出现在这次选择范围里，保留下来供审计/回溯比直接抹掉更稳妥，也正好是这个项目自己刚建好的
批量审核机制（`board_service.batch_decide_queries`）的第一次真实使用。用真实账号（Cristal，
用户本人）作为 actor 调用，reject_reason 写清楚是哪个已知 bug 导致的，审计记录里能查到
`query_count: 6`。处理完确认：6 条变成 `不纳入`，唯一那条真正匹配选择（`SCN21`）的用例保持
`已纳入`不受影响。

### 真实 LLM 端到端验证：一个病例，五个 agent，全部真实调用

写了一个一次性脚本，不经过 worker/队列，直接调用 `run_agent_a/b/c/d/f`（这时候已经是唯一实现）：
新建一个专门的验证病例（`case_no` 前缀 `VALIDATE-`，`patient_meta.dx` 写明"验证脚本自动创建、
非真实病例"），复用一个真实病例的 2 份去标识化图片作为单据，A→B→C→D→F 依次跑，全部用真实
MiniMax 调用（不是 fake）。结果：

- 5 个全部一次成功，没有一个触发修复循环——不是说明修复循环没用（阶段 0-4 的 43+57 个测试已经
  把它的每条分支都测过了），是说明这次的真实调用里模型表现良好，用来验证的是"框架跟真实 LLM 的
  接口对不对得上"，不是"修复循环在真实场景下触不触发"。
- 数据质量抽查：A 抽出的两份报告类型、检查时间、结构化字段都对；B 的阶段映射正确把两份早期影像
  报告归到 J01（其余阶段 uncovered/not_applicable，跟只有 2 份早期资料的病例相符）；C 抽出 15 个
  真实患者画像字段（年龄/性别/科室/床号/入院诊断……），来源 seq 标注正确；D 正确判断没有
  real_gap 阶段、跳过 LLM 调用（耗时 0.004 秒，token_usage 为 None，两者都印证了这条优化真的
  生效）；F 生成了 1 个裂点、4 条用例（覆盖场景库里 4 个跟"早期异常影像判读"相关的真实场景）、
  16 套画像脚本（4 用例 × 4 画像）。
- 运行记录本身也验证过：A/B/C/F 都有真实的 `token_usage`（provider/model/prompt_tokens/
  completion_tokens 全部来自 MiniMax 真实返回，不是估算）和有内容的 `progress_note`；F 真实耗时
  274.8 秒（约 4.6 分钟），跟这个项目此前观察到的"F 通常要几分钟"完全吻合。

验证完把这个病例（含上传到 MinIO 的 2 份图片）彻底删除，确认删除后查不到——不留在真实病例列表里
污染用户的工作队列。

### 阶段 5：删除旧手写实现，五个 agent 各自只剩一套代码

对每个 agent 做了同一件事：删掉整段旧的 `run_agent_x()`（查版本、标运行、直接调 `run_structured`、
成功失败收口——这些机制性代码现在完全由 `run_with_framework` 一处实现），**把 `run_agent_x_unified`
改名为 `run_agent_x`**（不是留着 `_unified` 后缀——现在就一套实现，没有"统一版 vs 旧版"的区分
必要，保留后缀只会显得像还有另一条路径）。改名前先搜过全代码库确认影响面：只有 `worker.py`
（自己）和测试文件引用这些函数名，`sandbox.py` 引用的是 `build_context`/`build_doc_summary`/
`real_gap_stages` 这几个helper 函数，都原样保留没有改名，改名风险可控。

框架本身也补了两处这次 F/D 迁移时才发现真正需要的扩展，都是先在 `framework.py` 加好、再回头把
已经迁移的 A/B/C 签名对齐，不是每个 agent 各自变出一套形状：

- `AgentSpec.validate`/`persist` 都加了 `context: dict` 参数——F 的 `build_request` 要算出一堆
  三步都要用的派生状态（`allowed_scenario_codes`/`persona_id_by_code`……），算一次塞进
  `AgentRequest.context`，避免各自重算出三份可能不一致的结果。
- `AgentRequest.precomputed_result`——D 的"没有 real_gap 阶段就跳过 LLM 调用"这个既有优化接进
  框架的机制：非空时框架直接把它当"模型输出"送进 `validate()`，不调 `run_structured()`。

`worker.py` 的 `_RUNNERS` 表不再按特性开关选路径，五个 agent 直接指向各自唯一的实现；
`core.config.Settings` 里五个 `agent_x_unified_runner` 开关也一并删除——不再有意义，没有第二条
路径可切。

测试这边同步做了清理，不是留着测已经删掉的代码：删除 5 个阶段 0 时代的 `test_agent_x_regression.py`
（专门测旧实现，旧实现没了这些测试也该走）；把 5 个 `test_agent_x_unified_regression.py` 改名
回收 `test_agent_x_regression.py` 这个名字，内容里"新旧两条路径对比"的测试要么删掉要么改写成
"单一实现产出结果正确"（比如 A/C 原来"新旧路径落库结果一致"的测试，现在旧路径不存在了，改成直接
断言产出内容本身对不对）；`test_unified_framework_acceptance.py` 里"五个特性开关默认值是 False"
这条测试删掉（开关本身没了），换成一条新的："agent_x.py 不该再直接 import run_structured"（阶段 5
真正的验收点——LLM 调用现在只应该发生在 framework.py 一处）。

全部改动跑过 `pytest tests/`（112 个测试全过——比阶段 3/4 结束时的 155 少，是因为删掉了 5 个
测已删除代码的文件和几个"新旧对比"类测试，不是覆盖率下降，是被测代码本身不再有两份）。改完确认
没有活跃 PipelineRun 后重启了 arq worker（这是这次会话第二次因为"改了 agent 代码"而重启——
汲取的教训直接生效：这次改完立刻检查、立刻重启，没有再拖）；backend 健康检查、`GET /cases`、
`GET /board/testcases` 都正常返回 200。

到此为止，Agent 统一架构改造方案的阶段 0-5 全部完成：A/B/C/D/F 五个 agent 统一走
`UnifiedAgentRunner`，各自只保留 `build_request`/`validate`/`persist` 三个函数，真实 LLM 调用
端到端验证过，worker 正在跑的就是这套代码，没有特性开关、没有并行的旧实现。

## 内部部署打包

用户要"打包一个完整镜像，公司内部部署"。之前的 `infra/docker-compose.yml` 和两个 `Dockerfile`
早就在阶段路线图里标注过是"仅限本地开发"（`--reload`、源码整个挂载进容器、数据库/Redis/MinIO
端口全部暴露到宿主机、默认密码就是 `caseflow`/`caseflow`）——这次是真正把生产可用的一套做出来，
不是把开发配置原样复制一份改个名字。

### 三个新 Dockerfile/compose，跟开发版本分开维护

- `backend/Dockerfile.prod`：两阶段构建（装依赖的阶段留着 gcc/libpq-dev 编译工具链，运行阶段
  只留 `libpq5` 这个运行时库），非 root 用户跑服务，去掉 `--reload`。容器启动跑
  `docker-entrypoint.sh`：先 `alembic upgrade head` 再执行传进来的命令（`uvicorn` 或
  `arq` worker）——backend 和 worker 两个服务共用同一个镜像，只是 command 不同，跟开发版本的
  组织方式一致；迁移本身幂等，两个服务同时启动重复跑一次没有副作用。
- `frontend/Dockerfile.prod`：两阶段构建，第一阶段 `npm run build`（不是 `npm run dev`）产出
  静态文件，第二阶段用 nginx 发布。`VITE_API_BASE_URL` 构建时烤成相对路径 `/api`（Vite 的环境
  变量是构建期展开的，不是运行时读取），配合 `nginx.conf` 里的反代（`/api/*` → backend 容器的
  8000 端口，`/` 其余路径走 SPA 的 `try_files` 回退到 `index.html`），部署只需要对外开 nginx
  这一个端口，不用分别管理前后端两个端口，也不用处理跨域——`nginx.conf` 里顺带把反代读超时调到
  600s，避免 Agent F 那种观察到接近 5 分钟的运行被 nginx 默认 60s 超时掐断。
- `infra/docker-compose.prod.yml`：postgres/redis/minio 不发布端口到宿主机（只在 compose 内部
  网络里被 backend/worker 访问）；所有密码密钥走 `infra/.env.prod`，用 `${VAR:?错误提示}` 语法
  强制要求真实填写，不像开发版本那样有 `caseflow`/`caseflow` 兜底；镜像不挂载源码，代码是
  build 时打进去的。

### 顺手补的两个真实安全缺口

这两个都不是这次部署包裹带来的新问题——是这次为了准备构建上下文时发现的，之前就一直存在：

1. **没有 `.dockerignore`**：`backend/.env`（真实密钥，990 字节，这台机器上一直在用）和
   `backend/.venv`（148MB）之前都会被 `docker build` 的构建上下文原样带进去，`COPY . .` 会把
   `.env` 直接烤进镜像层——镜像一旦 push 到仓库或者分享给别人，密钥就泄露了。新增
   `backend/.dockerignore`/`frontend/.dockerignore`。
2. **`.gitignore` 只排除了 `infra/.env`，没排除 `backend/.env`**：这个仓库到现在还没有
   `git init` 过，还没真的泄露过，但迟早会走 `git init && git add .` 这一步。改成
   `**/.env` + `**/.env.*` + `!**/.env*.example` 三行覆盖所有变体，只留 `.example` 结尾的模板
   文件可以被提交——改完专门用一个临时的 scratch git 仓库验证过这条规则：`backend/.env.example`
   和 `infra/.env.prod.example` 正确被排除在忽略名单之外（第一版用 `!**/.env.example` 精确匹配，
   验证时发现 `infra/.env.prod.example` 文件名不是"精确等于 `.env.example`"，没被这条规则救回来，
   改成 `!**/.env*.example` 后重新验证通过）。

### 全流程真实跑通过一次，不是照着配置文件推测步骤该怎么写

构建了真实镜像（backend 438MB、frontend 76.3MB），起了完整的 `docker-compose.prod.yml` 六个
服务，依次验证了：

- `docker compose ... config` 确认 `${POSTGRES_PASSWORD}` 这类跨服务的变量插值真的按预期工作
  （构建 `DATABASE_URL` 时正确读到 `.env.prod` 里的密码）——过程中发现一个真实的 Compose 语义
  坑：`env_file:` 写在某个 service 底下只把变量注入那个容器的运行时环境，不会让同一份变量在
  compose 文件别处的 `${VAR}` 插值里生效；真正让插值生效需要用 `docker compose --env-file
  infra/.env.prod` 显式指定，这也是为什么部署指南里每条命令都带着这个参数、还建议设个 alias。
- 五个服务全部 healthy 后，`curl` 直接走 nginx 反代验证了 `/`（前端页面）和 `/api/health`
  （后端接口）都正确返回；`postgres`/`minio` 确认没有端口发布到宿主机（`docker compose ps`
  看端口列表，不是靠 curl 探测——这台机器本身还跑着 Homebrew 原生的 MinIO/Postgres 占着同样的
  5432/9000 端口，curl 探测会被这个巧合误导，得看 compose 自己报的端口映射才是权威判断）。
- 容器里真实跑通了首次部署的种子数据流程：建管理员账号（`app.seed`）、种子六个 Agent 的 v1
  prompt（`app.seed_agents`）、种子四个候选画像（`app.seed_personas`）、导入业务方真实场景库
  （`app.import_scenario_standards`——这一步发现 `doc/` 目录不在 backend 镜像的构建上下文里，
  业务方 xlsx 文件需要单独 `docker compose cp` 进容器，已经写进部署指南）。跑完确认：49 个场景、
  20 项评分标准、7 条法规依据、11 条通用红线、20 项标准卡分档，数字跟这个项目一直在用的真实
  业务数据一致。
- 最后真实登录了一次（`/api/auth/login` 拿到 JWT）、用这个 token 真实调用了 `/api/agents`
  （返回 6 个真实 agent）和 `/api/scenario-types`（返回 49 个真实场景）——不是只测到"容器起来
  了"，是测到"一个人真的能登录、真的能看到数据"这一步。

验证完把这套测试部署（六个容器 + 三个数据卷）整个 `down -v` 删掉，`.env.prod` 测试文件也删了，
没有留下任何东西。这台机器本身用来跑这一整套项目开发工作的真实 backend/worker（Homebrew 原生
Postgres/Redis/MinIO + 本地 venv）全程没有被碰过——验证前后都确认过真实病例数（9 条）和真实
场景数（49 条）没有变化。

新增 `doc/内部部署指南.md`，覆盖：前置条件、配置密钥、构建启动、首次部署的种子数据步骤（含
业务方 xlsx 导入这个容易被漏掉的环节）、更新部署时"一定要确认 worker 真的重启了"这条这个项目
反复踩过的坑、备份（`pg_dump` 而不是直接打包卷文件）、常见问题排查、以及没有外网访问权限的
部署环境该怎么用 `docker save`/`docker load` 离线搬运镜像。
