import { Link } from "react-router-dom";

export function AuthorLinks({ authors = [], fallback = "" }) {
  if (!authors.length) return fallback ? <span dir="auto">{fallback}</span> : null;
  return <span className="authority-links" dir="auto">{authors.map((author, index) => <span key={author.id}>{index > 0 && <span aria-hidden="true"> · </span>}<Link to={author.href || `/authors/${author.id}`}>{author.name}</Link></span>)}</span>;
}

export function PublisherLink({ publisher, fallback = "" }) {
  if (!publisher) return fallback ? <span dir="auto">{fallback}</span> : null;
  return <Link className="authority-link" dir="auto" to={publisher.href || `/publishers/${publisher.id}`}>{publisher.name}</Link>;
}
