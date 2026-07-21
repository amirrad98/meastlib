import { Link } from "react-router-dom";
import { useI18n } from "../i18n.jsx";

export default function CatalogCard({ item }) {
  const { t } = useI18n();
  return (
    <article className="catalog-card">
      <Link className="catalog-cover" to={`/item/${item.id}`} aria-label={item.title}>
        <img src={item.thumbnail} alt="" loading="lazy" />
      </Link>
      <div className="catalog-card-body">
        <p className="catalog-kicker">
          {item.type || "book"}{item.volume_label ? ` · ${item.volume_label}` : ""}
        </p>
        <h3 dir="auto"><Link to={`/item/${item.id}`}>{item.title}</Link></h3>
        {item.creator && <p className="catalog-creator" dir="auto">{item.creator}</p>}
        <p className="catalog-facts">
          {item.date && <span>{item.date}</span>}
          {item.pages > 0 && <span>{item.pages} {t("pages")}</span>}
        </p>
      </div>
    </article>
  );
}
