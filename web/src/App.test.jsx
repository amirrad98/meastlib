import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";
import { I18nProvider } from "./i18n.jsx";

vi.mock("openseadragon", () => ({ default: () => ({}) }));

beforeEach(() => {
  localStorage.clear();
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ total: 0, items: [], facets: { collection: [] } }),
  });
});

test("switches public navigation to persistent Persian RTL labels", async () => {
  render(<I18nProvider><MemoryRouter initialEntries={["/"]}><App /></MemoryRouter></I18nProvider>);
  await waitFor(() => expect(global.fetch).toHaveBeenCalled());
  fireEvent.click(screen.getByRole("button", { name: "Switch interface language" }));
  expect(screen.getByRole("link", { name: "خانه" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "مرور آثار" })).toBeInTheDocument();
  expect(document.querySelector(".app")).toHaveAttribute("dir", "rtl");
  expect(localStorage.getItem("meastlib-locale")).toBe("fa");
});
