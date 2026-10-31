import { Component, EventEmitter, Input, Output } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { RunDetail, statusLabel } from './services/runs.service';

@Component({
  selector: 'app-run-header', standalone: true, imports: [DatePipe, RouterLink, MatButtonModule],
  template: `
    <a class="back-link" routerLink="/new">← Все запуски</a>
    <header class="workspace-heading">
      <div class="workspace-title"><div class="eyebrow">ЗАПУСК / {{ run.runId.slice(0, 8) }}</div>
        <h1>{{ title() }}</h1>
        <div class="workspace-meta"><span class="status-pill" [attr.data-status]="run.status">{{ label(run.status) }}</span><span>{{ run.createdAt | date:'dd.MM.yyyy, HH:mm' }}</span><span>{{ run.status === 'queued' || run.status === 'running' ? 'Автообновление каждые 3 с' : 'Сохранённые результаты' }}</span></div>
      </div>
      <div class="workspace-actions"><button mat-stroked-button [disabled]="refreshing" (click)="refresh.emit()">{{ refreshing ? 'Обновляем…' : '↻ Обновить' }}</button><button mat-flat-button (click)="reuse.emit()">Использовать требования ↗</button></div>
    </header>
    <nav class="workspace-tabs" aria-label="Разделы запуска">
      <a [routerLink]="['/status', run.runId]" [class.active]="active === 'progress'" [attr.aria-current]="active === 'progress' ? 'page' : null">Процесс выполнения</a>
      <a [routerLink]="['/result', run.runId]" [class.active]="active === 'result'" [attr.aria-current]="active === 'result' ? 'page' : null">Результат</a>
      <a [routerLink]="['/result', run.runId]" [queryParams]="{ view: 'files' }" [class.active]="active === 'files'" [attr.aria-current]="active === 'files' ? 'page' : null">Файлы проекта @if (fileCount !== null) { <span class="tab-count">{{ fileCount }}</span> }</a>
      <a [routerLink]="['/result', run.runId]" [queryParams]="{ view: 'task' }" [class.active]="active === 'task'" [attr.aria-current]="active === 'task' ? 'page' : null">Бизнес-задача</a>
    </nav>
  `
})
export class RunHeaderComponent {
  @Input({ required: true }) run!: RunDetail;
  @Input() active: 'progress' | 'result' | 'files' | 'task' = 'progress';
  @Input() fileCount: number | null = null;
  @Input() refreshing = false;
  @Output() refresh = new EventEmitter<void>();
  @Output() reuse = new EventEmitter<void>();
  readonly label = statusLabel;
  title(): string {
    const title = this.run.requirements.trim().split('\n')[0];
    return title.length > 110 ? title.slice(0, 110) + '…' : title;
  }
}
