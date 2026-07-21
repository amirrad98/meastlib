import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import CatalogCard from "../components/CatalogCard.jsx";
import { fetchCatalogItem } from "../api.js";
import { useI18n } from "../i18n.jsx";

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
  const details = [[t("creator"), item.creator], [t("date"), item.date_display || item.date_published], [t("language"), item.language], [t("type"), item.type], [t("subject"), (item.subjects || []).join(" · ")], [t("collection"), item.series_title], [t("publisher"), item.publisher], [t("edition"), item.edition]];
  return <main className="public-page item-landing">
    <section className="item-hero"><div className="item-cover"><img src={item.thumbnail} alt="" /></div><div className="item-intro"><p className="eyebrow">{item.type || "book"}</p><h1 dir="auto">{item.title}</h1>{item.creator && <p className="item-byline" dir="auto">{item.creator}</p>}<p className="item-summary">{item.pages} {t("pages")} · {item.ocr_confidence != null ? `${Math.round(item.ocr_confidence * 100)}% OCR` : t("machineText")}</p><div className="item-actions"><Link className="primary-link" to={`/item/${itemId}/1`}>{t("read")}</Link>{item.derivatives?.searchable_pdf && <a href={item.derivatives.searchable_pdf}>{t("searchablePdf")}</a>}</div><form className="within-form" onSubmit={(e) => { e.preventDefault(); if (query.trim()) navigate(`/item/${itemId}/1?q=${encodeURIComponent(query.trim())}`); }}><input dir="auto" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("searchWithin")} /><button>{t("search")}</button></form></div></section>
    <section className="item-details"><h2>{t("aboutItem")}</h2><dl>{details.filter(([, value]) => value).map(([label, value]) => <div key={label}><dt>{label}</dt><dd dir="auto">{value}</dd></div>)}</dl><p className="machine-note">{t("machineText")}</p></section>
    {item.related_items?.length > 1 && <section className="catalog-section"><div className="catalog-heading"><h2>{t("relatedVolumes")}</h2></div><div className="catalog-grid">{item.related_items.map((related) => <CatalogCard item={related} key={related.id} />)}</div></section>}
  </main>;
}
