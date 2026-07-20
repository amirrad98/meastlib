import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  IS_GITHUB_PAGES,
  SERVICES_AVAILABLE,
  searchPages,
  pageNumber,
} from "../api.js";

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState(searchParams.get("q") || "");
  const [results, setResults] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function run(e) {
    e?.preventDefault();
    const query = q.trim();
    if (!query) return;
    setSearchParams({ q: query });
    setLoading(true);
    setError("");
    try {
      setResults(await searchPages(query));
    } catch (err) {
      setError(`Search failed — are the services running? (${err.message})`);
      setResults(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="search-page">
      {IS_GITHUB_PAGES && !SERVICES_AVAILABLE && (
        <section className="pages-notice">
          <strong>Static project preview</strong>
          <p>
            GitHub Pages hosts this interface, while search, OCR, IIIF images,
            and book administration run in the local Docker stack.
          </p>
          <a href="https://github.com/amirrad98/meastlib">View setup instructions on GitHub</a>
        </section>
      )}
      <form className="searchbar" onSubmit={run}>
        <input
          dir="auto"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search inside books — ابحث في الكتب — جستجو در کتاب‌ها"
          disabled={!SERVICES_AVAILABLE}
          autoFocus
        />
        <button type="submit" disabled={loading || !SERVICES_AVAILABLE}>
          {loading ? "…" : "Search"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {results && (
        <>
          <p className="count">
            {results.total} matching page{results.total === 1 ? "" : "s"}
          </p>
          <ul className="hits">
            {results.hits.map((hit) => (
              <li key={hit.id}>
                <Link
                  className="hit"
                  to={`/item/${hit.itemId}/${pageNumber(hit.page)}`}
                >
                  <div className="hit-meta">
                    <span className="hit-title">{hit.title}</span>
                    {hit.creator && <span> · {hit.creator}</span>}
                    {hit.date && <span> · {hit.date}</span>}
                    <span> · p. {pageNumber(hit.page)}</span>
                  </div>
                  {hit.snippets.map((s, i) => (
                    <p
                      key={i}
                      className="snippet"
                      dir="rtl"
                      dangerouslySetInnerHTML={{ __html: s }}
                    />
                  ))}
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}

      {!results && !error && SERVICES_AVAILABLE && (
        <p className="intro">
          Full-text search across digitized Arabic and Persian books,
          newspapers, and historical documents. Results link to the exact page.
        </p>
      )}
    </main>
  );
}
