/** "DOC-03" as clickable text instead of a dead label — every place that
 * used to render this as a plain string (核对冲突 involved_docs, 阶段裁定
 * stage_map/边界判断) now opens the lightbox to that exact document. */
export function DocRefLink({ seq, onOpen }: { seq: number; onOpen: (seq: number) => void }) {
  return (
    <button
      onClick={() => onOpen(seq)}
      style={{
        background: "none",
        border: "none",
        padding: 0,
        color: "var(--ex)",
        textDecoration: "underline",
        textUnderlineOffset: 2,
        cursor: "zoom-in",
        font: "inherit",
        fontWeight: 600,
      }}
    >
      DOC-{String(seq).padStart(2, "0")}
    </button>
  );
}
