// Step-zero smoke test for the web (jsdom) project: App renders, and the browser sha256 adapter matches the §5 vectors.
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { App } from "../../../src/web/App.js";
import { sha256 } from "../../../src/web/hash.js";

describe("web step zero", () => {
  it("renders the placeholder heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Example Map Live" })).toBeInTheDocument();
  });

  it("browser sha256 adapter matches the §5 vectors", () => {
    expect(sha256("")).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    expect(sha256("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });

  it("the setup file stubbed WebSocket and crypto.randomUUID", () => {
    expect(typeof WebSocket).toBe("function");
    expect(typeof crypto.randomUUID()).toBe("string");
  });
});
