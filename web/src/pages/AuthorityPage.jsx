import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import CatalogCard from "../components/CatalogCard.jsx";
import { fetchAuthority } from "../api.js";
import { useI18n } from "../i18n.jsx";

export default function AuthorityPage({ kind }) {
  const { authorityId } = useParams();
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { setData(null); setError(""); fetchAuthority(kind, authorityId).then(setData).catch((value) => setError(value.message)); }, [kind, authorityId]);
  if (error) return <main className="public-page"><p className="error">{error}</p></main>;
  if (!data) return <main className="public-page"><p>{t("loading")}</p></main>;
  return <main className="public-page authority-page"><div className="page-heading"><p className="eyebrow">{t(kind === "authors" ? "authorIndex" : "publisherIndex")}</p><h1 dir="auto">{data.name}</h1><p>{data.work_count} {t("works")}</p></div><div className="catalog-grid">{data.items.map((item) => <CatalogCard item={item} key={item.id} />)}</div></main>;
}
