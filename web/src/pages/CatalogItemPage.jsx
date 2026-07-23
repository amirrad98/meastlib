import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import CatalogCard from "../components/CatalogCard.jsx";
import { fetchCatalogItem } from "../api.js";
import { useI18n } from "../i18n.jsx";
import { AuthorLinks, PublisherLink } from "../components/AuthorityLinks.jsx";

export default function CatalogItemPage() {
  const { itemId } = useParams();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  useEffect(() => { fetchCatalogItem(itemId).then(setItem).catch((e) => setError(e.message)); }, [itemId]);
  if (error) return <main className="public-page"><p className="error">{error}</p></main>;
  if (!item) return <main className="public-page"><p>{t("loading")}</p></main>;
  const isNewspaper = item.type === "newspaper";
  const collectionHref = item.collection_id ? `/collection/${item.collection_id}` : "";
  const details = [
    { label: t("publication"), value: isNewspaper ? item.series_title : "", href: collectionHref },
    { label: t("issueNumber"), value: item.issue_number },
    { label: t("date"), value: item.date_display || item.date_published },
    { label: t("language"), value: item.language },
    { label: t("type"), value: item.type },
    { label: t("subject"), value: (item.subjects || []).join(" · ") },
    { label: t("collection"), value: isNewspaper ? "" : item.series_title, href: collectionHref },
    { label: t("edition"), value: item.edition },
  ];
  return <main className="public-page item-landing">
    <section className={`item-hero ${isNewspaper ? "newspaper-item-hero" : ""}`}><div className="item-cover"><img src={item.thumbnail} alt="" /></div><div className="item-intro"><p className="eyebrow">{isNewspaper ? `${t("issue")}${item.issue_number ? ` ${item.issue_number}` : ""}` : (item.type || "book")}</p><h1 dir="auto">{isNewspaper ? (item.series_title || item.title) : item.title}</h1>{isNewspaper && <p className="issue-date" dir="auto">{item.date_display || item.date_published}</p>}{(item.authors?.length || item.creator) && <p className="item-byline"><AuthorLinks authors={item.authors} fallback={item.creator} /></p>}<p className="item-summary">{item.pages} {t("pages")} · {item.ocr_confidence != null ? `${Math.round(item.ocr_confidence * 100)}% OCR` : t("machineText")}</p><div className="item-actions"><Link className="primary-link" to={`/item/${itemId}/1`}>{t("read")}</Link>{item.derivatives?.searchable_pdf && <a href={item.derivatives.searchable_pdf}>{t("searchablePdf")}</a>}</div><form className="within-form" onSubmit={(e) => { e.preventDefault(); if (query.trim()) navigate(`/item/${itemId}/1?q=${encodeURIComponent(query.trim())}`); }}><input dir="auto" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t(isNewspaper ? "searchWithinIssue" : "searchWithin")} /><button>{t("search")}</button></form></div></section>
    <section className="item-details"><h2>{t("aboutItem")}</h2><dl>{(item.authors?.length || item.creator) && <div><dt>{t("creator")}</dt><dd><AuthorLinks authors={item.authors} fallback={item.creator} /></dd></div>}{(item.publisher_authority || item.publisher) && <div><dt>{t("publisher")}</dt><dd><PublisherLink publisher={item.publisher_authority} fallback={item.publisher} /></dd></div>}{details.filter(({ value }) => value).map(({ label, value, href }) => <div key={label}><dt>{label}</dt><dd dir="auto">{href ? <Link className="index-link" to={href}>{value}</Link> : value}</dd></div>)}</dl><p className="machine-note">{t("machineText")}</p></section>
    {item.related_items?.length > 1 && <section className="catalog-section"><div className="catalog-heading"><h2>{t(isNewspaper ? "relatedIssues" : "relatedVolumes")}</h2></div><div className={`catalog-grid ${isNewspaper ? "newspaper-grid" : ""}`}>{item.related_items.map((related) => <CatalogCard item={related} key={related.id} />)}</div></section>}
  </main>;
}
