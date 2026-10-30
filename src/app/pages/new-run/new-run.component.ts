import { Component, inject, OnInit, AfterViewInit, ElementRef, OnDestroy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatIconModule } from '@angular/material/icon';
import { CommonModule } from '@angular/common';
import { RunsService } from '../../services/runs.service';

@Component({
  selector: 'app-new-run',
  standalone: true,
  imports: [CommonModule, FormsModule, MatCardModule, MatButtonModule, MatProgressSpinnerModule, MatIconModule],
  templateUrl: './new-run.component.html',
  styles: [`
    .page-header { text-align: center; margin-bottom: 56px; padding: 60px 0 40px; }
    .page-header h1 { font-size: 72px; font-weight: 900; background: linear-gradient(135deg, #ffffff 0%, #4fc3f7 50%, #ffffff 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 24px; letter-spacing: -3px; line-height: 1; text-transform: uppercase; text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3); }
    .page-header p { color: #e2e8f0 !important; font-size: 20px; max-width: 700px; margin: 0 auto; line-height: 1.7; text-shadow: 0 2px 4px rgba(0, 0, 0, 0.4); }
    .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 28px; margin-bottom: 64px; }
    .stat-card { background: white !important; padding: 32px 24px; border-radius: 20px; box-shadow: 0 8px 24px rgba(0,0,0,0.06); text-align: center; transition: all 0.4s ease; border: none !important; position: relative; overflow: hidden; }
    .stat-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px; background: linear-gradient(90deg, #003366, #0066CC, #FF6B35); transform: scaleX(0); transition: transform 0.4s ease; }
    .stat-card:hover::before { transform: scaleX(1); }
    .stat-card:hover { transform: translateY(-6px); box-shadow: 0 12px 32px rgba(0,0,0,0.1); }
    .stat-value { font-size: 44px; font-weight: 900; background: linear-gradient(135deg, #003366, #0066CC); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 8px; }
    .stat-label { font-size: 13px; color: #64748b !important; text-transform: uppercase; letter-spacing: 1.5px; font-weight: 700; }
    .main-card { padding: 48px; background: transparent !important; border-radius: 24px; box-shadow: none !important; border: none !important; }
    .card-title { font-size: 48px; font-weight: 900; background: linear-gradient(135deg, #ffffff 0%, #4fc3f7 50%, #ffffff 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin-bottom: 16px; display: flex; align-items: center; gap: 16px; text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3); text-transform: uppercase; letter-spacing: -2px; }
    .card-title-icon { width: 56px; height: 56px; min-width: 56px; background: linear-gradient(135deg, #003366, #0066CC); border-radius: 16px; display: flex; align-items: center; justify-content: center; box-shadow: 0 8px 24px rgba(0, 51, 102, 0.3); -webkit-text-fill-color: initial !important; color: white !important; }
    .card-title-icon mat-icon { -webkit-text-fill-color: white !important; color: white !important; font-size: 28px !important; width: 28px !important; height: 28px !important; }
    .card-subtitle { color: #e2e8f0 !important; font-size: 17px; margin-bottom: 36px; line-height: 1.6; text-shadow: 0 2px 4px rgba(0, 0, 0, 0.4); }
    .custom-textarea { width: 100%; min-height: 320px; padding: 28px; font-size: 16px; line-height: 1.8; border: 3px solid #e9ecef; border-radius: 20px; background: white; color: #212529 !important; font-family: 'Inter', sans-serif; resize: vertical; transition: all 0.4s ease; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06); }
    .custom-textarea::placeholder { color: #adb5bd; font-size: 15px; }
    .custom-textarea:focus { outline: none; border-color: #0066CC; box-shadow: 0 12px 32px rgba(0, 102, 204, 0.2); transform: translateY(-2px); }
    .char-count { text-align: right; margin-top: 12px; font-size: 14px; color: #cbd5e1 !important; font-weight: 600; }
    .actions { margin-top: 40px; display: flex; gap: 28px; align-items: center; justify-content: space-between; }
    .error { color: #DC3545 !important; margin-top: 24px; font-weight: 600; padding: 18px 24px; background: #ffebee; border-radius: 14px; border-left: 5px solid #DC3545; display: flex; align-items: center; font-size: 15px; }
    .launch-btn { background: linear-gradient(135deg, #003366 0%, #0066CC 100%) !important; color: white !important; padding: 18px 48px !important; font-size: 17px !important; font-weight: 700 !important; box-shadow: 0 8px 24px rgba(0, 51, 102, 0.25) !important; border-radius: 14px !important; transition: all 0.3s ease !important; }
    .launch-btn:hover { box-shadow: 0 12px 32px rgba(0, 51, 102, 0.35) !important; transform: translateY(-2px) !important; }
    .launch-btn:active { transform: translateY(0) !important; box-shadow: 0 4px 16px rgba(0, 51, 102, 0.2) !important; }
    .launch-btn:disabled { background: #ccc !important; box-shadow: none !important; transform: none !important; }
    .time-info { color: #cbd5e1 !important; font-size: 16px; font-weight: 600; display: flex; align-items: center; gap: 10px; }
    .hint-box { background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%) !important; border-left: 5px solid #0066CC; padding: 32px; border-radius: 20px; margin-top: 40px; border: none !important; }
    .hint-box h4 { color: #003366 !important; margin-bottom: 20px; font-weight: 800; display: flex; align-items: center; gap: 12px; font-size: 19px; }
    .hint-box ul { margin-left: 32px; color: #495057 !important; line-height: 2; }
    .hint-box li { margin-bottom: 10px; font-size: 15px; }
    .recent-section h3 { font-size: 24px; font-weight: 700; color: #ffffff !important; margin-bottom: 20px; display: flex; align-items: center; gap: 10px; }
    .recent-list { background: white !important; border-radius: 16px; padding: 24px; box-shadow: 0 8px 24px rgba(0,0,0,0.08); border: none !important; }
    .recent-item { display: flex; align-items: center; padding: 16px; border-bottom: 1px solid #e9ecef; cursor: pointer; transition: all 0.3s ease; }
    .recent-item:last-child { border-bottom: none; }
    .recent-item:hover { background: #f8f9fa; }
  `]
})
export class NewRunComponent implements OnInit, AfterViewInit, OnDestroy {
  private runsService = inject(RunsService);
  private router = inject(Router);
  private elementRef = inject(ElementRef);
  
  requirements = '';
  loading = false;
  error = '';
  private observer: IntersectionObserver | null = null;

  stats = { totalRuns: 1247, successRate: 94, avgTime: '4.2 мин', activeUsers: 23 };
  recentRuns = [
    { id: 'run-1247', name: 'Парковочный помощник', status: 'succeeded', time: '2 мин назад' },
    { id: 'run-1246', name: 'Складской учёт', status: 'succeeded', time: '15 мин назад' }
  ];

  ngOnInit() {}
  ngAfterViewInit() { this.setupScrollAnimations(); }
  ngOnDestroy() { if (this.observer) this.observer.disconnect(); }

  private setupScrollAnimations() {
    this.observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        entry.isIntersecting ? entry.target.classList.add('visible') : entry.target.classList.remove('visible');
      });
    }, { threshold: 0.15, rootMargin: '0px 0px -50px 0px' });
    this.elementRef.nativeElement.querySelectorAll('.animate-slide-up').forEach((el: Element) => this.observer?.observe(el));
  }

  getStatusIcon(status: string): string { return status === 'succeeded' ? 'check_circle' : 'error'; }
  getStatusColor(status: string): string { return status === 'succeeded' ? '#4caf50' : '#f44336'; }
  navigateToStatus(id: string) { this.router.navigate(['/status', id]); }

  startRun() {
    if (!this.requirements.trim()) {
      this.error = 'Введите бизнес-требования';
      return;
    }
    this.error = '';
    this.loading = true;
    
    this.runsService.createRun(this.requirements).subscribe({
      next: (res) => this.router.navigate(['/status', res.runId]),
      error: (err) => {
        this.loading = false;
        this.error = 'Ошибка: ' + (err.message || 'Неизвестная ошибка');
      }
    });
  }
}