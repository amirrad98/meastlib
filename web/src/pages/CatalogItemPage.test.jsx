import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import CatalogItemPage from "./CatalogItemPage.jsx";
import { I18nProvider } from "../i18n.jsx";
import { fetchCatalogItem } from "../api.js";

vi.mock("../api.js", () => ({ fetchCatalogItem: vi.fn() }));

beforeEach(() => {
  localStorage.clear();
  fetchCatalogItem.mockReset();
});

test("links a newspaper publication to its complete indexed run", async () => {
  fetchCatalogItem.mockResolvedValue({
    id: "kayhan-issue", title: "کیهان — 19 بهمن 1357", type: "newspaper",
    series_title: "کیهان", collection_id: "newspaper-kayhan", issue_number: "10633",
    date_display: "19 بهمن 1357", language: "fas", pages: 9, thumbnail: "/cover.jpg",
    derivatives: {}, related_items: [], subjects: [],
  });
  render(<I18nProvider><MemoryRouter initialEntries={["/item/kayhan-issue"]}><Routes><Route path="/item/:itemId" element={<CatalogItemPage />} /></Routes></MemoryRouter></I18nProvider>);
  expect(await screen.findByRole("link", { name: "کیهان" })).toHaveAttribute("href", "/collection/newspaper-kayhan");
});
