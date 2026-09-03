import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Box,
  Button,
  Code,
  Group,
  ScrollArea,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { Check, Copy, Search } from "lucide-react";

import rawSections from "../syntax-reference.json";
import rawCatalog from "../syntax-reference-catalog.json";

interface SyntaxReferenceSection {
  id: string;
  title: string;
  summary: string;
  keywords: string[];
  rules: string[];
  exampleTitle: string;
  code: string;
}

interface SyntaxReferenceField {
  name: string;
  requirement: string;
  value: string;
  default: string;
  description: string;
}

interface SyntaxReferenceSymbol {
  id: string;
  name: string;
  kind: string;
  signature: string;
  summary: string;
  context: string;
  fields: SyntaxReferenceField[];
  notes?: string[];
}

interface SyntaxReferenceCatalogSection {
  sectionId: string;
  symbols: SyntaxReferenceSymbol[];
}

const sections = rawSections as SyntaxReferenceSection[];
const catalogSections = rawCatalog as SyntaxReferenceCatalogSection[];
const catalogBySection = new Map(
  catalogSections.map((section) => [section.sectionId, section.symbols]),
);
const totalCatalogSymbols = catalogSections.reduce(
  (count, section) => count + section.symbols.length,
  0,
);

function searchableSymbolText(symbol: SyntaxReferenceSymbol): string {
  return [
    symbol.id,
    symbol.name,
    symbol.kind,
    symbol.signature,
    symbol.summary,
    symbol.context,
    ...symbol.fields.flatMap((field) => [
      field.name,
      field.requirement,
      field.value,
      field.default,
      field.description,
    ]),
    ...(symbol.notes ?? []),
  ].join("\n");
}

function symbolMatches(symbol: SyntaxReferenceSymbol, query: string): boolean {
  return searchableSymbolText(symbol).toLocaleLowerCase().includes(query.toLocaleLowerCase());
}

function fallbackCopy(text: string): boolean {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.readOnly = true;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  return copied;
}

function matches(section: SyntaxReferenceSection, query: string): boolean {
  if (!query) return true;
  const symbols = catalogBySection.get(section.id) ?? [];
  const haystack = [
    section.title,
    section.summary,
    section.exampleTitle,
    ...section.keywords,
    ...section.rules,
    section.code,
    ...symbols.map(searchableSymbolText),
  ].join("\n").toLocaleLowerCase();
  return haystack.includes(query.toLocaleLowerCase());
}

function visibleSymbols(sectionId: string, query: string): SyntaxReferenceSymbol[] {
  const symbols = catalogBySection.get(sectionId) ?? [];
  if (!query) return symbols;
  const matched = symbols.filter((symbol) => symbolMatches(symbol, query));
  return matched.length > 0 ? matched : symbols;
}

export function SyntaxReference({ initialTopic = null, initialSymbol = null }: { initialTopic?: string | null; initialSymbol?: string | null }) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(sections[0]?.id ?? "");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copyFailed, setCopyFailed] = useState(false);
  const filtered = useMemo(
    () => sections.filter((section) => matches(section, query.trim())),
    [query],
  );
  const selected = filtered.find((section) => section.id === selectedId) ?? filtered[0] ?? null;
  const selectedSymbols = useMemo(
    () => selected ? visibleSymbols(selected.id, query.trim()) : [],
    [query, selected],
  );

  useEffect(() => {
    if (!initialTopic || !sections.some((section) => section.id === initialTopic)) return;
    setQuery("");
    setSelectedId(initialTopic);
  }, [initialTopic]);

  useEffect(() => {
    if (!initialSymbol || !selected || !selectedSymbols.some((symbol) => symbol.id === initialSymbol)) return;
    const timer = window.setTimeout(() => {
      const target = document.getElementById(`syntax-symbol-${initialSymbol}`);
      target?.scrollIntoView({ block: "start" });
      target?.focus({ preventScroll: true });
    }, 100);
    return () => window.clearTimeout(timer);
  }, [initialSymbol, selected, selectedSymbols]);

  const copyExample = async (section: SyntaxReferenceSection) => {
    setCopyFailed(false);
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(section.code);
      else if (!fallbackCopy(section.code)) throw new Error("clipboard unavailable");
      setCopiedId(section.id);
    } catch {
      if (fallbackCopy(section.code)) setCopiedId(section.id);
      else {
        setCopiedId(null);
        setCopyFailed(true);
      }
    }
  };

  return (
    <div className="syntax-reference" aria-label="Kirin Tor 语法参考内容">
      <header className="syntax-reference-header">
        <Box>
          <Text className="page-kicker">写作参考</Text>
          <Text fw={680} fz="lg">在源码旁确认写法与创作边界</Text>
          <Text c="dimmed" fz="xs" mt={4}>
            {totalCatalogSymbols} 个官方语法项集中列出公开声明、字段、约束和可验证示例；这里是只读投影，不替代源码校验。
          </Text>
        </Box>
        <TextInput
          aria-label="搜索语法参考"
          leftSection={<Search size={14} />}
          placeholder="搜索输入、Process、Agent、图表…"
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
        />
      </header>

      <div className="syntax-reference-layout">
        <ScrollArea className="syntax-reference-index" type="auto" scrollbars="y">
          <nav aria-label="语法主题">
            <Text className="nav-group-label">{filtered.length} 个匹配主题</Text>
            {filtered.map((section) => (
              <button
                type="button"
                key={section.id}
                className="syntax-reference-link"
                aria-pressed={selected?.id === section.id}
                onClick={() => {
                  setSelectedId(section.id);
                  setCopiedId(null);
                  setCopyFailed(false);
                }}
              >
                <strong>{section.title}</strong>
                <small>
                  {(catalogBySection.get(section.id)?.length ?? 0) > 0
                    ? `${catalogBySection.get(section.id)?.length ?? 0} 项官方语法`
                    : section.keywords.slice(0, 3).join(" · ")}
                </small>
              </button>
            ))}
          </nav>
        </ScrollArea>

        <ScrollArea className="syntax-reference-detail" type="auto" scrollbars="y">
          {selected ? (
            <article aria-labelledby={`syntax-reference-${selected.id}`}>
              <Stack gap="lg">
                <Box>
                  <Group gap="xs" mb="xs">
                    <Badge variant="outline" color="gray">Kirin Tor v2</Badge>
                    <Badge variant="light" color="orange">官方语法参考</Badge>
                  </Group>
                  <Text id={`syntax-reference-${selected.id}`} component="h3" fw={700} fz="xl">
                    {selected.title}
                  </Text>
                  <Text c="dimmed" fz="sm" mt="xs" lh={1.65}>{selected.summary}</Text>
                </Box>

                {selectedSymbols.length > 0 && (
                  <section className="syntax-reference-catalog" aria-label={`${selected.title}官方语法项`}>
                    <Group justify="space-between" align="baseline" mb="xs">
                      <Text component="h4" fw={700} fz="md">官方语法项</Text>
                      <Text c="dimmed" fz="xs">{selectedSymbols.length} 项 · 字段封闭</Text>
                    </Group>

                    {selectedSymbols.length > 1 && (
                      <nav className="syntax-symbol-index" aria-label={`${selected.title}语法项索引`}>
                        {selectedSymbols.map((symbol) => (
                          <a key={symbol.id} href={`#syntax-symbol-${symbol.id}`}>
                            <code>{symbol.name}</code>
                            <span>{symbol.summary}</span>
                          </a>
                        ))}
                      </nav>
                    )}

                    <Stack gap="md">
                      {selectedSymbols.map((symbol) => (
                        <section
                          key={symbol.id}
                          id={`syntax-symbol-${symbol.id}`}
                          tabIndex={-1}
                          className="syntax-symbol"
                          aria-labelledby={`syntax-symbol-heading-${symbol.id}`}
                        >
                          <div className="syntax-symbol-header">
                            <Box>
                              <Group gap="xs" mb={4}>
                                <Badge variant="outline" color="gray">{symbol.kind}</Badge>
                                <Text c="dimmed" fz="xs">{symbol.context}</Text>
                              </Group>
                              <Text
                                id={`syntax-symbol-heading-${symbol.id}`}
                                component="h5"
                                fw={700}
                                fz="md"
                              >
                                <Code>{symbol.name}</Code>
                              </Text>
                              <Text c="dimmed" fz="sm" mt={5} lh={1.55}>{symbol.summary}</Text>
                            </Box>
                          </div>

                          <pre className="syntax-reference-signature"><Code component="code" tabIndex={0}>{symbol.signature}</Code></pre>

                          <div className="syntax-field-table-wrap">
                            <table className="syntax-field-table">
                              <thead>
                                <tr>
                                  <th scope="col">字段或组成项</th>
                                  <th scope="col">要求</th>
                                  <th scope="col">类型或允许值</th>
                                  <th scope="col">默认</th>
                                  <th scope="col">说明</th>
                                </tr>
                              </thead>
                              <tbody>
                                {symbol.fields.map((field) => (
                                  <tr key={`${symbol.id}-${field.name}`}>
                                    <th scope="row"><code>{field.name}</code></th>
                                    <td>{field.requirement}</td>
                                    <td><code>{field.value}</code></td>
                                    <td>{field.default}</td>
                                    <td>{field.description}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>

                          {symbol.notes && symbol.notes.length > 0 && (
                            <ul className="syntax-symbol-notes">
                              {symbol.notes.map((note) => <li key={note}>{note}</li>)}
                            </ul>
                          )}
                        </section>
                      ))}
                    </Stack>
                  </section>
                )}

                <section aria-label={`${selected.title}规则`}>
                  <Text component="h4" className="page-kicker" mb="xs">主题规则</Text>
                  <ul className="syntax-reference-rules">
                    {selected.rules.map((rule) => <li key={rule}>{rule}</li>)}
                  </ul>
                </section>

                <section className="syntax-example" aria-label={`${selected.title}示例`}>
                  <Group justify="space-between" wrap="nowrap" className="syntax-example-toolbar">
                    <Box>
                      <Text className="page-kicker">可校验示例</Text>
                      <Text fw={650} fz="sm" mt={3}>{selected.exampleTitle}</Text>
                    </Box>
                    <Button
                      variant="default"
                      size="xs"
                      leftSection={copiedId === selected.id ? <Check size={13} /> : <Copy size={13} />}
                      aria-label={`复制示例：${selected.title}`}
                      onClick={() => { void copyExample(selected); }}
                    >
                      {copiedId === selected.id ? "已复制" : "复制示例"}
                    </Button>
                  </Group>
                  <pre><Code component="code" tabIndex={0}>{selected.code}</Code></pre>
                  <Text c={copyFailed ? "red" : "dimmed"} fz="xs" className="syntax-example-note">
                    {copyFailed
                      ? "浏览器拒绝了剪贴板访问；可以直接选择上方源码复制。"
                      : "复制只写入剪贴板，不会修改当前文档。粘贴后仍需按所在工作区的语义执行完整校验。"}
                  </Text>
                </section>
              </Stack>
            </article>
          ) : (
            <Stack className="syntax-reference-empty" align="center" justify="center" gap="xs">
              <Search size={26} />
              <Text fw={650}>没有匹配的语法主题</Text>
              <Text c="dimmed" fz="xs">换一个关键词，例如“输入”“Agent”或“图表”。</Text>
            </Stack>
          )}
        </ScrollArea>
      </div>
    </div>
  );
}
