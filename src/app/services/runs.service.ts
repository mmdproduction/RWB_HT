import { Injectable } from '@angular/core';
import { Observable, of, delay } from 'rxjs';
import { SpecGeneratorService, AppSpec } from './spec-generator.service';

export type RunStatus = 'pending' | 'running' | 'succeeded' | 'failed';
export type StageStatus = 'pending' | 'running' | 'passed' | 'failed' | 'blocked';

export interface Stage { name: string; status: StageStatus; }

export interface RunDetail {
  runId: string;
  status: RunStatus;
  stages: Stage[];
  logs: string[];
  appUrl?: string;
  repoUrl?: string;
  metrics?: { duration: number; tokens: number };
}

@Injectable({ providedIn: 'root' })
export class RunsService {
  private runs = new Map<string, RunDetail>();

  constructor(private specGenerator: SpecGeneratorService) {}

  createRun(requirements: string): Observable<{ runId: string }> {
    const runId = 'run-' + Date.now();
    const spec = this.specGenerator.generateSpec(requirements);
    
    // Сохраняем spec для PWA
    localStorage.setItem(`spec-${runId}`, JSON.stringify(spec));
    
    const run: RunDetail = {
      runId,
      status: 'running',
      stages: [
        { name: 'Анализ требований', status: 'running' },
        { name: 'Системный анализ', status: 'pending' },
        { name: 'Проектирование UI', status: 'pending' },
        { name: 'Генерация Frontend', status: 'pending' },
        { name: 'Генерация Backend', status: 'pending' },
        { name: 'Тестирование', status: 'pending' },
        { name: 'Сборка и деплой', status: 'pending' }
      ],
      logs: ['[00:00] ✓ Получены требования, начинаю анализ...'],
      metrics: { duration: 1, tokens: 1200 }
    };
    
    this.runs.set(runId, run);
    this.simulateGeneration(runId, spec);
    
    return of({ runId }).pipe(delay(300));
  }

  getRun(runId: string): Observable<RunDetail> {
    const run = this.runs.get(runId);
    if (!run) return of(this.createMockRun(runId));
    return of(run);
  }

  private simulateGeneration(runId: string, spec: AppSpec) {
    const run = this.runs.get(runId)!;
    const stageDuration = 2000;
    
    run.stages.forEach((stage, index) => {
      setTimeout(() => {
        for (let i = 0; i < index; i++) run.stages[i].status = 'passed';
        stage.status = 'running';
        
        const logs = [
          '✓ Сформирован системный анализ',
          '✓ Спроектировано UI',
          '✓ Сгенерирован Angular код',
          '✓ Сгенерирован Backend',
          '✓ Пройдено тестирование',
          '✓ Приложение развёрнуто'
        ];
        if (index > 0) run.logs.push(`[00:0${index + 1}] ${logs[index - 1]}`);
        run.metrics!.duration = index + 1;
        
        if (index === run.stages.length - 1) {
          setTimeout(() => {
            stage.status = 'passed';
            run.status = 'succeeded';
            run.appUrl = `http://localhost:4201?spec=${runId}`;
            run.repoUrl = 'https://gitlab.russtech.ai/projects/' + runId;
          }, stageDuration);
        }
      }, index * stageDuration);
    });
  }

  private createMockRun(runId: string): RunDetail {
    return {
      runId, status: 'succeeded',
      stages: [{ name: 'Анализ', status: 'passed' }, { name: 'Генерация', status: 'passed' }, { name: 'Деплой', status: 'passed' }],
      logs: ['[00:00] ✓ Готово'],
      appUrl: `http://localhost:4201?spec=${runId}`,
      repoUrl: 'https://gitlab.russtech.ai/projects/' + runId,
      metrics: { duration: 3, tokens: 5000 }
    };
  }
}