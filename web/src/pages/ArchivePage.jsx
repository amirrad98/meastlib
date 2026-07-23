import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { catalogDatasetUrl, fetchArchiveIndex } from "../api.js";
import { useI18n } from "../i18n.jsx";

function AuthorityIndex({ title, entries, emptyText }) {
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const value = query.trim().toLocaleLowerCase();
    return value ? entries.filter((entry) => entry.name.toLocaleLowerCase().includes(value)) : entries;
  }, [entries, query]);
  return <section className="authority-index">
    <div className="authority-index-heading"><h2>{title}</h2><span>{entries.length}</span></div>
    <input dir="auto" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={emptyText} aria-label={`${title} search`} />
    <ol>{visible.map((entry) => <li key={entry.id}><Link dir="auto" to={entry.href}>{entry.name}</Link><span>{entry.work_count}</span></li>)}</ol>
  </section>;
}

export default function ArchivePage() {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { fetchArchiveIndex().then(setData).catch((value) => setError(value.message)); }, []);
  if (error) return <main className="public-page"><p className="error">{error}</p></main>;
  if (!data) return <main className="public-page"><p>{t("loading")}</p></main>;
  const summary = data.summary || {};
  return <main className="public-page archive-page">
    <div className="archive-heading"><div><p className="eyebrow">{t("researchIndex")}</p><h1>{t("archiveIndex")}</h1><p>{t("archiveIntro")}</p></div><a className="dataset-download" href={catalogDatasetUrl(data.dataset_url)}>{t("downloadDataset")}</a></div>
    <dl className="archive-summary">
      <div><dt>{t("works")}</dt><dd>{summary.items || 0}</dd></div>
      <div><dt>{t("pages")}</dt><dd>{summary.pages || 0}</dd></div>
      <div><dt>{t("authors")}</dt><dd>{summary.authors || 0}</dd></div>
      <div><dt>{t("publishers")}</dt><dd>{summary.publishers || 0}</dd></div>
      <div><dt>{t("collections")}</dt><dd>{summary.collections || 0}</dd></div>
    </dl>
    <div className="authority-indexes">
      <AuthorityIndex title={t("authors")} entries={data.authors || []} emptyText={t("filterAuthors")} />
      <AuthorityIndex title={t("publishers")} entries={data.publishers || []} emptyText={t("filterPublishers")} />
    </div>
    {!!data.collections?.length && <section className="catalog-section"><div className="catalog-heading"><h2>{t("collections")}</h2></div><div className="collection-links">{data.collections.map((entry) => <Link key={entry.id} to={entry.href}><span dir="auto" className="collection-name">{entry.title}</span><span>{entry.work_count}</span></Link>)}</div></section>}
  </main>;
}
