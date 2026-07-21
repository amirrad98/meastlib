import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { SERVICES_AVAILABLE, searchPages, pageNumber } from "../api.js";
import { useI18n } from "../i18n.jsx";

const FACETS = [["language", "language"], ["item_type", "type"], ["collection", "collection"], ["creator", "creator"], ["subject", "subject"]];

export default function SearchPage() {
  const { t } = useI18n();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryParam = searchParams.get("q") || "";
  const [q, setQ] = useState(queryParam);
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const options = Object.fromEntries(searchParams.entries());
  const start = Number(options.start || 0);

  useEffect(() => setQ(queryParam), [queryParam]);
  useEffect(() => {
    if (!queryParam.trim() || !SERVICES_AVAILABLE) { setResults(null); return; }
    let cancelled = false;
    setLoading(true); setError("");
    const { q: ignored, ...requestOptions } = options;
    searchPages(queryParam, requestOptions).then((value) => { if (!cancelled) setResults(value); }).catch((err) => { if (!cancelled) { setError(err.message); setResults(null); } }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [searchParams.toString()]);

  function submit(event) {
    event.preventDefault();
    const query = q.trim();
    if (!query) return;
    setSearchParams({ q: query });
  }
  function update(key, value) {
    const next = new URLSearchParams(searchParams);
    if (value !== "" && value != null) next.set(key, String(value)); else next.delete(key);
    if (key !== "start") next.delete("start");
    setSearchParams(next);
  }

  return (
    <main className="public-page search-page">
      <form className="searchbar" onSubmit={submit}>
        <input dir="auto" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("searchPlaceholder")} disabled={!SERVICES_AVAILABLE} autoFocus />
        <button type="submit" disabled={loading || !SERVICES_AVAILABLE}>{loading ? "…" : t("search")}</button>
      </form>
      {error && <p className="error">{error}</p>}
      {results && <div className="search-layout">
        <aside className="facet-panel search-facets">
          <h2>{t("filters")}</h2>
          <label>{t("sort")}<select value={options.sort || "relevance"} onChange={(e) => update("sort", e.target.value)}><option value="relevance">{t("relevance")}</option><option value="date">{t("date")}</option><option value="title">{t("title")}</option></select></label>
          <label>{t("search")}<select value={options.scope || "all"} onChange={(e) => update("scope", e.target.value)}><option value="all">{t("all")}</option><option value="catalog">{t("catalog")}</option><option value="fulltext">{t("fulltext")}</option></select></label>
          {FACETS.map(([parameter, facet]) => <label key={parameter}>{t(facet)}<select value={options[parameter] || ""} onChange={(e) => update(parameter, e.target.value)}><option value="">{t("all")}</option>{(results.facets?.[facet] || []).map((entry) => <option value={entry.value} key={entry.value}>{entry.label || entry.value} ({entry.count})</option>)}</select></label>)}
          <label>{t("dateFrom")}<input type="number" value={options.date_from || ""} onChange={(e) => update("date_from", e.target.value)} placeholder={t("yearPlaceholder")} /></label>
          <label>{t("dateTo")}<input type="number" value={options.date_to || ""} onChange={(e) => update("date_to", e.target.value)} placeholder={t("yearPlaceholder")} /></label>
          <button className="text-button" onClick={() => setSearchParams({ q: queryParam })}>{t("clear")}</button>
        </aside>
        <section className="search-results">
          <p className="count">{results.total} {t("works")} · {results.total_documents} {t("results")}</p>
          {results.hits?.length ? <div className="work-hits">{results.hits.map((hit) => <article className="work-hit" key={hit.item_id}>
            <Link className="work-hit-cover" to={`/item/${hit.item_id}`}><img src={hit.thumbnail} alt="" loading="lazy" /></Link>
            <div className="work-hit-content">
              <h2 dir="auto"><Link to={`/item/${hit.item_id}`}>{hit.title}</Link></h2>
              <p className="hit-meta" dir="auto">{[hit.creator, hit.date, hit.volume_number ? `vol. ${hit.volume_number}` : ""].filter(Boolean).join(" · ")}</p>
              <p className="match-summary">{hit.catalog_match && t("catalog")}{hit.catalog_match && hit.page_hit_count ? " · " : ""}{hit.page_hit_count ? `${hit.page_hit_count} ${t("matchingPages")}` : ""}</p>
              <div className="page-hits">{hit.page_hits.map((pageHit) => <Link className="page-hit" key={pageHit.id} to={`/item/${hit.item_id}/${pageNumber(pageHit.page)}?q=${encodeURIComponent(queryParam)}`}><strong>{t("page")} {pageNumber(pageHit.page)}</strong>{pageHit.snippets.map((snippet, index) => <p dir="auto" key={index} dangerouslySetInnerHTML={{ __html: snippet.text }} />)}</Link>)}</div>
            </div>
          </article>)}</div> : <div className="empty-state"><strong>{t("noResults")}</strong><p>{t("tryAgain")}</p></div>}
          <div className="pagination"><button disabled={start <= 0} onClick={() => update("start", Math.max(0, start - 10))}>{t("previous")}</button><button disabled={start + 10 >= results.total} onClick={() => update("start", start + 10)}>{t("next")}</button></div>
        </section>
      </div>}
      {!results && !error && SERVICES_AVAILABLE && <div className="search-intro"><p>{t("hero")}</p><Link to="/browse">{t("browse")}</Link></div>}
    </main>
  );
}
