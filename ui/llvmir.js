// ---------------------------------------------------------------------------
// Pure JavaScript LLVM IR Parser Fallback (For GitHub Pages / Static hosting)
// Matches the exact text-splitting and declaration derivation logic of
// llmcompile/phases/p1_parse.py, shared by both Phase 1 and Phase 2 views.
// ---------------------------------------------------------------------------

export function functionName(line) {
  const match = line.match(/@(?:"([^"]*)"|([\w.$\-]+))\s*\(/);
  if (!match) {
    throw new Error(`Could not parse function name from: ${line}`);
  }
  return match[1] !== undefined ? match[1] : match[2];
}

export function signatureToDeclaration(signatureLine) {
  let sig = signatureLine.trim();
  if (sig.endsWith("{")) {
    sig = sig.slice(0, -1).trimEnd();
  }

  // Remove metadata attachments: ' !dbg !12'
  sig = sig.replace(/\s+!\w+\s+!\d+/g, "");

  const definitionOnlyClauses = [
    " personality ",
    " prologue ",
    " prefix ",
    " gc ",
    " section ",
    " comdat"
  ];

  let earliest = sig.length;
  for (const clause of definitionOnlyClauses) {
    const idx = sig.indexOf(clause);
    if (idx !== -1) {
      earliest = Math.min(earliest, idx);
    }
  }
  sig = sig.slice(0, earliest).trimEnd();

  if (!sig.startsWith("define")) {
    throw new Error(`Expected a \`define\` signature, got: ${signatureLine}`);
  }
  return "declare" + sig.slice("define".length);
}

export function splitModuleText(irText) {
  const lines = irText.split(/\r?\n/);
  const preambleLines = [];
  const blocks = [];

  let i = 0;
  const n = lines.length;
  while (i < n) {
    const line = lines[i];
    if (line.trimStart().startsWith("define ")) {
      const signature = line;
      const body = [line];
      i++;
      let closed = false;
      while (i < n) {
        body.push(lines[i]);
        if (lines[i].trimEnd() === "}") {
          closed = true;
          break;
        }
        i++;
      }
      if (!closed) {
        throw new Error(`Unterminated function body starting at: ${signature.trim()}`);
      }
      blocks.push({
        name: functionName(signature),
        signature: signature,
        text: body.join("\n")
      });
      i++;
    } else {
      preambleLines.push(line);
      i++;
    }
  }
  return { preambleLines, blocks };
}

export function parseModuleJS(irText) {
  const { preambleLines, blocks } = splitModuleText(irText);
  const basePreamble = preambleLines.join("\n").trim();

  const declarations = {};
  for (const block of blocks) {
    declarations[block.name] = signatureToDeclaration(block.signature);
  }

  const functions = [];
  for (const block of blocks) {
    const name = block.name;
    const otherDecls = Object.entries(declarations)
      .filter(([fnName]) => fnName !== name)
      .map(([, decl]) => decl);

    const parts = [basePreamble];
    if (otherDecls.length > 0) {
      parts.push("; --- declarations of sibling functions ---");
      parts.push(...otherDecls);
    }
    parts.push("");
    parts.push(block.text);
    const standaloneIr = parts.filter(p => p !== null).join("\n").trim() + "\n";
    functions.push({ name, original_ir: standaloneIr });
  }

  return { preamble: basePreamble, functions };
}
