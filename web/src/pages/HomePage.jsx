import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import CatalogCard from "../components/CatalogCard.jsx";
import { fetchCatalogItems, IS_GITHUB_PAGES, SERVICES_AVAILABLE } from "../api.js";
import { useI18n } from "../i18n.jsx";

export default function HomePage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [catalog, setCatalog] = useState({ items: [], facets: {} });
  const [error, setError] = useState("");
  useEffect(() => {
    if (SERVICES_AVAILABLE) fetchCatalogItems({ rows: 8, sort: "recent" }).then(setCatalog).catch((e) => setError(e.message));
  }, []);
  function submit(event) {
    event.preventDefault();
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`);
  }
  const collections = (catalog.facets?.collection || []).slice(0, 6);
  return (
    <main className="public-page home-page">
      {IS_GITHUB_PAGES && !SERVICES_AVAILABLE && (
        <section className="pages-notice"><strong>Static project preview</strong><p>Connect a public service URL to browse and search the collection.</p></section>
      )}
      <section className="hero-panel">
        <p className="eyebrow">{t("explore")}</p>
        <h1>{t("library")}</h1>
        <p>{t("hero")}</p>
        <form className="hero-search" onSubmit={submit}>
          <input dir="auto" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchPlaceholder")} disabled={!SERVICES_AVAILABLE} />
          <button disabled={!SERVICES_AVAILABLE}>{t("search")}</button>
        </form>
      </section>
      {error && <p className="error">{error}</p>}
      {SERVICES_AVAILABLE && (
        <>
          <section className="catalog-section">
            <div className="catalog-heading"><h2>{t("recentlyAdded")}</h2><Link to="/browse">{t("viewAll")}</Link></div>
            <div className="catalog-grid">{catalog.items.map((item) => <CatalogCard item={item} key={item.id} />)}</div>
          </section>
          {collections.length > 0 && (
            <section className="catalog-section collection-section">
              <div className="catalog-heading"><h2>{t("featuredCollections")}</h2></div>
              <div className="collection-links">{collections.map((entry) => <Link key={entry.value} to={`/collection/${entry.value}`}><span dir="auto" className="collection-name">{entry.label || entry.value}</span><span>{entry.count}</span></Link>)}</div>
            </section>
          )}
        </>
      )}
    </main>
  );
}
