export type NewickNode = {
  name?: string;
  length?: number;
  children?: NewickNode[];
  // layout fields (computed later)
  x?: number;
  y?: number;
};

export function parseNewick(s: string): NewickNode {
  // Based on the classic compact parser (adapted + typed)
  let i = 0;
  function eatWhitespace() {
    while (/\s/.test(s[i])) i++;
  }
  function parseSubtree(): NewickNode {
    eatWhitespace();
    const node: NewickNode = {};
    if (s[i] === "(") {
      i++; // consume '('
      node.children = [];
      while (true) {
        node.children.push(parseSubtree());
        eatWhitespace();
        if (s[i] === ",") {
          i++; // next child
        } else if (s[i] === ")") {
          i++; // end children
          break;
        } else {
          throw new Error("Unexpected character in Newick: " + s[i]);
        }
      }
    }
    // name
    eatWhitespace();
    let name = "";
    while (i < s.length && ![":", ",", ")", ";"].includes(s[i])) {
      name += s[i++];
    }
    name = name.trim();
    if (name) node.name = name;

    // branch length
    if (s[i] === ":") {
      i++;
      let lenStr = "";
      while (i < s.length && ![",", ")", ";"].includes(s[i])) {
        lenStr += s[i++];
      }
      const v = parseFloat(lenStr);
      if (!Number.isNaN(v)) node.length = v;
    }
    eatWhitespace();
    return node;
  }

  const tree = parseSubtree();
  // optional trailing semicolon
  if (s[i] === ";") i++;
  return tree;
}

export function cleanNewick(s: string): string {
  // strip R print prefix/suffix if present
  let x = s.trim();
  x = x.replace(/^\[\d+\]\s*"/, ""); // remove `[1] "`
  x = x.replace(/"\s*$/, ""); // remove trailing quote
  // ensure trailing semicolon (optional for our parser, but nice to have)
  if (!x.endsWith(";")) x += ";";
  return x;
}
