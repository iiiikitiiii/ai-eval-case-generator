import { useEffect, useState } from "react";
import { fetchDocumentImageUrl } from "../api/cases";

/** Small blob-preview <img> for a document image. Documents/query image
 * refs are auth-gated on the backend (MinIO never faces the browser
 * directly), so this fetches the bytes itself and manages its own
 * object: URL lifetime instead of taking a plain src. Pass onClick to make
 * it open in a <Lightbox> — every call site does, this is never meant to
 * be a dead-end 34px square. */
export function DocThumb({
  caseId,
  documentId,
  contentType,
  size = 44,
  onClick,
}: {
  caseId: string;
  documentId: string;
  contentType: string | null;
  size?: number;
  onClick?: () => void;
}) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!contentType?.startsWith("image/")) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    fetchDocumentImageUrl(caseId, documentId)
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
  }, [caseId, documentId, contentType]);

  const placeholderStyle = {
    width: size,
    height: size,
    borderRadius: 6,
    background: "var(--surface)",
    border: "1px solid var(--line)",
    flexShrink: 0,
  } as const;

  if (!contentType?.startsWith("image/")) {
    return <div style={placeholderStyle} />;
  }
  if (!url) {
    return <div style={placeholderStyle} />;
  }

  const img = (
    <img
      src={url}
      alt=""
      style={{ width: size, height: size, objectFit: "cover", borderRadius: 6, border: "1px solid var(--line)", flexShrink: 0, display: "block" }}
    />
  );

  if (!onClick) return img;

  return (
    <button
      onClick={onClick}
      title="点击查看大图"
      style={{ padding: 0, border: "none", background: "none", cursor: "zoom-in", flexShrink: 0, borderRadius: 6 }}
    >
      {img}
    </button>
  );
}
