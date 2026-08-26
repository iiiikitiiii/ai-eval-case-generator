# Agent 统一架构改造方案

## 1. 目的

将当前 A/B/C/D/F 的“单次 Prompt + LLM + 各自落库”实现，收敛为：

> **统一运行框架 + 声明式 Agent 规格 + 保留领域规则的扩展函数。**

本次改造的直接目标不是引入开放式 agent loop，而是降低重复实现、提升失败可恢复性，并确保所有 Agent 采用一致的运行记录、校验、重试、审计与失败收口机制。

## 2. 结论与边界

### 2.1 不做开放式 Agent Loop

当前任务的输入在运行开始时已基本完备：病历图片、结构化病历、旅程表、场景库和画像库均由系统提供。让模型自由决定工具调用、无限规划或自主扩展上下文，不能增加可验证事实，反而会增加成本、时延和医学场景的越界风险。

保留的循环是**有界修复循环（bounded repair loop）**：模型输出未通过服务端校验时，系统将明确错误反馈给模型，限定次数后重试；超过次数即失败并交给人工。

### 2.2 不统一领域规则

统一的是运行机制；不统一的是每个步骤的医学/业务约束。

| Agent | 必须保留的领域约束 |
| --- | --- |
| A | 单据数量与输出一一对应；OCR 零编造；跨单据冲突识别 |
| B | 六阶段完整覆盖；阶段映射与边界判断规则 |
| C | 患者画像字段的组合与冲突标识 |
| D | 只允许为 `real_gap` 生成推测；禁止推断未来阶段 |
| F | 场景 code、资料序号、画像集合、标准卡和多轮脚本的合法性 |

### 2.3 本期不改变的内容

- 不改变现有 A/B/C/D/F 的 API 路径、前端流程或数据库产出模型。
- 不改变 Prompt 版本管理、模型供应商切换和 `arq` 队列模式。
- 不在本次将外部资料检索、测试平台执行或自主任务规划接入模型。
- 不改变人工关卡；自动修复不能跳过人工确认、边界裁定或推测审核。

## 3. 当前架构基线

当前实现已经具备三项可复用基础：

- `llm_client.run_structured()` 统一处理 MiniMax、Kimi、Anthropic 的结构化调用、流式推理进度与 token 用量。
- `pipeline.common` 已统一处理 Prompt 版本读取、运行状态、进度、token、成功和失败收口。
- `worker.py` 已统一将 `PipelineRun` 分发至 A/B/C/D/F 的 runner。

但每个 `run_agent_x()` 仍各自承担了：输入准备、LLM 调用、字段校验、领域校验、数据替换和落库。失败时当前通常是一次调用失败后将病例整体置为 `blocked`，没有统一的可修复错误重试策略。

## 4. 目标架构

```text
API enqueue
  ↓
arq Worker
  ↓
UnifiedAgentRunner.run(spec, db, case, run)
  ├─ 读取已发布 Prompt / 当前模型设置
  ├─ spec.build_request() 构造输入
  ├─ 调用 run_structured()
  ├─ schema / 领域校验
  ├─ 可修复失败：构造修复指令，有限重试
  ├─ spec.persist() 事务性落库
  ├─ 记录运行、token、重试和审计信息
  └─ 成功 / 失败统一收口
```

### 4.1 AgentSpec

每个 Agent 以一个规格对象注册，而不是在统一 runner 内出现大量 `if agent_code == ...`。

```python
@dataclass
class AgentSpec:
    code: str
    build_request: Callable[[Session, Case, PipelineRun], AgentRequest]
    validate: Callable[[Session, Case, dict], ValidationResult]
    persist: Callable[[Session, Case, dict], dict]
    retry_policy: RetryPolicy
```

其中：

- `build_request`：只负责构造用户输入、图片和 Agent 特有上下文。
- `validate`：校验模型输出是否能安全落库；返回结构化错误，而非直接把错误格式化为自然语言。
- `persist`：只负责已验证结果的业务写入，并返回轻量 `output_ref` 摘要。
- `retry_policy`：声明该 Agent 的最大修复次数、网络重试次数及不可修复错误类型。

### 4.2 统一 Runner

统一 runner 应负责以下不属于任何单一领域的流程：

1. 查找已发布版本、标记 `PipelineRun.running`。
2. 调用 `run_structured()`，持续写入进度和 token 用量。
3. 执行通用 schema/基础类型检查，再执行 `spec.validate()`。
4. 对可修复的校验错误执行有限修复调用。
5. 在单个事务中调用 `spec.persist()`，成功后写入 `output_ref`。
6. 写入重试摘要、最终错误和后续可审计信息。
7. 所有未恢复异常经 `finish_failed()` 统一处理。

### 4.3 请求与校验结果的推荐形状

```python
@dataclass
class AgentRequest:
    user_text: str
    images: list[tuple[bytes, str]] | None = None

@dataclass
class ValidationIssue:
    code: str              # 机器可读，例如 missing_stage / invalid_scenario
    message: str           # 给运行记录和人工看的中文说明
    repairable: bool
    path: str | None = None

@dataclass
class ValidationResult:
    issues: list[ValidationIssue]

    @property
    def valid(self) -> bool: ...
```

不要继续以散落的字符串异常表达“模型输出问题”。结构化 issue 既可用于修复 Prompt，也可用于运行记录、后续看板和测试。

## 5. 有界修复与重试策略

### 5.1 三类失败

| 失败类型 | 示例 | 系统动作 |
| --- | --- | --- |
| 瞬时基础设施错误 | 网络抖动、429、5xx、连接超时 | 指数退避，最多重试 2 次 |
| 可修复输出错误 | 漏必填字段、漏阶段、无效场景 code、越界图片序号 | 带结构化错误清单进行修复调用，默认最多 1 次 |
| 不可修复业务错误 | 无输入资料、无已发布版本、前置人工关卡未完成、D 试图处理非 real_gap | 立即失败，不重试 |

### 5.2 修复调用原则

修复 Prompt 必须满足：

- 附上上一次模型的原始结构化输出和服务端发现的错误清单。
- 明确要求保留有效内容，仅修复无效部分；不得引入不在原始输入中的事实。
- 使用原 Agent 的 schema 和同一 Prompt 版本。
- 不得变更本次运行选择的模型、画像集合或病例输入。
- 修复次数达到上限即停止，不允许无限循环。

示例：

```text
上次输出未通过系统校验。请仅修复下列问题，并按既定 Schema 重新返回完整结果：
1. stage_map 缺少 J04；
2. SCN99 不存在于本次提供的场景库；
3. test_image_seqs 中的 8 不属于当前病例。

保留所有已合法内容；不得补充输入资料中不存在的医疗事实。
```

### 5.3 Agent 特有策略

| Agent | 网络重试 | 输出修复 | 额外限制 |
| --- | ---: | ---: | --- |
| A | 2 | 1 | 修复后仍必须保持文档数一一对应 |
| B | 2 | 1 | 只修复阶段/边界结构；落库前再次完整校验六阶段 |
| C | 2 | 1 | 不得修改 B 的阶段或边界数据 |
| D | 2 | 1 | 修复输入仅包含 real_gap；校验不允许输出其他阶段 |
| F | 2 | 1 | 严格校验场景、资料序号、画像 code 与标准卡引用 |

## 6. 数据与可观测性

### 6.1 PipelineRun

建议在 `PipelineRun` 增加以下可选字段，或先在已有 JSON 字段中兼容保存：

- `attempt_count`：总调用次数。
- `repair_count`：输出修复次数。
- `attempts`：结构化摘要，包括尝试序号、错误分类、失败原因、时间、模型、token。

首期建议将尝试摘要放入 `output_ref` / 新增 JSONB 字段，避免为调试信息过早拆分过多表；若看板需要按失败类别聚合，再单独迁移字段。

### 6.2 审计与脱敏

- 运行记录保存错误 code、简要信息和版本号，不在面向普通用户的界面直接暴露完整 Prompt 或原始病历文本。
- 使用 `AuditLog` 记录配置变更、人工重试和人工跳过等操作；运行本身继续以 `PipelineRun` 为主记录。
- 原始模型输出若需保存用于排查，应有独立的访问权限与保留期限策略；本期先不扩大存储范围。

## 7. 迁移计划

### 阶段 0：先补测试护栏

在不重构前，为每个现有 Agent 建立最小回归测试：成功落库、模型漏字段、无效引用、LLM 异常、运行状态最终收口。测试不依赖真实 LLM，使用可注入的 `run_structured` fake。

### 阶段 1：建立框架并迁移 Agent C

选择 C 作为首个迁移目标：它不读取图片、不删除重建 B 的边界裁定、不涉及 D 的推测红线，落库关系较简单。

验收：C 的 API、前端行为、生成数据和失败状态与现状兼容；新增一次可修复输出错误的自动修复测试。

### 阶段 2：迁移 A

迁移图片输入及“文档数量一一对应”校验；验证图片字节读取只发生一次，不在修复调用中重复读取/变更输入集合。

### 阶段 3：迁移 B

在暴露 B 重试入口之前明确产品规则：重跑 B 会重建阶段映射和边界判断，需二次确认。框架负责运行一致性，保留/清空人工裁定属于领域持久化策略。

### 阶段 4：迁移 D 与 F

D 先迁移，以 `real_gap` 白名单验证为重点；F 最后迁移，覆盖场景库、画像、图片和 variants 的多层校验。

### 阶段 5：删除旧重复样板

所有 Agent 迁移后，删除重复的运行状态、LLM 调用和通用异常收口代码，仅保留各 Agent 的输入、校验和持久化函数。

## 8. 兼容性与回滚

- 外部 endpoint、`agent_code`、队列任务参数和前端轮询协议保持不变。
- 每次仅迁移一个 Agent；其余 Agent 继续走旧 runner，避免一次性切换整条流水线。
- 迁移版本应可通过特性开关或 registry 映射回退至旧实现，直至该 Agent 的真实运行验证通过。
- 数据落库前完成全部校验；禁止修复失败后产生半写入数据。

## 9. 验收标准

### 框架级

- A/B/C/D/F 都经同一 `UnifiedAgentRunner` 执行公共生命周期。
- 每个 Agent 不再重复实现版本读取、状态更新、LLM 调用、token 写入和失败收口。
- 瞬时错误和可修复输出错误的次数上限一致且可配置。
- 最终失败的 `PipelineRun` 不会停留在 `queued` 或 `running`。

### 领域级

- 每个 Agent 现有的关键业务校验仍然生效。
- D 不能因修复调用生成非 real_gap 的推测。
- F 不能因修复调用引用未选择画像、无效场景或无效资料序号。
- B/C 的局部重试不破坏彼此的已完成数据；B 本身重跑的边界裁定策略以产品决定为准。

## 10. 后续可选演进

当未来接入外部资料检索、测试平台执行、自动补测规划等真正需要“观察—调用工具—再决策”的能力时，可在统一 runner 之上新增一个独立的研究/规划 Agent。它不应替代现有病例生产流水线，也不得绕过本方案的校验、重试上限与人工关卡。
