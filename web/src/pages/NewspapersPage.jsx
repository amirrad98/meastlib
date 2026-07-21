import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import CatalogCard from "../components/CatalogCard.jsx";
import { fetchCatalogItems } from "../api.js";
import { useI18n } from "../i18n.jsx";

export default function NewspapersPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const options = Object.fromEntries(params.entries());

  useEffect(() => {
    const request = { rows: 100, sort: "date", item_type: "newspaper", ...options };
    fetchCatalogItems(request).then(setData).catch((e) => setError(e.message));
  }, [params.toString()]);

  function update(key, value) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  }

  const publications = useMemo(() => {
    const groups = new Map();
    for (const item of data?.items || []) {
      const key = item.collection_id || item.series_title || item.title;
      if (!groups.has(key)) groups.set(key, { id: item.collection_id, title: item.series_title || item.title, count: 0 });
      groups.get(key).count += 1;
    }
    return Array.from(groups.values());
  }, [data]);

  return (
    <main className="public-page newspapers-page">
      <section className="newspaper-heading">
        <div>
          <p className="eyebrow">{t("newspaperArchive")}</p>
          <h1>{t("newspapers")}</h1>
          <p>{t("newspapersIntro")}</p>
        </div>
        <form className="newspaper-search" onSubmit={(event) => event.preventDefault()}>
          <label>{t("findIssue")}<input dir="auto" value={options.q || ""} onChange={(event) => update("q", event.target.value)} placeholder={t("issueSearchPlaceholder")} /></label>
          <label>{t("publication")}<select value={options.collection || ""} onChange={(event) => update("collection", event.target.value)}><option value="">{t("allPublications")}</option>{(data?.facets?.collection || []).map((entry) => <option value={entry.value} key={entry.value}>{entry.label || entry.value} ({entry.count})</option>)}</select></label>
          <label>{t("dateFrom")}<input value={options.date_from || ""} onChange={(event) => update("date_from", event.target.value)} placeholder="1357-01-01" /></label>
          <label>{t("dateTo")}<input value={options.date_to || ""} onChange={(event) => update("date_to", event.target.value)} placeholder="1357-12-29" /></label>
        </form>
      </section>

      {error && <p className="error">{error}</p>}
      {!data && !error && <p>{t("loading")}</p>}
      {data && <>
        {!params.toString() && publications.length > 0 && <section className="publication-strip" aria-label={t("publications")}>
          {publications.map((publication) => publication.id ? <Link to={`/collection/${publication.id}`} key={publication.id}><span dir="auto">{publication.title}</span><strong>{publication.count} {t("issues")}</strong></Link> : <div key={publication.title}><span dir="auto">{publication.title}</span><strong>{publication.count} {t("issues")}</strong></div>)}
        </section>}
        <div className="newspaper-results-heading"><h2>{t("issues")}</h2><p>{data.total} {t("issues")}</p></div>
        {data.items.length ? <div className="catalog-grid newspaper-grid">{data.items.map((item) => <CatalogCard item={item} key={item.id} />)}</div> : <div className="empty-state">{t("noIssues")}</div>}
      </>}
    </main>
  );
}
