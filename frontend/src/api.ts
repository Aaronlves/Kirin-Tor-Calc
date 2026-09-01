import type { OperationResult } from "./types";

const currentUrl = new URL(window.location.href);
const suppliedToken = currentUrl.searchParams.get("token");

export const initialDocument = currentUrl.searchParams.get("document");

if (suppliedToken) {
  sessionStorage.setItem("kirin-token", suppliedToken);
  currentUrl.searchParams.delete("token");
  currentUrl.searchParams.delete("document");
  history.replaceState({}, "", currentUrl.pathname + currentUrl.search + currentUrl.hash);
}

const token = suppliedToken || sessionStorage.getItem("kirin-token") || "";

export class ApiError extends Error {
  payload: Record<string, unknown>;

  constructor(payload: Record<string, unknown>, fallback: string) {
    super(String(payload.author_message || payload.message || fallback));
    this.name = "ApiError";
    this.payload = payload;
  }
}

async function parseResponse(response: Response): Promise<Record<string, unknown>> {
  try {
    return (await response.json()) as Record<string, unknown>;
  } catch {
    return { message: `工作台返回了无法读取的响应（HTTP ${response.status}）。` };
  }
}

export async function request<T>(
  path: string,
  payload?: Record<string, unknown>,
  options: { allowErrorResult?: boolean } = {},
): Promise<T> {
  if (!token) {
    throw new ApiError({ code: "missing_session", message: "缺少本地工作台会话令牌，请通过 kt web 重新打开。" }, "缺少会话令牌");
  }
  const response = await fetch(path, {
    method: payload === undefined ? "GET" : "POST",
    headers: {
      "X-Kirin-Token": token,
      ...(payload === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const result = await parseResponse(response);
  if (!response.ok || (!options.allowErrorResult && result.status === "error")) {
    throw new ApiError(result, `请求失败（HTTP ${response.status}）`);
  }
  return result as T;
}

export async function runOperation(
  operation: string,
  payload: Record<string, unknown>,
  overlays: Record<string, string>,
): Promise<OperationResult> {
  return request<OperationResult>("/api/operation", { operation, payload, overlays });
}

export async function fetchArtifact(path: string): Promise<string> {
  const response = await fetch(`/api/artifact?path=${encodeURIComponent(path)}`, {
    headers: { "X-Kirin-Token": token },
  });
  if (!response.ok) {
    const payload = await parseResponse(response);
    throw new ApiError(payload, "无法读取导出文件");
  }
  return URL.createObjectURL(await response.blob());
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "发生了未知错误。";
}
