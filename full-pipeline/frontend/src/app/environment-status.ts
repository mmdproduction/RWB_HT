import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { Config } from '../models';
import { RunsService, errorMessage } from './services/runs.service';

@Component({
  selector: 'app-environment-status', standalone: true, imports: [MatButtonModule],
  template: `
    <section class="environment-bar" aria-label="Готовность среды">
      <div class="environment-heading"><span class="eyebrow">КОНФИГУРАЦИЯ СРЕДЫ</span><button mat-button [disabled]="loading" (click)="refresh()">{{ loading ? 'Обновляем…' : 'Обновить' }}</button></div>
      @if (config; as cfg) {
        <div class="environment-items"><span><i class="connection-dot" [class.ready]="cfg.modelConfigured"></i><strong>Модель</strong> {{ cfg.model }} · {{ cfg.modelConfigured ? 'настроена' : 'не настроена' }}</span><span><i class="connection-dot" [class.ready]="cfg.workerConfigured"></i><strong>Исполнитель</strong> {{ cfg.workerConfigured ? 'настроен' : 'не настроен' }}</span></div>
      } @else if (!error) { <p>Загружаем конфигурацию…</p> }
      @if (error) { <p class="environment-error" role="alert">{{ error }}</p> }
      <p class="environment-note">Текущее соединение с моделью показано в QWEN_API ниже.</p>
    </section>
  `
})
export class EnvironmentStatusComponent implements OnInit {
  private api = inject(RunsService);
  private destroyRef = inject(DestroyRef);
  config: Config | null = null;
  error = '';
  loading = false;
  ngOnInit(): void { this.refresh(); }
  refresh(): void {
    if (this.loading) return;
    this.loading = true;
    this.api.getConfig().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: config => { this.config = config; this.error = ''; this.loading = false; },
      error: error => { this.error = errorMessage(error); this.loading = false; }
    });
  }
}
