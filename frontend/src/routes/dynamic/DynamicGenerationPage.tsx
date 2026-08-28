import { useEffect, useId, useMemo, useState, type CSSProperties, type KeyboardEvent } from "react";
import { listPersonas, listScenarioTypes } from "../../shared/api/agents";
import { getCase, listCases } from "../../shared/api/cases";
import { ApiError } from "../../shared/api/client";
import { advanceDynamicQuery } from "../../shared/api/dynamic";
import type { CaseDetail, CaseListItem, ScenarioTypeOut, UserPersonaOut } from "../../shared/api/types";
import { useAuth } from "../../shared/auth/AuthContext";
import { Lightbox } from "../../shared/ui/Lightbox";
import { QueryCard } from "../../shared/ui/QueryCard";

const JOURNEY_STAGE_LABEL: Record<string, string> = {
  J01: "疑诊 / 初筛期",
  J02: "确诊后治疗方案决策期",
  J03: "初诊治疗实施期",
  J04: "复发 / 进展 / 耐药后治疗方案调整",
  J05: "康复随访期",
  J06: "姑息照护期",
};

interface SelectOption {
  value: string;
  label: string;
  keywords?: string[];
}

interface DynamicSelection {
  caseId: string;
  stageCode: string;
  scenarioCode: string;
  personaId: string;
}

interface ScreenshotPreview {
  file: File;
  url: string;
}

interface DynamicHistoryTurn {
  round: number;
  messages: string[];
  images: number[];
  responseText: string | null;
  responseImageNames: string[];
}

interface DynamicConversationView {
  conversationId: string;
  turns: DynamicHistoryTurn[];
  done: boolean;
  stopReason: string | null;
}

const SUPPORTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);
// Mirror the backend per-turn attachment cap for immediate browser feedback.
const MAX_RESPONSE_IMAGES = 10;
const MAX_RESPONSE_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_RESPONSE_IMAGES_TOTAL_BYTES = 20 * 1024 * 1024;

const EMPTY_SELECTION: DynamicSelection = {
  caseId: "",
  stageCode: "",
  scenarioCode: "",
  personaId: "",
};

function readStoredSelection(userId: string): DynamicSelection {
  if (!userId) return { ...EMPTY_SELECTION };
  try {
    const raw = sessionStorage.getItem(`dynamic-generation-selection:${userId}`);
    if (!raw) return { ...EMPTY_SELECTION };
    const parsed = JSON.parse(raw) as Partial<Record<keyof DynamicSelection, unknown>>;
    // Accept only the four committed string identifiers. Search text and any
    // unexpected stored fields never become part of the restored UI state.
    return {
      caseId: typeof parsed.caseId === "string" ? parsed.caseId : "",
      stageCode: typeof parsed.stageCode === "string" ? parsed.stageCode : "",
      scenarioCode: typeof parsed.scenarioCode === "string" ? parsed.scenarioCode : "",
      personaId: typeof parsed.personaId === "string" ? parsed.personaId : "",
    };
  } catch {
    // Storage may contain malformed JSON or be disabled by the browser; an
    // empty in-memory selection keeps the page usable in both situations.
    return { ...EMPTY_SELECTION };
  }
}

interface SearchableSelectProps {
  label: string;
  value: string;
  options: SelectOption[];
  placeholder: string;
  disabled?: boolean;
  emptyText?: string;
  onChange: (value: string) => void;
}

/**
 * Local combobox used by the four Stage 2-1 selectors. Keeping it on this page
 * avoids introducing a shared UI abstraction before another screen needs it.
 */
function SearchableSelect({
  label,
  value,
  options,
  placeholder,
  disabled = false,
  emptyText = "没有匹配项",
  onChange,
}: SearchableSelectProps) {
  const inputId = useId();
  const listId = `${inputId}-list`;
  const selected = options.find((option) => option.value === value);
  const [searchText, setSearchText] = useState(selected?.label ?? "");
  const [open, setOpen] = useState(false);

  // Parent selections reset dependent values; mirror that reset in the text
  // field so a stale stage/scenario/persona label is never shown as selected.
  useEffect(() => {
    setSearchText(selected?.label ?? "");
  }, [selected?.label]);

  const filteredOptions = useMemo(() => {
    const term = searchText.trim().toLocaleLowerCase("zh-CN");
    if (!term || selected?.label === searchText) return options;
    return options.filter((option) =>
      [option.label, ...(option.keywords ?? [])]
        .join(" ")
        .toLocaleLowerCase("zh-CN")
        .includes(term),
    );
  }, [options, searchText, selected?.label]);

  function handleTextChange(nextText: string) {
    setSearchText(nextText);
    setOpen(true);
    // Typing after making a selection means the user is searching again; the
    // stored value is cleared until an actual option is chosen.
    if (nextText !== selected?.label) onChange("");
  }

  function choose(option: SelectOption) {
    setSearchText(option.label);
    onChange(option.value);
    setOpen(false);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "Enter" && open && filteredOptions.length > 0) {
      event.preventDefault();
      choose(filteredOptions[0]);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      <label htmlFor={inputId} style={{ fontSize: 12.5, fontWeight: 700, color: "var(--navy)" }}>{label}</label>
      <div style={{ position: "relative" }}>
        <input
          id={inputId}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={open && !disabled}
          autoComplete="off"
          value={searchText}
          placeholder={placeholder}
          disabled={disabled}
          onChange={(event) => handleTextChange(event.target.value)}
          onFocus={(event) => {
            setOpen(true);
            // Selecting existing text lets users immediately type a new
            // partial term instead of manually clearing the prior label.
            event.currentTarget.select();
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={handleKeyDown}
          style={{ ...inputStyle, background: disabled ? "var(--card)" : "var(--surface)" }}
        />
        <span
          aria-hidden="true"
          style={{
            position: "absolute",
            right: 11,
            top: "50%",
            transform: "translateY(-50%)",
            color: "var(--muted)",
            pointerEvents: "none",
          }}
        >
          ▾
        </span>

        {open && !disabled && (
          <div id={listId} role="listbox" style={menuStyle}>
            {filteredOptions.length === 0 && (
              <div style={{ padding: "9px 11px", color: "var(--muted)", fontSize: 12 }}>{emptyText}</div>
            )}
            {filteredOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                // Prevent input blur from closing the menu before selection.
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(option)}
                style={{
                  ...optionStyle,
                  background: option.value === value ? "var(--navy-l)" : "var(--surface)",
                  color: option.value === value ? "var(--navy)" : "var(--ink)",
                  fontWeight: option.value === value ? 700 : 400,
                }}
              >
                {option.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/** Dynamic Query workspace backed by the case-scoped web API. */
export function DynamicGenerationPage() {
  const { user } = useAuth();
  const userId = user?.id ?? "";
  const screenshotInputId = useId();
  const [cases, setCases] = useState<CaseListItem[]>([]);
  const [scenarioTypes, setScenarioTypes] = useState<ScenarioTypeOut[]>([]);
  const [personas, setPersonas] = useState<UserPersonaOut[]>([]);
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null);
  const [selection, setSelection] = useState<DynamicSelection>(() => readStoredSelection(userId));
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [loadingCase, setLoadingCase] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lightboxSeq, setLightboxSeq] = useState<number | null>(null);
  const [responseText, setResponseText] = useState("");
  const [screenshots, setScreenshots] = useState<File[]>([]);
  const [screenshotPreviews, setScreenshotPreviews] = useState<ScreenshotPreview[]>([]);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);
  const [selectedQueryId, setSelectedQueryId] = useState("");
  const [conversation, setConversation] = useState<DynamicConversationView | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [retryLocked, setRetryLocked] = useState(false);
  const {
    caseId: selectedCaseId,
    stageCode: selectedStage,
    scenarioCode: selectedScenario,
    personaId: selectedPersonaId,
  } = selection;

  // sessionStorage survives route unmounts and reloads in this tab but is
  // cleared when the tab closes. The user-specific key prevents account A's
  // selected case from appearing after account B signs in on the same tab.
  useEffect(() => {
    if (!userId) return;
    try {
      sessionStorage.setItem(`dynamic-generation-selection:${userId}`, JSON.stringify(selection));
    } catch {
      // Persistence is a convenience; storage restrictions must not prevent
      // users from continuing with the current in-memory selection.
    }
  }, [selection, userId]);

  // Object URLs keep screenshot bytes local to the browser and must all be
  // revoked whenever the file list changes to avoid retaining old blobs.
  useEffect(() => {
    const previews = screenshots.map((file) => ({ file, url: URL.createObjectURL(file) }));
    setScreenshotPreviews(previews);
    return () => previews.forEach((preview) => URL.revokeObjectURL(preview.url));
  }, [screenshots]);

  // Load reusable dictionaries once. Case detail is fetched only after a case
  // is selected because it contains the larger cutpoint/query/variant graph.
  useEffect(() => {
    let cancelled = false;
    Promise.all([listCases(), listScenarioTypes(), listPersonas()])
      .then(([caseRows, scenarioRows, personaRows]) => {
        if (cancelled) return;
        setCases(caseRows);
        setScenarioTypes(scenarioRows);
        setPersonas(personaRows);
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError instanceof ApiError ? requestError.message : "加载选择项失败");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingOptions(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setCaseDetail(null);
    if (!selectedCaseId) {
      setLoadingCase(false);
      return () => {
        cancelled = true;
      };
    }

    setLoadingCase(true);
    setError(null);
    getCase(selectedCaseId)
      .then((detail) => {
        if (!cancelled) setCaseDetail(detail);
      })
      .catch((requestError) => {
        if (!cancelled) {
          setError(requestError instanceof ApiError ? requestError.message : "加载病例用例失败");
        }
      })
      .finally(() => {
        if (!cancelled) setLoadingCase(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedCaseId]);

  const caseOptions = useMemo<SelectOption[]>(() => cases.map((item) => {
    const diagnosis = typeof item.patient_meta.dx === "string" ? item.patient_meta.dx : "";
    const patientName = typeof item.patient_meta.name === "string" ? item.patient_meta.name : "";
    return {
      value: item.id,
      label: [item.case_no, item.alias, diagnosis].filter(Boolean).join(" · "),
      keywords: [item.case_no, item.alias ?? "", diagnosis, patientName],
    };
  }), [cases]);

  const eligibleCutpoints = useMemo(() => (caseDetail?.cutpoints ?? []).filter(
    (cutpoint) => cutpoint.enabled && cutpoint.queries.some((query) => query.decision === "accept"),
  ), [caseDetail]);

  const stageOptions = useMemo<SelectOption[]>(() => {
    const codes = Array.from(new Set(eligibleCutpoints.map((cutpoint) => cutpoint.stage_code))).sort();
    return codes.map((code) => ({
      value: code,
      label: `${code} · ${JOURNEY_STAGE_LABEL[code] ?? code}`,
      keywords: [code, JOURNEY_STAGE_LABEL[code] ?? ""],
    }));
  }, [eligibleCutpoints]);

  const scenarioOptions = useMemo<SelectOption[]>(() => {
    if (!selectedStage) return [];
    const codes = new Set<string>();
    for (const cutpoint of eligibleCutpoints) {
      if (cutpoint.stage_code !== selectedStage) continue;
      for (const query of cutpoint.queries) {
        if (query.decision === "accept") codes.add(query.scenario_type);
      }
    }
    return Array.from(codes).sort().flatMap((code) => {
      const scenario = scenarioTypes.find((item) => item.code === code && item.active);
      // A removed or disabled scenario must not be restored merely because an
      // older accepted query still contains its denormalized code.
      if (!scenario) return [];
      return [{
        value: code,
        label: `${code} · ${scenario.name}`,
        keywords: [code, scenario.name, scenario.feature_scenario ?? "", scenario.description ?? ""],
      }];
    });
  }, [eligibleCutpoints, scenarioTypes, selectedStage]);

  const personaOptions = useMemo<SelectOption[]>(() => {
    if (!selectedStage || !selectedScenario) return [];
    const availableIds = new Set<string>();
    for (const cutpoint of eligibleCutpoints) {
      if (cutpoint.stage_code !== selectedStage) continue;
      for (const query of cutpoint.queries) {
        if (query.decision !== "accept" || query.scenario_type !== selectedScenario) continue;
        for (const variant of query.variants) availableIds.add(variant.persona_id);
      }
    }
    return personas.filter((persona) => persona.active && availableIds.has(persona.id)).map((persona) => ({
      value: persona.id,
      label: `${persona.name} · ${persona.role === "patient" ? "患者本人" : "家属"} · ${persona.cognition === "low" ? "低认知" : "较高认知"}`,
      keywords: [persona.code, persona.name, persona.behavior_guideline],
    }));
  }, [eligibleCutpoints, personas, selectedScenario, selectedStage]);

  // A stage/scenario can contain multiple cutpoints, so the four selectors may
  // legitimately resolve to more than one accepted query. Keep every match,
  // but trim each card to the selected persona's variant for an exact preview.
  const selectedTestCases = useMemo(() => {
    if (!selectedStage || !selectedScenario || !selectedPersonaId) return [];
    return eligibleCutpoints.flatMap((cutpoint) => {
      if (cutpoint.stage_code !== selectedStage) return [];
      return cutpoint.queries.flatMap((query) => {
        if (query.decision !== "accept" || query.scenario_type !== selectedScenario) return [];
        const variants = query.variants.filter((variant) => variant.persona_id === selectedPersonaId);
        if (variants.length === 0) return [];
        return [{ cutpoint, query: { ...query, variants } }];
      });
    });
  }, [eligibleCutpoints, selectedPersonaId, selectedScenario, selectedStage]);
  const selectedTarget = selectedTestCases.find(({ query }) => query.id === selectedQueryId) ?? null;
  const selectedVariant = selectedTarget?.query.variants[0] ?? null;
  const hasResponseContent = !!responseText.trim() || screenshots.length > 0;
  const canSubmit = !!selectedTarget
    && !isGenerating
    && (!conversation || (!conversation.done && hasResponseContent));

  // Validate restored identifiers only after their authoritative option data
  // has loaded. Invalid parents clear every dependent value in the snapshot.
  useEffect(() => {
    if (loadingOptions || !selectedCaseId) return;
    if (!caseOptions.some((option) => option.value === selectedCaseId)) {
      setSelection({ ...EMPTY_SELECTION });
    }
  }, [caseOptions, loadingOptions, selectedCaseId]);

  useEffect(() => {
    if (loadingCase || !caseDetail || !selectedStage) return;
    if (!stageOptions.some((option) => option.value === selectedStage)) {
      setSelection((current) => ({
        ...current,
        stageCode: "",
        scenarioCode: "",
        personaId: "",
      }));
    }
  }, [caseDetail, loadingCase, selectedStage, stageOptions]);

  useEffect(() => {
    if (loadingOptions || loadingCase || !caseDetail || !selectedScenario) return;
    if (!scenarioOptions.some((option) => option.value === selectedScenario)) {
      setSelection((current) => ({ ...current, scenarioCode: "", personaId: "" }));
    }
  }, [caseDetail, loadingCase, loadingOptions, scenarioOptions, selectedScenario]);

  useEffect(() => {
    if (loadingOptions || loadingCase || !caseDetail || !selectedPersonaId) return;
    if (!personaOptions.some((option) => option.value === selectedPersonaId)) {
      setSelection((current) => ({ ...current, personaId: "" }));
    }
  }, [caseDetail, loadingCase, loadingOptions, personaOptions, selectedPersonaId]);

  function selectCase(value: string) {
    setLightboxSeq(null);
    resetDynamicRun();
    setSelection({ caseId: value, stageCode: "", scenarioCode: "", personaId: "" });
  }

  function selectStage(value: string) {
    resetDynamicRun();
    setSelection((current) => ({ ...current, stageCode: value, scenarioCode: "", personaId: "" }));
  }

  function selectScenario(value: string) {
    resetDynamicRun();
    setSelection((current) => ({ ...current, scenarioCode: value, personaId: "" }));
  }

  function selectPersona(value: string) {
    resetDynamicRun();
    setSelection((current) => ({ ...current, personaId: value }));
  }

  function clearResponseDraft() {
    setResponseText("");
    setScreenshots([]);
    setScreenshotError(null);
  }

  function resetDynamicRun() {
    // A conversation belongs to one exact case/query/persona combination and
    // must never survive a target change in the current page instance.
    clearResponseDraft();
    setSelectedQueryId("");
    setConversation(null);
    setGenerationError(null);
    setRetryLocked(false);
  }

  function chooseQuery(queryId: string) {
    if (isGenerating || queryId === selectedQueryId) return;
    resetDynamicRun();
    setSelectedQueryId(queryId);
  }

  function selectScreenshots(files: File[]) {
    if (files.length === 0) return;
    setGenerationError(null);
    const seen = new Set(screenshots.map((file) => `${file.name}:${file.size}:${file.lastModified}`));
    const next = [...screenshots];
    const problems: string[] = [];
    for (const file of files) {
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      if (seen.has(key)) continue;
      if (!SUPPORTED_IMAGE_TYPES.has(file.type)) {
        problems.push(`${file.name} 不是 JPEG、PNG 或 WebP`);
        continue;
      }
      if (file.size > MAX_RESPONSE_IMAGE_BYTES) {
        problems.push(`${file.name} 超过 5 MiB`);
        continue;
      }
      if (next.length >= MAX_RESPONSE_IMAGES) {
        problems.push(`每轮最多上传 ${MAX_RESPONSE_IMAGES} 张图片`);
        break;
      }
      const nextTotal = next.reduce((sum, item) => sum + item.size, 0) + file.size;
      if (nextTotal > MAX_RESPONSE_IMAGES_TOTAL_BYTES) {
        problems.push("每轮图片总大小不能超过 20 MiB");
        break;
      }
      seen.add(key);
      next.push(file);
    }
    setScreenshots(next);
    setScreenshotError(problems.length > 0 ? problems[0] : null);
  }

  function removeScreenshot(index: number) {
    setScreenshots((current) => current.filter((_, currentIndex) => currentIndex !== index));
    setScreenshotError(null);
    setGenerationError(null);
  }

  function clearScreenshots() {
    setScreenshots([]);
    setScreenshotError(null);
    setGenerationError(null);
  }

  async function advanceConversation() {
    if (!selectedTarget || !selectedVariant || !canSubmit) return;
    const submittedText = responseText.trim();
    const submittedImages = [...screenshots];
    setIsGenerating(true);
    setGenerationError(null);
    try {
      const result = await advanceDynamicQuery(
        selectedCaseId,
        selectedTarget.query.id,
        selectedVariant.id,
        conversation ? submittedText || null : null,
        conversation ? submittedImages : [],
      );
      if (!conversation) {
        // The first call retrieves durable seed R1 without submitting a reply.
        setConversation({
          conversationId: result.conversation_id,
          turns: [{
            round: result.round,
            messages: result.messages,
            images: result.images,
            responseText: null,
            responseImageNames: [],
          }],
          done: result.done,
          stopReason: result.stop_reason,
        });
      } else {
        setConversation((current) => {
          if (!current) return current;
          const turns = current.turns.map((turn, index) => index === current.turns.length - 1
            ? {
                ...turn,
                responseText: submittedText || null,
                responseImageNames: submittedImages.map((file) => file.name),
              }
            : turn);
          if (!result.done) {
            turns.push({
              round: result.round,
              messages: result.messages,
              images: result.images,
              responseText: null,
              responseImageNames: [],
            });
          }
          return {
            ...current,
            turns,
            done: result.done,
            stopReason: result.stop_reason,
          };
        });
        clearResponseDraft();
      }
      setRetryLocked(false);
    } catch (requestError) {
      const apiError = requestError instanceof ApiError ? requestError : null;
      setGenerationError(apiError?.message ?? "动态问题生成失败，请稍后重试");
      // The service persists answers before calling the LLM. A gateway error
      // therefore locks the exact draft so retries cannot overwrite it.
      if (apiError?.status === 502 || apiError?.status === 504) setRetryLocked(true);
    } finally {
      setIsGenerating(false);
    }
  }

  const composerDisabled = !conversation || conversation.done || isGenerating || retryLocked;
  const actionLabel = isGenerating
    ? "生成中…"
    : conversation?.done
      ? "已完成"
      : retryLocked
        ? "重试生成"
        : conversation
          ? "生成下一轮问题"
          : selectedTarget
            ? "开始动态跑测"
            : "请选择用例";

  return (
    <div style={{ padding: "24px 32px 60px" }}>
      <h1 style={{ fontSize: 19, fontWeight: 700, margin: "0 0 4px" }}>动态生成</h1>
      <p style={{ fontSize: 12.5, color: "var(--sub)", margin: "0 0 18px" }}>
        选择一条已有用例和画像，以真实被测系统答复动态生成后续问题。
      </p>

      <section style={panelStyle}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "var(--navy)", marginBottom: 14 }}>生成配置</div>
        {error && (
          <div style={{ color: "var(--red)", background: "var(--red-l)", border: "1px solid var(--red-b)", borderRadius: 6, padding: "7px 10px", marginBottom: 14 }}>
            {error}
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 14 }}>
          <SearchableSelect
            label="病例"
            value={selectedCaseId}
            options={caseOptions}
            placeholder={loadingOptions ? "加载病例中…" : "输入病例编号、别名或诊断"}
            disabled={loadingOptions || isGenerating}
            emptyText="没有匹配的病例"
            onChange={selectCase}
          />
          <SearchableSelect
            label="阶段"
            value={selectedStage}
            options={stageOptions}
            placeholder={loadingCase ? "加载阶段中…" : selectedCaseId ? "输入阶段编号或名称" : "请先选择病例"}
            disabled={!selectedCaseId || loadingCase || !caseDetail || isGenerating}
            emptyText="该病例没有已纳入用例的阶段"
            onChange={selectStage}
          />
          <SearchableSelect
            label="场景"
            value={selectedScenario}
            options={scenarioOptions}
            placeholder={selectedStage ? "输入场景编号或名称" : "请先选择阶段"}
            disabled={!selectedStage || isGenerating}
            emptyText="该阶段没有已纳入的场景"
            onChange={selectScenario}
          />
          <SearchableSelect
            label="画像"
            value={selectedPersonaId}
            options={personaOptions}
            placeholder={selectedScenario ? "输入画像名称、角色或认知水平" : "请先选择场景"}
            disabled={!selectedScenario || isGenerating}
            emptyText="该场景没有可用画像"
            onChange={selectPersona}
          />
        </div>
      </section>

      {/* Hide the workspace until the four selectors resolve to a real query;
          empty configuration should show only the configuration controls. */}
      {selectedTestCases.length > 0 && (
        <section
          className="dynamic-content-grid"
          // Once the run is complete there is no further response to compose,
          // so the history panel takes the full workspace width.
          style={conversation?.done ? { gridTemplateColumns: "minmax(0, 1fr)" } : undefined}
        >
          <div style={panelStyle}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--navy)" }}>选出的用例</div>
              <span style={{ fontSize: 11, color: "var(--muted)" }}>
                共 {selectedTestCases.length} 条
              </span>
            </div>
            {caseDetail && selectedTestCases.map(({ cutpoint, query }) => {
              const isSelected = query.id === selectedQueryId;
              // Dynamic preview deliberately exposes only seed R1; generated
              // R2-R4 from Agent F must not influence this workflow.
              const seedOnlyQuery = {
                ...query,
                variants: query.variants.map((variant) => ({
                  ...variant,
                  turns: variant.turns.filter((turn) => turn.round === 1),
                })),
              };
              return (
                <div
                  key={query.id}
                  style={{
                    border: `2px solid ${isSelected ? "var(--navy)" : "transparent"}`,
                    borderRadius: 9,
                    padding: 4,
                    marginBottom: 10,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 4 }}>
                    <button
                      type="button"
                      disabled={isGenerating || isSelected}
                      onClick={() => chooseQuery(query.id)}
                      style={querySelectButtonStyle(isSelected, !isGenerating)}
                    >
                      {isSelected ? "当前跑测用例" : "选择此用例"}
                    </button>
                  </div>
                  <QueryCard
                    caseId={selectedCaseId}
                    documents={caseDetail.documents}
                    cutpoint={cutpoint}
                    query={seedOnlyQuery}
                    stageLabel={JOURNEY_STAGE_LABEL[cutpoint.stage_code]}
                    onOpenImage={setLightboxSeq}
                    readOnly
                  />
                </div>
              );
            })}

            {conversation && (
              <div style={{ marginTop: 18 }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "var(--navy)", marginBottom: 10 }}>
                  动态跑测记录
                </div>
                {conversation.turns.map((turn) => (
                  <div key={turn.round} style={historyTurnStyle}>
                    <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                      <b style={{ color: "var(--navy)" }}>第 {turn.round} 轮问题</b>
                      {turn.responseText === null && turn.responseImageNames.length === 0 && !conversation.done && (
                        <span style={{ color: "var(--muted)", fontSize: 11 }}>等待答复</span>
                      )}
                    </div>
                    {turn.messages.map((message, index) => (
                      <div key={index} style={{ borderLeft: "2px solid var(--ex)", paddingLeft: 8, marginTop: 6 }}>
                        {message}
                      </div>
                    ))}
                    {turn.images.length > 0 && (
                      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
                        <span style={{ color: "var(--muted)", fontSize: 11 }}>随问题发送：</span>
                        {turn.images.map((seq) => (
                          <button key={seq} type="button" onClick={() => setLightboxSeq(seq)} style={imageLinkStyle}>
                            DOC-{String(seq).padStart(2, "0")}
                          </button>
                        ))}
                      </div>
                    )}
                    {(turn.responseText !== null || turn.responseImageNames.length > 0) && (
                      <div style={{ background: "var(--surface)", borderRadius: 6, padding: "8px 10px", marginTop: 9 }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "var(--sub)" }}>已提交答复</div>
                        {turn.responseText && <div style={{ whiteSpace: "pre-wrap", marginTop: 3 }}>{turn.responseText}</div>}
                        {turn.responseImageNames.length > 0 && (
                          <div style={{ color: "var(--muted)", fontSize: 11, marginTop: 4 }}>
                            回复图片：{turn.responseImageNames.join("、")}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))}
                {conversation.done && (
                  <div style={{ color: "var(--green)", fontWeight: 700, marginTop: 8 }}>
                    动态跑测已完成{conversation.stopReason ? `（${conversation.stopReason}）` : ""}
                  </div>
                )}
              </div>
            )}
          </div>

          {!conversation?.done && (
          <div style={{ ...panelStyle, display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--navy)", marginBottom: 4 }}>
            被测系统答复
          </div>
          <div style={{ fontSize: 11.5, color: "var(--muted)", marginBottom: 9 }}>
            {!selectedTarget
              ? "请先从左侧显式选择一条用例。"
              : !conversation
                ? "点击开始动态跑测，服务端将返回该画像的种子 R1。"
                : "可以输入文字、上传截图，或同时提供两者。成功提交后将在左侧保留本页记录。"}
          </div>
          <textarea
            value={responseText}
            onChange={(event) => {
              setResponseText(event.target.value);
              setGenerationError(null);
            }}
            disabled={composerDisabled}
            placeholder={conversation ? "输入被测系统对当前问题的实际答复…" : "开始动态跑测后可填写答复"}
            rows={5}
            style={{
              ...responseInputStyle,
              // Fill the right column like the reference layout while leaving
              // the upload/generation actions anchored beneath the editor.
              flex: 1,
              minHeight: 240,
              background: composerDisabled ? "var(--card)" : "var(--surface)",
            }}
          />

          <div style={{ display: "flex", alignItems: "center", gap: 9, marginTop: 9, flexWrap: "wrap" }}>
            <input
              id={screenshotInputId}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              disabled={composerDisabled}
              onChange={(event) => {
                selectScreenshots(Array.from(event.target.files ?? []));
                // Reset the native input so removed screenshots can be chosen
                // again and future selections append instead of replacing.
                event.currentTarget.value = "";
              }}
              style={{ display: "none" }}
            />
            <label
              htmlFor={!composerDisabled ? screenshotInputId : undefined}
              style={{
                ...uploadButtonStyle,
                color: !composerDisabled ? "var(--navy)" : "var(--muted)",
                cursor: !composerDisabled ? "pointer" : "default",
                opacity: !composerDisabled ? 1 : 0.65,
              }}
            >
              {screenshots.length > 0 ? "继续上传截图" : "上传截图"}
            </label>
            {screenshots.length > 0 && (
              <button type="button" disabled={composerDisabled} onClick={clearScreenshots} style={removeButtonStyle}>
                清空全部
              </button>
            )}
            <span style={{ fontSize: 11, color: "var(--muted)" }}>
              JPEG / PNG / WebP，最多 10 张，单张 5 MiB，总计 20 MiB{screenshots.length > 0 ? ` · 已选 ${screenshots.length} 张` : ""}
            </span>
            {/* Keep upload and generation actions on the same horizontal row;
                the flexible spacer anchors generation on the right. */}
            <span style={{ flex: 1 }} />
            <button
              type="button"
              disabled={!canSubmit}
              onClick={advanceConversation}
              style={generateButtonStyle(canSubmit)}
            >
              {actionLabel}
            </button>
          </div>

          {screenshotError && <div style={{ color: "var(--red)", fontSize: 11.5, marginTop: 7 }}>{screenshotError}</div>}
          {generationError && <div style={{ color: "var(--red)", fontSize: 11.5, marginTop: 7 }}>{generationError}</div>}
          {screenshotPreviews.length > 0 && (
            <div style={screenshotGridStyle}>
              {screenshotPreviews.map((preview, index) => (
                <div key={preview.url} style={screenshotCardStyle}>
                  <img
                    src={preview.url}
                    alt={`已上传的被测系统答复截图 ${index + 1}`}
                    style={{ width: 96, height: 72, objectFit: "contain", borderRadius: 5, background: "var(--surface)" }}
                  />
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {preview.file.name}
                    </div>
                    <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 3 }}>
                      {(preview.file.size / 1024).toFixed(1)} KB
                    </div>
                    <button type="button" disabled={composerDisabled} onClick={() => removeScreenshot(index)} style={{ ...removeButtonStyle, marginTop: 6, padding: "3px 8px", fontSize: 11 }}>
                      移除
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          </div>
          )}
        </section>
      )}

      {caseDetail && lightboxSeq !== null && (
        <Lightbox
          caseId={selectedCaseId}
          docs={caseDetail.documents.map((document) => ({
            id: document.id,
            seq: document.seq,
            contentType: document.content_type,
            label: document.document_type,
          }))}
          initialSeq={lightboxSeq}
          onClose={() => setLightboxSeq(null)}
        />
      )}
    </div>
  );
}

const panelStyle: CSSProperties = {
  padding: 18,
  border: "1px solid var(--line)",
  borderRadius: 10,
  background: "var(--card)",
};

const inputStyle: CSSProperties = {
  width: "100%",
  height: 38,
  padding: "7px 34px 7px 10px",
  border: "1px solid var(--line)",
  borderRadius: 7,
  color: "var(--ink)",
  fontFamily: "inherit",
  fontSize: 12.5,
  outline: "none",
};

const menuStyle: CSSProperties = {
  position: "absolute",
  zIndex: 20,
  top: "calc(100% + 4px)",
  left: 0,
  right: 0,
  maxHeight: 240,
  overflowY: "auto",
  border: "1px solid var(--line)",
  borderRadius: 7,
  background: "var(--surface)",
  boxShadow: "0 8px 24px rgba(0, 0, 0, 0.14)",
};

const optionStyle: CSSProperties = {
  display: "block",
  width: "100%",
  padding: "8px 10px",
  border: "none",
  borderBottom: "1px solid var(--line-soft)",
  fontFamily: "inherit",
  fontSize: 12,
  lineHeight: 1.45,
  textAlign: "left",
  cursor: "pointer",
};

const responseInputStyle: CSSProperties = {
  display: "block",
  width: "100%",
  resize: "vertical",
  padding: "9px 10px",
  border: "1px solid var(--line)",
  borderRadius: 7,
  color: "var(--ink)",
  fontFamily: "inherit",
  fontSize: 12.5,
  lineHeight: 1.6,
  outline: "none",
};

const uploadButtonStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  height: 36,
  padding: "0 12px",
  border: "1px solid var(--navy-b)",
  borderRadius: 6,
  background: "var(--navy-l)",
  fontSize: 12,
  fontWeight: 600,
};

const removeButtonStyle: CSSProperties = {
  padding: "6px 10px",
  border: "1px solid var(--line)",
  borderRadius: 6,
  background: "var(--surface)",
  color: "var(--sub)",
  fontFamily: "inherit",
  fontSize: 12,
  cursor: "pointer",
};

const screenshotGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
  gap: 10,
  marginTop: 10,
};

const screenshotCardStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "96px minmax(0, 1fr)",
  alignItems: "center",
  gap: 10,
  padding: 8,
  border: "1px solid var(--line)",
  borderRadius: 7,
  background: "var(--surface)",
};

const historyTurnStyle: CSSProperties = {
  border: "1px solid var(--line)",
  borderRadius: 7,
  padding: "10px 12px",
  marginBottom: 9,
  background: "var(--card)",
  fontSize: 12,
};

const imageLinkStyle: CSSProperties = {
  padding: "2px 7px",
  border: "1px solid var(--navy-b)",
  borderRadius: 5,
  background: "var(--navy-l)",
  color: "var(--navy)",
  fontFamily: "inherit",
  fontSize: 10.5,
  cursor: "pointer",
};

function querySelectButtonStyle(selected: boolean, enabled: boolean): CSSProperties {
  return {
    padding: "5px 11px",
    border: `1px solid ${selected ? "var(--navy)" : "var(--line)"}`,
    borderRadius: 6,
    background: selected ? "var(--navy)" : "var(--surface)",
    color: selected ? "#fff" : "var(--navy)",
    fontFamily: "inherit",
    fontSize: 11.5,
    fontWeight: 700,
    cursor: enabled && !selected ? "pointer" : "default",
  };
}

function generateButtonStyle(enabled: boolean): CSSProperties {
  return {
    // Match the screenshot upload control so the two primary actions align
    // even though one is a label-backed file picker and one is a button.
    height: 36,
    padding: "0 18px",
    border: "1px solid var(--navy)",
    borderRadius: 7,
    background: enabled ? "var(--navy)" : "var(--card)",
    color: enabled ? "#fff" : "var(--muted)",
    fontFamily: "inherit",
    fontSize: 12.5,
    fontWeight: 700,
    cursor: enabled ? "pointer" : "default",
  };
}
