import { Routes, Route, Link, useLocation } from "react-router-dom";
import HomePage from "./pages/HomePage.jsx";
import BrowsePage from "./pages/BrowsePage.jsx";
import SearchPage from "./pages/SearchPage.jsx";
import ItemPage from "./pages/ItemPage.jsx";
import CatalogItemPage from "./pages/CatalogItemPage.jsx";
import CollectionPage from "./pages/CollectionPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import CorrectionPage from "./pages/CorrectionPage.jsx";
import { PUBLIC_PORTAL, SERVICES_AVAILABLE } from "./api.js";
import { useI18n } from "./i18n.jsx";

export default function App() {
  const { locale, setLocale, dir, t } = useI18n();
  const location = useLocation();
  const isAdmin = location.pathname.startsWith("/admin");
  return (
    <div className={`app ${isAdmin ? "admin-shell" : "public-shell"}`} dir={isAdmin ? "ltr" : dir} lang={isAdmin ? "en" : locale}>
      <header className="topbar">
        <Link to="/" className="brand">meastlib</Link>
        <span className="tagline">{isAdmin ? "Middle East Digital Library" : t("library")}</span>
        <nav className="topnav">
          <Link to="/">{isAdmin ? "Home" : t("home")}</Link>
          <Link to="/browse">{isAdmin ? "Browse" : t("browse")}</Link>
          <Link to="/search">{isAdmin ? "Search" : t("search")}</Link>
          {SERVICES_AVAILABLE && !PUBLIC_PORTAL && <Link to="/admin">{isAdmin ? "Admin" : t("admin")}</Link>}
          {!isAdmin && <button className="locale-toggle" onClick={() => setLocale(locale === "en" ? "fa" : "en")} aria-label="Switch interface language">{locale === "en" ? "فارسی" : "English"}</button>}
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/browse" element={<BrowsePage />} />
        <Route path="/search" element={<SearchPage />} />
        {!PUBLIC_PORTAL && <Route path="/admin" element={<AdminPage />} />}
        {!PUBLIC_PORTAL && <Route path="/admin/correct/:itemId/:page" element={<CorrectionPage />} />}
        <Route path="/collection/:collectionId" element={<CollectionPage />} />
        <Route path="/item/:itemId" element={<CatalogItemPage />} />
        <Route path="/item/:itemId/:page" element={<ItemPage />} />
      </Routes>
    </div>
  );
}
