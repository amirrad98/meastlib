import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import BrowsePage from "./BrowsePage.jsx";
import { I18nProvider } from "../i18n.jsx";
import { fetchCatalogItems } from "../api.js";

vi.mock("../api.js", () => ({ fetchCatalogItems: vi.fn() }));

beforeEach(() => {
  localStorage.clear();
  fetchCatalogItems.mockReset();
});

test("restores catalog filters and renders a paginated item card", async () => {
  fetchCatalogItems.mockResolvedValue({
    total: 25,
    items: [{ id: "book-1", title: "کتاب", creator: "نویسنده", language: "fas", pages: 10, thumbnail: "/cover.jpg" }],
    facets: { language: [{ value: "fas", count: 25 }], type: [], collection: [], creator: [], subject: [] },
  });
  render(<I18nProvider><MemoryRouter initialEntries={["/browse?language=fas&start=24"]}><BrowsePage /></MemoryRouter></I18nProvider>);
  await waitFor(() => expect(fetchCatalogItems).toHaveBeenCalledWith({ rows: 24, language: "fas", start: "24" }));
  expect(screen.getByRole("heading", { name: "کتاب" })).toBeInTheDocument();
  expect(screen.getByLabelText("Language")).toHaveValue("fas");
  expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
});
