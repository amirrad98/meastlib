import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import CatalogCard from "../components/CatalogCard.jsx";
import { fetchCatalogItems } from "../api.js";
import { useI18n } from "../i18n.jsx";

const FILTERS = [["language", "language"], ["item_type", "type"], ["collection", "collection"], ["creator", "creator"], ["publisher", "publisher"], ["subject", "subject"]];

export default function BrowsePage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const options = Object.fromEntries(params.entries());
  const start = Number(options.start || 0);
  useEffect(() => {
    fetchCatalogItems({ rows: 24, ...options }).then(setData).catch((e) => setError(e.message));
  }, [params.toString()]);
  function update(key, value) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    next.delete("start");
    setParams(next);
  }
  if (!data && !error) return <main className="public-page"><p>{t("loading")}</p></main>;
  return (
    <main className="public-page browse-page">
      <div className="page-heading"><p className="eyebrow">{t("explore")}</p><h1>{t("browse")}</h1></div>
      {error && <p className="error">{error}</p>}
      {data && <div className="browse-layout">
        <aside className="facet-panel">
          <h2>{t("filters")}</h2>
          <label>{t("sort")}<select value={options.sort || "recent"} onChange={(e) => update("sort", e.target.value)}><option value="recent">{t("recent")}</option><option value="title">{t("title")}</option><option value="date">{t("date")}</option></select></label>
          {FILTERS.map(([parameter, facet]) => <label key={parameter}>{t(facet)}<select value={options[parameter] || ""} onChange={(e) => update(parameter, e.target.value)}><option value="">{t("all")}</option>{(data.facets?.[facet] || []).map((entry) => <option value={entry.value} key={entry.value}>{entry.label || entry.value} ({entry.count})</option>)}</select></label>)}
          <label>{t("dateFrom")}<input value={options.date_from || ""} onChange={(e) => update("date_from", e.target.value)} placeholder={t("datePlaceholder")} /></label>
          <label>{t("dateTo")}<input value={options.date_to || ""} onChange={(e) => update("date_to", e.target.value)} placeholder={t("datePlaceholder")} /></label>
          {params.toString() && <button className="text-button" onClick={() => setParams({})}>{t("clear")}</button>}
        </aside>
        <section className="browse-results"><p className="result-count">{data.total} {t("works")}</p>{data.items.length ? <div className="catalog-grid">{data.items.map((item) => <CatalogCard item={item} key={item.id} />)}</div> : <div className="empty-state">{t("noItems")}</div>}
          <div className="pagination"><button disabled={start <= 0} onClick={() => update("start", Math.max(0, start - 24))}>{t("previous")}</button><button disabled={start + 24 >= data.total} onClick={() => update("start", start + 24)}>{t("next")}</button></div>
        </section>
      </div>}
    </main>
  );
}
