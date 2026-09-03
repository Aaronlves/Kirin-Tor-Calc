export const fullWidthSyntax: Readonly<Record<string, string>> = {
  "：": ":",
  "，": ",",
  "（": "(",
  "）": ")",
  "＝": "=",
  "％": "%",
  "。": ".",
  "”": '"',
};

export interface TextReplacement {
  from: number;
  to: number;
  insert: string;
}

/** Return syntax punctuation edits while preserving quoted labels and comments. */
export function fullWidthSyntaxReplacements(line: string): TextReplacement[] {
  const result: TextReplacement[] = [];
  let quoted = false;
  let curlyQuoted = false;
  let escaped = false;
  for (let index = 0; index < line.length;) {
    const point = line.codePointAt(index);
    if (point === undefined) break;
    const character = String.fromCodePoint(point);
    const width = character.length;
    if (curlyQuoted) {
      if (character === "”") {
        result.push({ from: index, to: index + width, insert: '"' });
        curlyQuoted = false;
      }
      index += width;
      continue;
    }
    if (quoted) {
      if (character === '"' && !escaped) quoted = false;
      escaped = character === "\\" && !escaped;
      if (character !== "\\") escaped = false;
      index += width;
      continue;
    }
    if (character === "/" && line[index + 1] === "/") break;
    if (character === '"') {
      quoted = true;
      index += width;
      continue;
    }
    if (character === "“") {
      result.push({ from: index, to: index + width, insert: '"' });
      curlyQuoted = true;
      index += width;
      continue;
    }
    const replacement = fullWidthSyntax[character];
    if (replacement) result.push({ from: index, to: index + width, insert: replacement });
    index += width;
  }
  return result;
}

export function replaceFullWidthSyntax(line: string): string {
  let rendered = line;
  for (const change of fullWidthSyntaxReplacements(line).reverse()) {
    rendered = rendered.slice(0, change.from) + change.insert + rendered.slice(change.to);
  }
  return rendered;
}
