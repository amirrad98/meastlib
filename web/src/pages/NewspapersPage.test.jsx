import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import NewspapersPage from "./NewspapersPage.jsx";
import { I18nProvider } from "../i18n.jsx";
import { fetchCatalogItems } from "../api.js";

vi.mock("../api.js", () => ({ fetchCatalogItems: vi.fn() }));

beforeEach(() => {
  localStorage.clear();
  fetchCatalogItems.mockReset();
});

test("loads newspaper issues as publication records", async () => {
  fetchCatalogItems.mockResolvedValue({
    total: 2,
    items: [
      { id: "kayhan-1", type: "newspaper", title: "کیهان — 18 بهمن 1357", series_title: "کیهان", collection_id: "newspaper-kayhan", issue_number: "10632", date: "18 بهمن 1357", pages: 9, thumbnail: "/cover.jpg" },
      { id: "kayhan-2", type: "newspaper", title: "کیهان — 19 بهمن 1357", series_title: "کیهان", collection_id: "newspaper-kayhan", issue_number: "10633", date: "19 بهمن 1357", pages: 9, thumbnail: "/cover.jpg" },
    ],
    facets: { collection: [{ value: "newspaper-kayhan", label: "کیهان", count: 2 }] },
  });
  render(<I18nProvider><MemoryRouter initialEntries={["/newspapers"]}><NewspapersPage /></MemoryRouter></I18nProvider>);
  await waitFor(() => expect(fetchCatalogItems).toHaveBeenCalledWith({ rows: 100, sort: "date", item_type: "newspaper" }));
  expect(screen.getByRole("heading", { name: "Newspapers" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { name: "کیهان" })).toHaveLength(2);
  expect(screen.getByText("Issue 10632")).toBeInTheDocument();
});
