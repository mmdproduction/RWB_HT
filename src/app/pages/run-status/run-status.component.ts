import { Component, inject, OnInit, OnDestroy } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatChipsModule } from '@angular/material/chips';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { CommonModule } from '@angular/common';
import { RunsService, RunDetail, RunStatus, StageStatus } from '../../services/runs.service';

@Component({
  selector: 'app-run-status',
  standalone: true,
  imports: [
    CommonModule,
    MatCardModule, 
    MatButtonModule, 
    MatChipsModule,
    MatProgressBarModule,
    MatListModule,
    MatIconModule,
    MatProgressSpinnerModule
  ],
  templateUrl: './run-status.component.html',
  styles: [`
    .container { max-width: 900px; margin: 0 auto; padding: 24px; }
    .header { text-align: center; margin-bottom: 40px; }
    .header h1 {
      font-size: 42px;
      font-weight: 800;
      background: linear-gradient(135deg, #ffffff 0%, #4fc3f7 50%, #ffffff 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 12px;
      text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .header p { 
      color: #e2e8f0 !important; 
      font-size: 16px; 
      font-weight: 500;
      text-shadow: 0 2px 4px rgba(0, 0, 0, 0.4);
    }
    
    .status-text {
      font-size: 36px;
      font-weight: 900;
      margin: 0;
      letter-spacing: 1px;
      text-transform: uppercase;
    }
    .status-waiting {
      background: linear-gradient(135deg, #ffffff 0%, #4fc3f7 50%, #ffffff 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .status-generating {
      background: linear-gradient(90deg, #ff9800, #ff5722, #ff9800);
      background-size: 200% auto;
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      animation: gradient-flow 2s linear infinite;
    }
    @keyframes gradient-flow {
      0% { background-position: 0% center; }
      100% { background-position: 200% center; }
    }
    .status-completed {
      background: linear-gradient(135deg, #4caf50 0%, #66bb6a 50%, #4caf50 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-shadow: 0 4px 12px rgba(76, 175, 80, 0.3);
    }
    
    .stages-section { margin-bottom: 40px; }
    .stages-section h2 {
      font-size: 32px;
      font-weight: 900;
      background: linear-gradient(135deg, #ffffff 0%, #4fc3f7 50%, #ffffff 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 20px;
      text-transform: uppercase;
      letter-spacing: -1px;
      text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .stage-item { 
      display: flex; 
      align-items: center; 
      padding: 16px 20px; 
      margin-bottom: 12px;
      background: white;
      border-radius: 14px;
      transition: all 0.3s ease;
      box-shadow: 0 2px 12px rgba(0,0,0,0.04);
      border: none !important;
      overflow: visible !important;
    }
    .stage-icon { 
      margin-right: 20px; 
      font-size: 28px !important;
      width: 28px !important;
      height: 28px !important;
      min-width: 28px !important;
      min-height: 28px !important;
      line-height: 28px !important;
      display: inline-flex !important;
      align-items: center !important;
      justify-content: center !important;
      overflow: visible !important;
      -webkit-text-fill-color: currentColor !important; 
    }
    .stage-item.active { 
      background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
      border-left: 5px solid #0066CC;
      box-shadow: 0 8px 24px rgba(0, 102, 204, 0.15);
      transform: translateX(8px);
    }
    .stage-item.completed { 
      background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%);
      border-left: 5px solid #4caf50;
      box-shadow: 0 4px 16px rgba(76, 175, 80, 0.1);
    }
    .stage-item.failed { 
      background: linear-gradient(135deg, #ffebee 0%, #ffcdd2 100%);
      border-left: 5px solid #f44336;
    }
    .stage-content { flex: 1; }
    .stage-name { font-weight: 700; font-size: 16px; margin-bottom: 4px; color: #212529 !important; }
    .stage-status { 
      font-size: 13px; 
      color: #64748b !important; 
      text-transform: uppercase; 
      letter-spacing: 0.5px; 
      font-weight: 600;
    }
    
    .logs-section { 
      margin-top: 40px; 
      background: #1e1e1e !important; 
      border-radius: 16px; 
      overflow: hidden;
      box-shadow: 0 12px 40px rgba(0,0,0,0.2);
      border: none !important;
    }
    .logs-header { 
      background: linear-gradient(135deg, #333 0%, #222 100%);
      color: #fff !important; 
      padding: 16px 24px; 
      font-weight: 700;
      font-size: 15px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .logs-content { 
      color: #00ff00 !important; 
      padding: 20px 24px; 
      font-family: 'Courier New', monospace; 
      font-size: 13px;
      max-height: 300px; 
      overflow-y: auto;
      white-space: pre-wrap;
      line-height: 1.8;
    }
    .log-line { margin-bottom: 6px; animation: fadeIn 0.3s ease; }
    @keyframes fadeIn {
      from { opacity: 0; transform: translateY(-10px); }
      to { opacity: 1; transform: translateY(0); }
    }
  `]
})
export class RunStatusComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private runsService = inject(RunsService);
  
  runId = '';
  run: RunDetail | null = null;
  error = '';
  progress = 0;
  elapsedTime = 0;
  private timer: any;

  ngOnInit() {
    this.runId = this.route.snapshot.paramMap.get('runId') || '';
    this.poll();
    this.timer = setInterval(() => {
      this.poll();
      this.elapsedTime++;
    }, 1000);
  }

  ngOnDestroy() { 
    if (this.timer) clearInterval(this.timer); 
  }

  poll() {
    this.runsService.getRun(this.runId).subscribe({
      next: (data) => {
        this.run = data;
        this.error = '';
        this.calculateProgress();
      },
      error: () => this.error = 'Не удалось получить статус'
    });
  }

  calculateProgress() {
    if (!this.run) return;
    const totalStages = this.run.stages.length;
    const completedStages = this.run.stages.filter(s => 
      s.status === 'passed' || s.status === 'failed'
    ).length;
    this.progress = Math.round((completedStages / totalStages) * 100);
  }

  goToResult() { 
    // ИСПРАВЛЕНИЕ: ведём на внутреннюю страницу результата
    this.router.navigate(['/result', this.runId]); 
  }
  
  getStageIcon(status: StageStatus): string {
    if (status === 'passed') return 'check_circle';
    if (status === 'failed') return 'error';
    if (status === 'running') return 'sync';
    if (status === 'blocked') return 'block';
    return 'pending';
  }

  getStageClass(status: StageStatus): string {
    if (status === 'passed') return 'completed';
    if (status === 'running') return 'active';
    if (status === 'failed' || status === 'blocked') return 'failed';
    return '';
  }

  getStatusClass(): string {
    if (this.progress === 0) return 'status-waiting';
    if (this.progress === 100) return 'status-completed';
    return 'status-generating';
  }

  getStatusText(): string {
    if (this.progress === 0) return 'ОЖИДАНИЕ';
    if (this.progress === 100) return 'ЗАВЕРШЕНО';
    return 'ГЕНЕРАЦИЯ...';
  }

  formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
  }
}