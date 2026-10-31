import { Component, inject, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { CommonModule } from '@angular/common';
import { DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subject, catchError, exhaustMap, merge, timer } from 'rxjs';
import { isActive } from '../../../run-state';
import { RunsService, errorMessage, statusLabel } from '../../services/runs.service';

@Component({
  selector: 'app-new-run',
  standalone: true,
  imports: [CommonModule, FormsModule, MatButtonModule, MatProgressSpinnerModule],
  templateUrl: './new-run.component.html',

})
export class NewRunComponent implements OnInit {
  private runsService = inject(RunsService);
  private router = inject(Router);
  
  requirements = '';
  loading = false;
  error = '';

  private destroyRef = inject(DestroyRef);
  listError = '';
  listLoading = true;
  lastUpdated: Date | null = null;
  private refreshHistory$ = new Subject<void>();
  stats = { totalRuns: 0, successRate: 0, activeRuns: 0, successRuns: 0 };
  recentRuns: { id: string; name: string; status: string; time: string }[] = [];

  ngOnInit() {
    this.requirements = this.runsService.draftRequirements;
    merge(timer(0, 5000), this.refreshHistory$).pipe(
      exhaustMap(() => this.runsService.listRuns().pipe(catchError(error => {
        this.listError = errorMessage(error); this.listLoading = false; return EMPTY;
      }))), takeUntilDestroyed(this.destroyRef)
    ).subscribe(runs => {
      this.listError = ''; this.listLoading = false; this.lastUpdated = new Date();
      const successRuns = runs.filter(run => run.status === 'succeeded').length;
      this.stats = { totalRuns: runs.length, successRate: runs.length ? Math.round(successRuns / runs.length * 100) : 0,
        activeRuns: runs.filter(run => isActive(run.status)).length, successRuns };
      this.recentRuns = runs.map(run => ({ id: run.runId, name: run.requirements.trim().split('\n')[0].slice(0, 100),
        status: run.status, time: new Date(run.createdAt).toLocaleString('ru-RU') }));
    });
  }
  statusLabel = statusLabel;
  navigateToStatus(id: string) { this.router.navigate(['/status', id]); }

  refreshHistory(): void { this.refreshHistory$.next(); }
  saveDraft(value: string): void { this.requirements = value; this.runsService.draftRequirements = value; }

  startRun() {
    if (this.loading) return;
    if (!this.requirements.trim() || this.requirements.length > 100000) {
      this.error = 'Введите требования длиной от 1 до 100 000 символов';
      return;
    }
    this.error = '';
    this.loading = true;
    
    this.runsService.createRun(this.requirements).pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: (res) => this.router.navigate(['/status', res.runId]),
      error: (err) => {
        this.loading = false;
        this.error = errorMessage(err);
      }
    });
  }
}
