import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import SearchPage from "./SearchPage.jsx";
import { I18nProvider } from "../i18n.jsx";
import { searchPages } from "../api.js";

vi.mock("../api.js", () => ({
  SERVICES_AVAILABLE: true,
  pageNumber: (value) => Number(String(value).replace("page-", "")) || 1,
  searchPages: vi.fn(),
}));

beforeEach(() => {
  localStorage.clear();
  searchPages.mockReset();
});

test("runs a bookmarked search and renders grouped work results", async () => {
  searchPages.mockResolvedValue({
    total: 1, total_documents: 4, facets: {},
    hits: [{ item_id: "book-1", title: "داستان سیاوش", creator: "فردوسی", page_hit_count: 3, catalog_match: true, thumbnail: "/cover.jpg", page_hits: [{ id: "book-1/page-0081", page: "page-0081", snippets: [{ text: "<em>سیاوش</em>" }] }] }],
  });
  render(<I18nProvider><MemoryRouter initialEntries={["/search?q=سیاوش"]}><SearchPage /></MemoryRouter></I18nProvider>);
  await waitFor(() => expect(searchPages).toHaveBeenCalledWith("سیاوش", {}));
  expect(screen.getByRole("heading", { name: "داستان سیاوش" })).toBeInTheDocument();
  expect(screen.getByText("Page 81")).toBeInTheDocument();
});

test("shows a useful no-results state", async () => {
  searchPages.mockResolvedValue({ total: 0, total_documents: 0, facets: {}, hits: [] });
  render(<I18nProvider><MemoryRouter initialEntries={["/search?q=missing"]}><SearchPage /></MemoryRouter></I18nProvider>);
  expect(await screen.findByText("No results matched your search.")).toBeInTheDocument();
});

test("restores search filters and advances grouped-result pagination", async () => {
  searchPages.mockResolvedValue({ total: 21, total_documents: 30, facets: { language: [{ value: "fas", count: 21 }] }, hits: [] });
  render(<I18nProvider><MemoryRouter initialEntries={["/search?q=book&language=fas&start=10"]}><SearchPage /></MemoryRouter></I18nProvider>);
  await waitFor(() => expect(searchPages).toHaveBeenCalledWith("book", { language: "fas", start: "10" }));
  expect(screen.getByLabelText("Language")).toHaveValue("fas");
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await waitFor(() => expect(searchPages).toHaveBeenLastCalledWith("book", { language: "fas", start: "20" }));
});
