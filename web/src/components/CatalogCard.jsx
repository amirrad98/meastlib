import { Link } from "react-router-dom";
import { useI18n } from "../i18n.jsx";
import { AuthorLinks, PublisherLink } from "./AuthorityLinks.jsx";

export default function CatalogCard({ item }) {
  const { t } = useI18n();
  const isNewspaper = item.type === "newspaper";
  return (
    <article className={`catalog-card ${isNewspaper ? "newspaper-card" : ""}`}>
      <Link className="catalog-cover" to={`/item/${item.id}`} aria-label={item.title}>
        <img src={item.thumbnail} alt="" loading="lazy" />
      </Link>
      <div className="catalog-card-body">
        <p className="catalog-kicker">
          {isNewspaper ? `${t("issue")}${item.issue_number ? ` ${item.issue_number}` : ""}` : `${item.type || "book"}${item.volume_label ? ` · ${item.volume_label}` : ""}`}
        </p>
        <h3 dir="auto"><Link to={`/item/${item.id}`}>{isNewspaper ? (item.series_title || item.title) : item.title}</Link></h3>
        {isNewspaper && item.date && <p className="catalog-issue-date" dir="auto">{item.date}</p>}
        {(item.authors?.length || item.creator) && <p className="catalog-creator"><AuthorLinks authors={item.authors} fallback={item.creator} /></p>}
        {(item.publisher_authority || item.publisher) && <p className="catalog-publisher"><PublisherLink publisher={item.publisher_authority} fallback={item.publisher} /></p>}
        <p className="catalog-facts">
          {!isNewspaper && item.date && <span>{item.date}</span>}
          {item.pages > 0 && <span>{item.pages} {t("pages")}</span>}
        </p>
      </div>
    </article>
  );
}
