import type {
  AuthoringBuiltin,
  AuthoringIndex,
  AuthoringLocation,
  AuthoringReference,
  AuthoringSymbol,
} from "./types";

export const emptyAuthoringIndex: AuthoringIndex = { symbols: [], references: [], builtins: [] };

export interface AuthoringTarget {
  id: string;
  symbol?: AuthoringSymbol;
  builtin?: AuthoringBuiltin;
  reference?: AuthoringReference;
  definition?: AuthoringLocation;
}

function contains(location: AuthoringLocation, key: string, line: number, column: number): boolean {
  return location.key === key
    && location.line === line
    && column >= location.column
    && column <= location.end_column;
}

export function authoringTargetAt(
  index: AuthoringIndex,
  key: string,
  line: number,
  column: number,
): AuthoringTarget | null {
  const symbol = index.symbols.find((item) => contains(item.definition, key, line, column));
  if (symbol) return { id: symbol.id, symbol, definition: symbol.definition };
  const reference = index.references.find((item) => contains(item.location, key, line, column));
  if (!reference) return null;
  const targetSymbol = index.symbols.find((item) => item.id === reference.symbol_id);
  const builtin = index.builtins.find((item) => item.id === reference.symbol_id);
  return {
    id: reference.symbol_id,
    symbol: targetSymbol,
    builtin,
    reference,
    definition: targetSymbol?.definition,
  };
}

export function documentOutline(index: AuthoringIndex, key: string): AuthoringSymbol[] {
  return index.symbols.filter((item) => item.outline && item.definition.key === key);
}

export function referencesFor(index: AuthoringIndex, symbolId: string): AuthoringReference[] {
  return index.references.filter((item) => item.symbol_id === symbolId);
}

export function symbolFor(index: AuthoringIndex, symbolId: string | null | undefined): AuthoringSymbol | null {
  if (!symbolId) return null;
  return index.symbols.find((item) => item.id === symbolId) ?? null;
}

export function codePointColumn(lineText: string, utf16Offset: number): number {
  return Array.from(lineText.slice(0, utf16Offset)).length + 1;
}

export function utf16OffsetForColumn(lineText: string, column: number): number {
  return Array.from(lineText).slice(0, Math.max(0, column - 1)).join("").length;
}
