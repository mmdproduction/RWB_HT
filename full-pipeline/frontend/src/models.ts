export interface RunSummary { runId: string; requirements: string; status: string; createdAt: string; finishedAt: string | null; message: string; }
export interface Stage { stageId: string; status: string; attempt: number; message: string; startedAt: string | null; finishedAt: string | null; }
export interface Artifact { artifactId: string; name: string; kind: string; path: string; url: string; }
export interface Run extends RunSummary { startedAt: string | null; appUrl: string | null; repositoryUrl: string | null; stages: Stage[]; artifacts: Artifact[]; metrics: { modelCalls: number; inputTokens: number | null; outputTokens: number | null; retries: number; durationSeconds: number; tokenUsageComplete?: boolean; }; }
export interface LogItem { cursor: number; stageId: string; createdAt: string; message: string; }
export interface LogPage { items: LogItem[]; nextCursor: number; }
export interface Config { stack: Record<string, unknown>; model: string; modelConfigured: boolean; workerConfigured: boolean; stages: string[]; }
export interface RunFile { path: string; name: string; size: number; kind: 'source' | 'report' | 'config' | 'archive' | 'other'; language: string; viewable: boolean; restricted: boolean; contentUrl: string | null; downloadUrl: string | null; }
export interface RunFileList { items: RunFile[]; count: number; excludedDirectories: string[]; }
export interface RunFileContent { path: string; content: string; language: string; size: number; truncated: boolean; }
