import { Component, inject, OnInit, OnDestroy } from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { Subscription } from 'rxjs';
import { isActive } from '../../../run-state';
import { RunHeaderComponent } from '../../run-header';
import { RunFilesComponent } from '../../../run-files';
import { RunsService, RunDetail, errorMessage, statusLabel } from '../../services/runs.service';

@Component({
  selector: 'app-run-result',
  standalone: true,
  imports: [CommonModule, MatButtonModule, MatProgressSpinnerModule, RunFilesComponent, RouterLink, RunHeaderComponent],
  templateUrl: './run-result.component.html',

})
export class RunResultComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private runsService = inject(RunsService);
  private requests = new Subscription();
  private loadRequest?: Subscription;
  private downloadRequest?: Subscription;
  private timer?: ReturnType<typeof setTimeout>;
  busy = false;
  private destroyed = false;
  runId = '';
  run: RunDetail | null = null;
  error = '';
  downloading = false;
  downloadError = '';
  fileCount = 0;
  tab: 'result' | 'files' | 'task' = 'result';
  statusLabel = statusLabel;
  ngOnInit() {
    this.requests.add(this.route.queryParamMap.subscribe(params => {
      const view = params.get('view'); this.tab = view === 'files' || view === 'task' ? view : 'result';
    }));
    this.requests.add(this.route.paramMap.subscribe(params => {
      this.loadRequest?.unsubscribe(); this.downloadRequest?.unsubscribe(); clearTimeout(this.timer);
      this.runId = params.get('runId') || ''; this.run = null; this.busy = false; this.fileCount = 0;
      this.error = ''; this.downloadError = ''; this.downloading = false; this.load();
    }));
  }
  ngOnDestroy() {
    this.destroyed = true; clearTimeout(this.timer); this.requests.unsubscribe();
  }
  load() {
    if (this.busy || this.destroyed) return;
    clearTimeout(this.timer); this.busy = true;
    this.loadRequest = this.runsService.getRun(this.runId).subscribe({
      next: run => {
        this.run = run; this.error = ''; this.busy = false;
        if (isActive(run.status)) this.timer = setTimeout(() => this.load(), 3000);
      },
      error: error => {
        this.busy = false; this.error = errorMessage(error);
        if (!this.destroyed && ![400, 404, 422].includes(error.status)) {
          this.timer = setTimeout(() => this.load(), 3000);
        }
      }
    });
    this.requests.add(this.loadRequest);
  }
  duration(seconds: number): string {
    const value = Math.max(0, Math.round(seconds));
    return `${Math.floor(value / 60)} мин ${value % 60} с`;
  }
  tokens(value: number | null): string { return value == null ? 'Нет данных' : value.toLocaleString('ru-RU'); }
  reuse(): void {
    if (this.run) { this.runsService.draftRequirements = this.run.requirements; void this.router.navigate(['/new']); }
  }
  download() {
    if (this.downloading) return;
    this.downloading = true; this.downloadError = '';
    this.downloadRequest = this.runsService.download(this.runId).subscribe({
      next: blob => {
        this.downloading = false;
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url; anchor.download = `run-${this.runId}.zip`; anchor.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
      },
      error: error => { this.downloading = false; this.downloadError = errorMessage(error); }
    });
    this.requests.add(this.downloadRequest);
  }
}
