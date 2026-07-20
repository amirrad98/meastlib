import { Routes, Route, Link } from "react-router-dom";
import SearchPage from "./pages/SearchPage.jsx";
import ItemPage from "./pages/ItemPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">meastlib</Link>
        <span className="tagline">Middle East Digital Library</span>
        <nav className="topnav">
          <Link to="/">Search</Link>
          <Link to="/admin">Admin</Link>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<SearchPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/item/:itemId" element={<ItemPage />} />
        <Route path="/item/:itemId/:page" element={<ItemPage />} />
      </Routes>
    </div>
  );
}
