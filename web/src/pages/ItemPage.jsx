import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import OpenSeadragon from "openseadragon";
import { fetchManifest, fetchPageText, pageId, searchWithinItem } from "../api.js";
import { useI18n } from "../i18n.jsx";

export default function ItemPage() {
  const { itemId, page } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { t } = useI18n();
  const navigate = useNavigate();
  const pageNum = parseInt(page, 10) || 1;
  const query = searchParams.get("q") || "";
  const [manifest, setManifest] = useState(null);
  const [text, setText] = useState("");
  const [showText, setShowText] = useState(false);
  const [showThumbs, setShowThumbs] = useState(false);
  const [find, setFind] = useState(query);
  const [matches, setMatches] = useState(null);
  const [pageInput, setPageInput] = useState(String(pageNum));
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [viewerError, setViewerError] = useState("");
  const [viewerVersion, setViewerVersion] = useState(0);
  const viewerRef = useRef(null);
  const osdRef = useRef(null);

  useEffect(() => { fetchManifest(itemId).then(setManifest).catch((e) => setError(e.message)); }, [itemId]);
  useEffect(() => { setFind(query); }, [query]);
  useEffect(() => { setPageInput(String(pageNum)); }, [pageNum]);
  const canvases = manifest?.items || [];
  const total = canvases.length;
  const canvas = canvases[pageNum - 1];

  useEffect(() => {
    if (!canvas || !viewerRef.current) return;
    const service = canvas.items?.[0]?.items?.[0]?.body?.service?.[0];
    if (!service) return;
    let cancelled = false;
    let viewer = null;
    setViewerError("");
    if (osdRef.current) osdRef.current.destroy();
    (async () => {
      try {
        const response = await fetch(`${service.id}/info.json`, { cache: "no-store" });
        if (!response.ok) throw new Error(`IIIF image service returned ${response.status}`);
        const tileSource = await response.json();
        const publicServiceId = new URL(service.id, window.location.href).href;
        tileSource.id = publicServiceId;
        if (tileSource["@id"]) tileSource["@id"] = publicServiceId;
        if (cancelled) return;
        viewer = OpenSeadragon({ element: viewerRef.current, tileSources: tileSource, prefixUrl: "https://cdn.jsdelivr.net/npm/openseadragon@4.1/build/openseadragon/images/", showNavigationControl: true, maxZoomPixelRatio: 3 });
        viewer.addHandler("open", () => { if (!cancelled) setViewerVersion((value) => value + 1); });
        viewer.addHandler("open-failed", () => { if (!cancelled) setViewerError("Could not display this page image."); });
        osdRef.current = viewer;
      } catch (e) { if (!cancelled) setViewerError(e.message || "Could not display this page image."); }
    })();
    return () => { cancelled = true; if (viewer) viewer.destroy(); if (osdRef.current === viewer) osdRef.current = null; };
  }, [canvas]);

  useEffect(() => { fetchPageText(itemId, pageId(pageNum)).then(setText).catch(() => setText("")); }, [itemId, pageNum]);
  useEffect(() => {
    if (!query) { setMatches(null); return; }
    let cancelled = false;
    searchWithinItem(itemId, query, pageId(pageNum)).then((value) => { if (!cancelled) setMatches(value); }).catch(() => { if (!cancelled) setMatches(null); });
    return () => { cancelled = true; };
  }, [itemId, pageNum, query]);

  useEffect(() => {
    const viewer = osdRef.current;
    const current = matches?.current;
    if (!viewer || !viewerVersion || !current || current.page !== pageId(pageNum)) return;
    viewer.clearOverlays();
    const snippets = current.snippets || [];
    const sourcePage = snippets[0]?.pages?.[0] || { width: canvas?.width || 1, height: canvas?.height || 1 };
    const scaleX = (canvas?.width || sourcePage.width) / sourcePage.width;
    const scaleY = (canvas?.height || sourcePage.height) / sourcePage.height;
    const boxes = snippets.flatMap((snippet) => (snippet.highlights || []).flat().map((box) => {
      const parent = snippet.regions?.[box.parentRegionIdx] || { ulx: 0, uly: 0 };
      return {
        ...box,
        ulx: Number(parent.ulx || 0) + Number(box.ulx || 0),
        lrx: Number(parent.ulx || 0) + Number(box.lrx || 0),
        uly: Number(parent.uly || 0) + Number(box.uly || 0),
        lry: Number(parent.uly || 0) + Number(box.lry || 0),
      };
    }));
    boxes.forEach((box) => {
      const element = document.createElement("div");
      element.className = "ocr-highlight-overlay";
      element.setAttribute("aria-hidden", "true");
      viewer.addOverlay({
        element,
        location: viewer.viewport.imageToViewportRectangle(box.ulx * scaleX, box.uly * scaleY, (box.lrx - box.ulx) * scaleX, (box.lry - box.uly) * scaleY),
      });
    });
    const region = snippets[0]?.regions?.[0];
    if (region) {
      const rectangle = viewer.viewport.imageToViewportRectangle(region.ulx * scaleX, region.uly * scaleY, (region.lrx - region.ulx) * scaleX, (region.lry - region.uly) * scaleY);
      viewer.viewport.fitBounds(rectangle, true);
    }
  }, [matches, viewerVersion, canvas, pageNum]);

  function go(number) {
    if (number >= 1 && number <= total) navigate(`/item/${itemId}/${number}${query ? `?q=${encodeURIComponent(query)}` : ""}`);
  }
  useEffect(() => {
    function onKey(event) {
      if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName)) return;
      if (event.key === "ArrowLeft") go(pageNum + 1);
      if (event.key === "ArrowRight") go(pageNum - 1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const matchIndex = matches?.pages?.indexOf(pageId(pageNum)) ?? -1;
  const thumbnailPages = useMemo(() => {
    const start = Math.max(1, pageNum - 12);
    const end = Math.min(total, pageNum + 12);
    return Array.from({ length: Math.max(0, end - start + 1) }, (_, index) => start + index);
  }, [pageNum, total]);
  async function copyCitation() {
    const title = manifest?.label?.none?.[0] || itemId;
    try {
      await navigator.clipboard.writeText(`${title}, ${t("page")} ${pageNum}. ${window.location.href}`);
      setCopied(true); window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setViewerError(t("copyFailed"));
    }
  }

  if (error) return <main className="reader"><p className="error">Could not load item: {error}</p></main>;
  if (!manifest) return <main className="reader"><p>{t("loading")}</p></main>;
  const title = manifest.label?.none?.[0] || itemId;
  const manifestType = manifest.metadata?.find((entry) => entry.label?.en?.[0] === "Type")?.value?.none?.[0];
  const isNewspaper = manifestType === "newspaper";
  const searchablePdf = manifest.rendering?.find((item) => item.format === "application/pdf");
  const pageStem = pageId(pageNum);

  return <main className="reader">
    <div className="reader-bar"><div><Link className="reader-back" to={`/item/${itemId}`}>← {t("aboutItem")}</Link><h1 dir="auto">{title}</h1></div><div className="pager">
      <button onClick={() => go(pageNum + 1)} disabled={pageNum >= total} aria-label={t("next")}>‹</button>
      <form className="page-jump" onSubmit={(e) => { e.preventDefault(); go(Number(pageInput)); }}><label>{t("page")}<input inputMode="numeric" value={pageInput} onChange={(e) => setPageInput(e.target.value)} aria-label={t("page")} /></label><span>/ {total}</span><button>{t("go")}</button></form>
      <button onClick={() => go(pageNum - 1)} disabled={pageNum <= 1} aria-label={t("previous")}>›</button>
      <button className="toggle-text" onClick={() => setShowThumbs(!showThumbs)}>{t("thumbnails")}</button>
      <button className="toggle-text" onClick={() => setShowText(!showText)}>{showText ? t("hideText") : t("showText")}</button>
    </div></div>
    <div className="reader-tools"><form className="reader-search" onSubmit={(e) => { e.preventDefault(); const next = new URLSearchParams(searchParams); if (find.trim()) next.set("q", find.trim()); else next.delete("q"); setSearchParams(next); }}><input dir="auto" value={find} onChange={(e) => setFind(e.target.value)} placeholder={t(isNewspaper ? "searchWithinIssue" : "searchWithin")} /><button>{t("search")}</button></form>
      {matches && <div className="match-navigation"><span>{matches.total} {t(isNewspaper ? "matchesInIssue" : "matchesInBook")}</span><button disabled={matchIndex <= 0} onClick={() => go(Number(matches.pages[matchIndex - 1]?.replace("page-", "")))}>{t("previous")}</button><button disabled={!matches.pages.length || matchIndex >= matches.pages.length - 1} onClick={() => go(Number(matches.pages[matchIndex < 0 ? 0 : matchIndex + 1]?.replace("page-", "")))}>{t("next")}</button></div>}
      <div className="reader-downloads"><button onClick={copyCitation}>{copied ? t("citationCopied") : t("copyCitation")}</button>{searchablePdf && <a href={searchablePdf.id}>{t("searchablePdf")}</a>}<a href={`/api/catalog/items/${itemId}/ocr/${pageStem}?format=text`}>{t("plainText")}</a><a href={`/api/catalog/items/${itemId}/ocr/${pageStem}?format=alto`}>{t("alto")}</a><a href={`/data/items/${itemId}/iiif/manifest.json`}>{t("iiif")}</a></div>
    </div>
    <div className={`reader-body ${showText ? "with-text" : ""} ${showThumbs ? "with-thumbs" : ""}`}>
      {showThumbs && <aside className="thumbnail-strip" aria-label={t("thumbnails")}>{pageNum > 13 && <button onClick={() => go(Math.max(1, pageNum - 25))}>… {Math.max(1, pageNum - 25)}</button>}{thumbnailPages.map((number) => <button className={number === pageNum ? "active" : ""} onClick={() => go(number)} key={number}><img src={`/iiif/3/${itemId}%2Faccess%2Fpage-${String(number).padStart(4, "0")}.jpg/full/120,/0/default.jpg`} alt="" loading="lazy" /><span>{number}</span></button>)}{pageNum + 12 < total && <button onClick={() => go(Math.min(total, pageNum + 25))}>{Math.min(total, pageNum + 25)} …</button>}</aside>}
      <div className="osd" ref={viewerRef}>{viewerError && <p className="viewer-error">{viewerError}</p>}</div>
      {showText && <aside className="ocr-panel" dir="auto"><p className="machine-note">{t("machineText")}</p>{text ? <pre>{text}</pre> : <p className="muted">No OCR text for this page.</p>}</aside>}
    </div>
  </main>;
}
