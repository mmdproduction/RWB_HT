import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, catchError, map, of, switchMap, timeout } from 'rxjs';
import { Config, LogPage, Run, RunSummary, Stage as ApiStage } from '../../models';
import { safeExternalUrl } from '../../run-state';

export type RunStatus = string;
export type StageStatus = string;
export interface Stage extends ApiStage { name: string; }
export interface RunDetail extends Omit<Run, 'stages'> { stages: Stage[]; }
export const STAGE_NAMES: Record<string, string> = {
  analysis: 'Анализ требований', design: 'Проектирование', generation: 'Генерация кода',
  build: 'Сборка', test: 'Проверка сценариев', security: 'Аудит',
  deploy: 'Развёртывание', documentation: 'Документация'
};
const LABELS: Record<string, string> = {
  queued: 'В очереди', running: 'В работе', succeeded: 'Готово', failed: 'Ошибка',
  blocked: 'Требуется внимание', interrupted: 'Прерван', pending: 'Ожидает',
  passed: 'Пройдено', not_run: 'Не выполнялось'
};
export function statusLabel(status: string): string { return LABELS[status] || status; }
export function errorMessage(error: unknown): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0) return 'Нет связи с API. Проверьте подключение и повторите запрос.';
    if (error.status === 404) return 'Запуск не найден.';
    if (typeof error.error?.detail === 'string') return error.error.detail;
    return `Не удалось выполнить запрос (${error.status}).`;
  }
  return error instanceof Error ? error.message : 'Не удалось выполнить запрос.';
}

@Injectable({ providedIn: 'root' })
export class RunsService {
  private http = inject(HttpClient);
  draftRequirements = '';
  getConfig(): Observable<Config> { return this.http.get<Config>('/api/config').pipe(timeout(15000)); }
  createRun(requirements: string): Observable<{ runId: string }> {
    return this.http.post<{ runId: string }>('/api/runs', { requirements }).pipe(timeout(15000));
  }
  listRuns(): Observable<RunSummary[]> { return this.http.get<RunSummary[]>('/api/runs').pipe(timeout(15000)); }
  getRun(runId: string): Observable<RunDetail> {
    return this.http.get<Run>(`/api/runs/${encodeURIComponent(runId)}`).pipe(timeout(15000), map(run => ({
      ...run, appUrl: safeExternalUrl(run.appUrl), repositoryUrl: safeExternalUrl(run.repositoryUrl),
      stages: run.stages.map(stage => ({ ...stage, name: STAGE_NAMES[stage.stageId] || stage.stageId }))
    })));
  }
  snapshot(runId: string, after: number) {
    // Read the journal after the run: terminal state must not race its final log entries.
    return this.getRun(runId).pipe(switchMap(run =>
      this.http.get<LogPage>(`/api/runs/${encodeURIComponent(runId)}/logs`, { params: { after } }).pipe(
        timeout(15000),
        map(page => ({ page, error: '' })),
        catchError(error => of({ page: null, error: errorMessage(error) })),
        map(journal => ({ run, journal }))
      )
    ));
  }
  download(runId: string): Observable<Blob> {
    return this.http.get(`/api/runs/${encodeURIComponent(runId)}/download`, { responseType: 'blob' });
  }
}
