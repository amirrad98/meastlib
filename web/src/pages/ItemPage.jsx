import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import OpenSeadragon from "openseadragon";
import { fetchManifest, fetchPageText, pageId } from "../api.js";

export default function ItemPage() {
  const { itemId, page } = useParams();
  const navigate = useNavigate();
  const pageNum = parseInt(page, 10) || 1;

  const [manifest, setManifest] = useState(null);
  const [text, setText] = useState("");
  const [showText, setShowText] = useState(false);
  const [error, setError] = useState("");
  const viewerRef = useRef(null);
  const osdRef = useRef(null);

  useEffect(() => {
    fetchManifest(itemId).then(setManifest).catch((e) => setError(e.message));
  }, [itemId]);

  const canvases = manifest?.items || [];
  const total = canvases.length;
  const canvas = canvases[pageNum - 1];

  useEffect(() => {
    if (!canvas || !viewerRef.current) return;
    const service = canvas.items?.[0]?.items?.[0]?.body?.service?.[0];
    if (!service) return;
    if (osdRef.current) osdRef.current.destroy();
    osdRef.current = OpenSeadragon({
      element: viewerRef.current,
      tileSources: `${service.id}/info.json`,
      prefixUrl: "https://cdn.jsdelivr.net/npm/openseadragon@4.1/build/openseadragon/images/",
      showNavigationControl: true,
      maxZoomPixelRatio: 3,
    });
    return () => {
      if (osdRef.current) {
        osdRef.current.destroy();
        osdRef.current = null;
      }
    };
  }, [canvas]);

  useEffect(() => {
    fetchPageText(itemId, pageId(pageNum)).then(setText);
  }, [itemId, pageNum]);

  function go(n) {
    if (n >= 1 && n <= total) navigate(`/item/${itemId}/${n}`);
  }

  useEffect(() => {
    function onKey(e) {
      // RTL books: left arrow = next page
      if (e.key === "ArrowLeft") go(pageNum + 1);
      if (e.key === "ArrowRight") go(pageNum - 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  if (error) return <main className="reader"><p className="error">Could not load item: {error}</p></main>;
  if (!manifest) return <main className="reader"><p>Loading…</p></main>;

  const title = manifest.label?.none?.[0] || itemId;

  return (
    <main className="reader">
      <div className="reader-bar">
        <h1>{title}</h1>
        <div className="pager">
          <button onClick={() => go(pageNum + 1)} disabled={pageNum >= total} title="Next page">‹</button>
          <span>
            p. {pageNum} / {total}
          </span>
          <button onClick={() => go(pageNum - 1)} disabled={pageNum <= 1} title="Previous page">›</button>
          <button className="toggle-text" onClick={() => setShowText(!showText)}>
            {showText ? "Hide text" : "Show text"}
          </button>
        </div>
      </div>
      <div className={`reader-body ${showText ? "with-text" : ""}`}>
        <div className="osd" ref={viewerRef} />
        {showText && (
          <div className="ocr-panel" dir="rtl">
            {text ? <pre>{text}</pre> : <p className="muted">No OCR text for this page.</p>}
          </div>
        )}
      </div>
    </main>
  );
}
