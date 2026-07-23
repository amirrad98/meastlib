import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import ArchivePage from "./ArchivePage.jsx";
import { I18nProvider } from "../i18n.jsx";
import { fetchArchiveIndex } from "../api.js";

vi.mock("../api.js", () => ({ fetchArchiveIndex: vi.fn(), catalogDatasetUrl: (path) => path }));

beforeEach(() => {
  localStorage.clear();
  fetchArchiveIndex.mockReset();
});

test("renders linked author and publisher indexes and filters names", async () => {
  fetchArchiveIndex.mockResolvedValue({
    summary: { items: 2, pages: 320, authors: 2, publishers: 1, collections: 0 },
    dataset_url: "/api/catalog/dataset",
    authors: [
      { id: "author-one", name: "Author One", href: "/authors/author-one", work_count: 2 },
      { id: "author-two", name: "Author Two", href: "/authors/author-two", work_count: 1 },
    ],
    publishers: [{ id: "press-one", name: "Press One", href: "/publishers/press-one", work_count: 2 }],
    collections: [],
  });
  render(<I18nProvider><MemoryRouter><ArchivePage /></MemoryRouter></I18nProvider>);
  expect(await screen.findByRole("heading", { name: "Archive index" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Author One" })).toHaveAttribute("href", "/authors/author-one");
  expect(screen.getByRole("link", { name: "Press One" })).toHaveAttribute("href", "/publishers/press-one");
  expect(screen.getByRole("link", { name: "Download full dataset (JSON)" })).toHaveAttribute("href", "/api/catalog/dataset");
  fireEvent.change(screen.getByLabelText("Authors search"), { target: { value: "Two" } });
  expect(screen.queryByRole("link", { name: "Author One" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Author Two" })).toBeInTheDocument();
});
