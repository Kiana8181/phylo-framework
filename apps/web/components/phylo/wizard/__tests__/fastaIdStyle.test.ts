import { describe, expect, it } from "vitest";
import { classifyFastaHeaders } from "@/lib/fastaIdStyle";

// GCtree writes `seq3@9` in its own output but cannot read it back, so the run
// form has to ask what the number means — but only when the file uses that form.
describe("classifyFastaHeaders", () => {
  it("reports at_abundance when every header is name@N", () => {
    expect(classifyFastaHeaders(">naive@0\nACGT\n>seq3@9\nACGT\n")).toBe("at_abundance");
  });

  it("reports plain when no header contains @", () => {
    expect(classifyFastaHeaders(">naive\nACGT\n>seq3\nACGT\n")).toBe("plain");
  });

  it("reports other_at when only some headers use the form", () => {
    expect(classifyFastaHeaders(">naive@0\nACGT\n>seq3\nACGT\n")).toBe("other_at");
  });

  it("reports other_at when the suffix is not an integer", () => {
    expect(classifyFastaHeaders(">naive@0\nACGT\n>seq3@IgG\nACGT\n")).toBe("other_at");
  });

  it("ignores description text after the ID", () => {
    expect(classifyFastaHeaders(">naive@0 germline\nACGT\n>seq3@9 clone 4\nACGT\n")).toBe(
      "at_abundance",
    );
  });

  it("reports plain for input with no headers", () => {
    expect(classifyFastaHeaders("")).toBe("plain");
    expect(classifyFastaHeaders("ACGT\n")).toBe("plain");
  });

  it("handles CRLF line endings", () => {
    expect(classifyFastaHeaders(">naive@0\r\nACGT\r\n>seq3@9\r\nACGT\r\n")).toBe("at_abundance");
  });

  it("drops the final line when the read was truncated mid-header", () => {
    // ">seq3" alone would look like a plain ID and flip the verdict to other_at.
    expect(classifyFastaHeaders(">naive@0\nACGT\n>seq3", true)).toBe("at_abundance");
  });
});
