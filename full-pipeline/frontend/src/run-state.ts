export function isActive(status: string): boolean { return status === 'queued' || status === 'running'; }
export function shouldPoll(runs: readonly { status: string }[]): boolean { return runs.some(run => isActive(run.status)); }
export function safeExternalUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; } catch { return null; }
}
export function progressPercent(stages: readonly { status: string }[]): number {
  return stages.length ? Math.round(stages.filter(stage => stage.status === 'passed').length / stages.length * 100) : 0;
}
export function nextLogCursor(cursor: number, page: { nextCursor: number; items: readonly { cursor: number }[] }): number {
  return Math.max(cursor, page.nextCursor, ...page.items.map(item => item.cursor));
}
