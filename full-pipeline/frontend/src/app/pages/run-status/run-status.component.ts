import { Component, inject, OnInit, OnDestroy } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { CommonModule } from '@angular/common';
import { Subscription } from 'rxjs';
import { isActive, nextLogCursor, progressPercent } from '../../../run-state';
import { RunHeaderComponent } from '../../run-header';
import { LogItem } from '../../../models';
import { RunsService, RunDetail, STAGE_NAMES, errorMessage, statusLabel } from '../../services/runs.service';

@Component({
  selector: 'app-run-status',
  standalone: true,
  imports: [
    CommonModule,
    MatButtonModule, 
    MatProgressBarModule,
    MatProgressSpinnerModule,
    RunHeaderComponent
  ],
  templateUrl: './run-status.component.html',

})
export class RunStatusComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private runsService = inject(RunsService);
  runId = '';
  run: RunDetail | null = null;
  logs: LogItem[] = [];
  error = '';
  logError = '';
  progress = 0;
  elapsedTime = 0;
  private cursor = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private request?: Subscription;
  private destroyed = false;
  private routeSubscription?: Subscription;
  readonly statusLabel = statusLabel;

  ngOnInit() {
    this.routeSubscription = this.route.paramMap.subscribe(params => {
      this.request?.unsubscribe(); clearTimeout(this.timer);
      this.runId = params.get('runId') || ''; this.run = null; this.logs = []; this.cursor = 0;
      this.error = ''; this.logError = ''; this.progress = 0; this.elapsedTime = 0; this.poll();
    });
  }
  ngOnDestroy() {
    this.destroyed = true; clearTimeout(this.timer); this.request?.unsubscribe(); this.routeSubscription?.unsubscribe();
  }
  poll() {
    if (this.destroyed || (this.request && !this.request.closed)) return;
    clearTimeout(this.timer);
    this.request = this.runsService.snapshot(this.runId, this.cursor).subscribe({
      next: ({ run, journal }) => {
        if (this.destroyed) return;
        this.run = run; this.error = ''; this.logError = journal.error;
        this.progress = progressPercent(run.stages);
        this.elapsedTime = run.metrics.durationSeconds;
        let hasMoreLogs = false;
        if (journal.page) {
          const previous = this.cursor;
          this.cursor = nextLogCursor(previous, journal.page);
          this.logs = [...this.logs, ...journal.page.items.filter(item => item.cursor > previous)].slice(-2000);
          hasMoreLogs = journal.page.items.length > 0 && this.cursor > previous;
        }
        if (hasMoreLogs || isActive(run.status) || this.logError) this.schedule(hasMoreLogs ? 0 : 3000);
      },
      error: error => {
        this.error = errorMessage(error);
        if (error.status !== 404 && error.status !== 400 && error.status !== 422) this.schedule(3000);
      }
    });
  }
  private schedule(delay: number) {
    if (!this.destroyed) this.timer = setTimeout(() => this.poll(), delay);
  }
  reuse(): void {
    if (this.run) { this.runsService.draftRequirements = this.run.requirements; void this.router.navigate(['/new']); }
  }
  get refreshing(): boolean { return !!this.request && !this.request.closed; }
  stageDescription(id: string): string {
    return ({ analysis: 'Задача, сценарии и ограничения', design: 'Архитектура и модель данных', generation: 'Код приложения по требованиям', build: 'Проверка компиляции проекта', test: 'Проверка рабочих сценариев', security: 'Зависимости и информационные находки', deploy: 'Запуск приложения в Docker', documentation: 'Инструкции и итоговые отчёты' } as Record<string, string>)[id] || '';
  }
  stageName(id: string): string { return STAGE_NAMES[id] || id; }
  passedCount(): number { return this.run?.stages.filter(stage => stage.status === 'passed').length || 0; }
  formatTime(seconds: number): string {
    const value = Math.max(0, Math.round(seconds));
    return `${Math.floor(value / 60).toString().padStart(2, '0')}:${(value % 60).toString().padStart(2, '0')}`;
  }
}
