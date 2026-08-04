import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import NavBar from "../components/NavBar";

describe("NavBar", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders navigation links to /, /history and /settings", () => {
    render(
      <MemoryRouter>
        <NavBar />
      </MemoryRouter>
    );

    expect(screen.getByRole("link", { name: "首页" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("link", { name: "历史" }).getAttribute("href")).toBe("/history");
    expect(screen.getByRole("link", { name: "设置" }).getAttribute("href")).toBe("/settings");
  });

  it("links the brand to the home page", () => {
    render(
      <MemoryRouter>
        <NavBar />
      </MemoryRouter>
    );

    expect(
      screen.getByRole("link", { name: /PR Review Assistant/ }).getAttribute("href")
    ).toBe("/");
  });
});
