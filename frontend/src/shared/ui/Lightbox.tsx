import { useEffect, useState, type CSSProperties } from "react";
import { fetchDocumentImageUrl } from "../api/cases";

export interface LightboxDoc {
  id: string;
  seq: number;
  contentType: string | null;
  label?: string | null;
}

/** Full-screen image viewer — click any document thumbnail anywhere in the
 * app (upload cards, "随 query 发送" refs, DOC-XX text mentions in flags/
 * stage map/boundary decisions, board test-case detail) and it opens here
 * instead of staying a 34px square you can't actually read. Takes the
 * case's full document list so ‹/› can page through everything, not just
 * the one image that was clicked. */
export function Lightbox({ caseId, docs, initialSeq, onClose }: { caseId: string; docs: LightboxDoc[]; initialSeq: number; onClose: () => void }) {
  const [index, setIndex] = useState(() => Math.max(0, docs.findIndex((d) => d.seq === initialSeq)));
  const [url, setUrl] = useState<string | null>(null);
  const doc = docs[index];

  useEffect(() => {
    if (!doc) return;
    setUrl(null);
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchDocumentImageUrl(caseId, doc.id)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u);
          return;
        }
        objectUrl = u;
        setUrl(u);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, doc?.id]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowLeft") setIndex((i) => Math.max(0, i - 1));
      if (e.key === "ArrowRight") setIndex((i) => Math.min(docs.length - 1, i + 1));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [docs.length, onClose]);

  if (!doc) return null;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(10, 12, 16, 0.88)",
        zIndex: 1000,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: 40,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{ display: "flex", flexDirection: "column", alignItems: "center", maxWidth: "100%", maxHeight: "100%" }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#fff", fontSize: 13, marginBottom: 12 }}>
          <span style={{ fontWeight: 700 }}>DOC-{String(doc.seq).padStart(2, "0")}</span>
          {doc.label && <span style={{ color: "rgba(255,255,255,0.7)" }}>{doc.label}</span>}
          <span style={{ color: "rgba(255,255,255,0.5)" }}>
            {index + 1} / {docs.length}
          </span>
        </div>

        <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
          {index > 0 && (
            <button onClick={() => setIndex((i) => i - 1)} style={navBtnStyle("left")} aria-label="上一张">
              ‹
            </button>
          )}
          {url ? (
            <img
              src={url}
              alt=""
              style={{ maxWidth: "82vw", maxHeight: "76vh", borderRadius: 8, boxShadow: "0 20px 60px rgba(0,0,0,0.6)", display: "block" }}
            />
          ) : (
            <div
              style={{
                width: 320,
                height: 320,
                maxWidth: "82vw",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "rgba(255,255,255,0.6)",
                fontSize: 12.5,
              }}
            >
              加载中…
            </div>
          )}
          {index < docs.length - 1 && (
            <button onClick={() => setIndex((i) => i + 1)} style={navBtnStyle("right")} aria-label="下一张">
              ›
            </button>
          )}
        </div>

        <button
          onClick={onClose}
          style={{
            marginTop: 16,
            padding: "6px 16px",
            borderRadius: 6,
            border: "1px solid rgba(255,255,255,0.3)",
            background: "rgba(255,255,255,0.08)",
            color: "#fff",
            fontSize: 12,
            cursor: "pointer",
          }}
        >
          关闭（Esc）
        </button>
      </div>
    </div>
  );
}

function navBtnStyle(side: "left" | "right"): CSSProperties {
  return {
    position: "absolute",
    [side]: -56,
    top: "50%",
    transform: "translateY(-50%)",
    width: 40,
    height: 40,
    borderRadius: "50%",
    border: "1px solid rgba(255,255,255,0.3)",
    background: "rgba(255,255,255,0.1)",
    color: "#fff",
    fontSize: 22,
    lineHeight: 1,
    cursor: "pointer",
  };
}
