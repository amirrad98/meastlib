import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import CatalogCard from "../components/CatalogCard.jsx";
import { fetchCollection } from "../api.js";
import { useI18n } from "../i18n.jsx";

export default function CollectionPage() {
  const { collectionId } = useParams();
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => { fetchCollection(collectionId).then(setData).catch((e) => setError(e.message)); }, [collectionId]);
  const isNewspaper = data?.items?.[0]?.type === "newspaper";
  return <main className="public-page collection-page">{error ? <p className="error">{error}</p> : !data ? <p>{t("loading")}</p> : <><div className="page-heading"><p className="eyebrow">{t(isNewspaper ? "newspaperArchive" : "featuredCollections")}</p><h1 dir="auto">{data.title}</h1><p>{data.items.length} {t(isNewspaper ? "issues" : "works")}</p></div><div className={`catalog-grid ${isNewspaper ? "newspaper-grid" : ""}`}>{data.items.map((item) => <CatalogCard item={item} key={item.id} />)}</div></>}</main>;
}
