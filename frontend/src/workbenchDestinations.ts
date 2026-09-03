import tokens from "./design/tokens.json";

export type BuiltinDestinationId =
  | "documents"
  | "graph"
  | "runs"
  | "packages"
  | "plugins"
  | "syntax"
  | "search"
  | "changes"
  | "settings";

export type DestinationKind = "view" | "tool";
export type DestinationPlacement = "sidebar" | "tool-menu" | "header";
export type DestinationIcon =
  | "book"
  | "changes"
  | "documents"
  | "graph"
  | "history"
  | "package"
  | "plugin"
  | "search"
  | "settings";

export interface BuiltinDestination {
  id: BuiltinDestinationId;
  kind: DestinationKind;
  placement: DestinationPlacement;
  group: string;
  title: string;
  menuLabel?: string;
  eyebrow: string;
  description: string;
  commandLabel: string;
  keywords: string[];
  icon: DestinationIcon;
  drawerSize?: number | string;
}

export const builtinDestinations: BuiltinDestination[] = [
  {
    id: "documents", kind: "view", placement: "sidebar", group: "创作", title: "文档", eyebrow: "创作",
    description: "编辑 Kirin Tor 权威源码；外部本地工具写入会同步到干净缓冲。", commandLabel: "前往文档",
    keywords: ["文档", "创作", "source", "editor"], icon: "documents",
  },
  {
    id: "graph", kind: "view", placement: "sidebar", group: "理解", title: "关系图", eyebrow: "理解",
    description: "浏览由公式与跨文档引用生成的工作区关系网络。", commandLabel: "前往关系图",
    keywords: ["关系图", "理解", "graph", "dependencies"], icon: "graph",
  },
  {
    id: "syntax", kind: "tool", placement: "sidebar", group: "参考", title: "Kirin Tor 语法参考", eyebrow: "参考",
    description: "集中查询官方语法项、字段约束和可复制示例。", commandLabel: "打开 Kirin Tor 语法参考",
    keywords: ["syntax", "reference", "docs", "help", "语法", "参考", "文档", "帮助", "示例", "Agent", "协作"],
    icon: "book", drawerSize: tokens.size.drawerReference,
  },
  {
    id: "search", kind: "tool", placement: "tool-menu", group: "工作区工具", title: "工作区搜索与替换", eyebrow: "工具",
    menuLabel: "全文搜索与替换", description: "搜索当前草稿和 Package 源码；替换只生成可审查草稿。", commandLabel: "搜索与替换整个工作区",
    keywords: ["search", "replace", "全文", "搜索", "替换"], icon: "search", drawerSize: tokens.size.drawerFull,
  },
  {
    id: "changes", kind: "tool", placement: "tool-menu", group: "工作区工具", title: "保存前变更审查", eyebrow: "工具",
    description: "比较浏览器草稿与磁盘基线，并决定保存或放弃。", commandLabel: "审查未保存变更",
    keywords: ["diff", "changes", "review", "变更", "审查", "差异"], icon: "changes", drawerSize: tokens.size.drawerFull,
  },
  {
    id: "runs", kind: "tool", placement: "tool-menu", group: "工作区工具", title: "运行记录", eyebrow: "工具",
    description: "检查并重放带定义快照的不可变计算记录。", commandLabel: "打开运行记录",
    keywords: ["runs", "history", "运行记录"], icon: "history", drawerSize: tokens.size.drawerFull,
  },
  {
    id: "packages", kind: "tool", placement: "tool-menu", group: "依赖与扩展", title: "Package 管理", eyebrow: "管理",
    description: "安装、锁定、验证并开发社区数据包。", commandLabel: "打开 Package 管理",
    keywords: ["package", "依赖", "安装"], icon: "package", drawerSize: tokens.size.drawerWide,
  },
  {
    id: "plugins", kind: "tool", placement: "tool-menu", group: "依赖与扩展", title: "Workbench Plugins", eyebrow: "管理",
    description: "安装、批准、停用或验证沙箱界面插件。", commandLabel: "打开 Workbench Plugins",
    keywords: ["plugin", "extension", "插件", "扩展", "安全模式"], icon: "plugin", drawerSize: tokens.size.drawerWide,
  },
  {
    id: "settings", kind: "tool", placement: "header", group: "设置", title: "工作台设置", eyebrow: "设置",
    description: "查看当前工作区并调整界面、通知、Profile 与快捷键。", commandLabel: "打开工作台设置",
    keywords: ["settings", "preferences", "设置", "通知", "快捷键", "工作区"], icon: "settings", drawerSize: tokens.size.drawerSettings,
  },
];

export const builtinDestinationById = new Map(builtinDestinations.map((destination) => [destination.id, destination]));
export const builtinViewIds = builtinDestinations.filter((destination) => destination.kind === "view").map((destination) => destination.id);
export const builtinToolIds = builtinDestinations.filter((destination) => destination.kind === "tool").map((destination) => destination.id);
