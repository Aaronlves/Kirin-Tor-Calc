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

interface SyntaxReferenceSection {
  id: string;
  title: string;
  summary: string;
  keywords: string[];
  rules: string[];
  exampleTitle: string;
  code: string;
}

const sections = rawSections as SyntaxReferenceSection[];

function legacyCopy(text: string): boolean {
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
  const haystack = [
    section.title,
    section.summary,
    section.exampleTitle,
    ...section.keywords,
    ...section.rules,
    section.code,
  ].join("\n").toLocaleLowerCase();
  return haystack.includes(query.toLocaleLowerCase());
}

export function SyntaxReference({ initialTopic = null }: { initialTopic?: string | null }) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(sections[0]?.id ?? "");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [copyFailed, setCopyFailed] = useState(false);
  const filtered = useMemo(
    () => sections.filter((section) => matches(section, query.trim())),
    [query],
  );
  const selected = filtered.find((section) => section.id === selectedId) ?? filtered[0] ?? null;

  useEffect(() => {
    if (!initialTopic || !sections.some((section) => section.id === initialTopic)) return;
    setQuery("");
    setSelectedId(initialTopic);
  }, [initialTopic]);

  const copyExample = async (section: SyntaxReferenceSection) => {
    setCopyFailed(false);
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(section.code);
      else if (!legacyCopy(section.code)) throw new Error("clipboard unavailable");
      setCopiedId(section.id);
    } catch {
      if (legacyCopy(section.code)) setCopiedId(section.id);
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
          <Text className="page-kicker">AUTHORING REFERENCE</Text>
          <Text fw={680} fz="lg">在源码旁确认写法与创作边界</Text>
          <Text c="dimmed" fz="xs" mt={4}>
            这是随应用发布的只读速查。语法、Agent 协作和严格语义仍由当前版本实现与校验器决定。
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
        <ScrollArea className="syntax-reference-index" type="auto">
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
                <small>{section.keywords.slice(0, 3).join(" · ")}</small>
              </button>
            ))}
          </nav>
        </ScrollArea>

        <ScrollArea className="syntax-reference-detail" type="auto">
          {selected ? (
            <article aria-labelledby={`syntax-reference-${selected.id}`}>
              <Stack gap="lg">
                <Box>
                  <Group gap="xs" mb="xs">
                    <Badge variant="outline" color="gray">Kirin Tor v2</Badge>
                    <Badge variant="light" color="orange">只读参考</Badge>
                  </Group>
                  <Text id={`syntax-reference-${selected.id}`} component="h2" fw={700} fz="xl">
                    {selected.title}
                  </Text>
                  <Text c="dimmed" fz="sm" mt="xs" lh={1.65}>{selected.summary}</Text>
                </Box>

                <section aria-label={`${selected.title}规则`}>
                  <Text className="page-kicker" mb="xs">规则</Text>
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
                  <pre><Code component="code">{selected.code}</Code></pre>
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
