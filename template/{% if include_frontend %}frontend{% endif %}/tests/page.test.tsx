// Smoke test for the landing page — the frontend counterpart to the backend's
// health-check test. Proves the render path works end to end (component → DOM).
//
// This is the pattern to copy: CLAUDE.md requires a test for every new behaviour,
// so add a sibling `*.test.tsx` here whenever you add a component.
//
// Deliberately asserts structure, not the project name: interpolating the name
// would make the formatted line length depend on it, so a long project name could
// fail `prettier --check` on a freshly generated repo.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Home from "../app/page";

// Testing Library only auto-registers cleanup when Vitest `globals` are enabled;
// do it explicitly so each test starts from an empty DOM.
afterEach(cleanup);

describe("landing page", () => {
  it("renders a non-empty top-level heading", () => {
    render(<Home />);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBeTruthy();
  });

  it("links to the backend health check", () => {
    render(<Home />);
    expect(screen.getByRole("link", { name: "/health" })).toBeDefined();
  });
});
