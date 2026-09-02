export function isApplePlatform(): boolean {
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform);
}

export function primaryShortcut(key: string, shift = false): string {
  if (isApplePlatform()) return `⌘${shift ? "⇧" : ""}${key}`;
  return `Ctrl+${shift ? "Shift+" : ""}${key}`;
}

