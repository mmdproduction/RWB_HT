import { Component, inject, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { RunsService, RunDetail } from '../../services/runs.service';

@Component({
  selector: 'app-run-result',
  standalone: true,
  imports: [CommonModule, MatCardModule, MatButtonModule, MatProgressSpinnerModule],
  templateUrl: './run-result.component.html',
  styles: [`
    .container { max-width: 1000px; margin: 0 auto; padding: 24px; }
    .header { text-align: center; margin-bottom: 48px; }
    .header h1 {
      font-size: 48px;
      font-weight: 900;
      background: linear-gradient(135deg, #ffffff 0%, #4fc3f7 50%, #ffffff 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 16px;
      text-transform: uppercase;
      letter-spacing: -2px;
      text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .header p { color: #e2e8f0 !important; font-size: 18px; text-shadow: 0 2px 4px rgba(0, 0, 0, 0.4); }
    
    .success-banner {
      background: linear-gradient(135deg, #4caf50 0%, #66bb6a 100%);
      color: white;
      padding: 48px 40px;
      border-radius: 20px;
      text-align: center;
      margin-bottom: 40px;
      box-shadow: 0 12px 40px rgba(76, 175, 80, 0.3);
    }
    .success-icon {
      width: 80px;
      height: 80px;
      margin-bottom: 20px;
      animation: bounce 1s ease infinite;
    }
    @keyframes bounce {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-10px); }
    }
    .success-banner h2 { font-size: 32px; font-weight: 800; margin-bottom: 8px; }
    .success-banner p { font-size: 18px; opacity: 0.95; }
    
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 20px;
      margin-bottom: 40px;
    }
    .metric-card {
      background: white;
      padding: 28px;
      border-radius: 16px;
      box-shadow: 0 8px 24px rgba(0,0,0,0.08);
      text-align: center;
      transition: all 0.3s ease;
      border: none !important;
    }
    .metric-card:hover {
      transform: translateY(-4px);
      box-shadow: 0 12px 32px rgba(0,0,0,0.12);
    }
    .metric-value {
      font-size: 36px;
      font-weight: 800;
      background: linear-gradient(135deg, #003366, #0066CC);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      margin-bottom: 8px;
    }
    .metric-label {
      font-size: 13px;
      color: #64748b !important;
      text-transform: uppercase;
      letter-spacing: 1px;
      font-weight: 600;
    }
    
    .links-section {
      background: transparent !important;
      padding: 36px;
      border-radius: 20px;
      box-shadow: none !important;
      margin-bottom: 40px;
      border: none !important;
    }
    .links-section h3 {
      font-size: 32px;
      font-weight: 900;
      background: linear-gradient(135deg, #ffffff 0%, #4fc3f7 50%, #ffffff 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 24px;
      text-transform: uppercase;
      letter-spacing: -1px;
      text-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }
    .link-item {
      display: flex;
      align-items: center;
      padding: 20px;
      background: rgba(255, 255, 255, 0.95);
      border-radius: 12px;
      margin-bottom: 16px;
      transition: all 0.3s ease;
      box-shadow: 0 4px 16px rgba(0,0,0,0.1);
    }
    .link-item:hover {
      background: rgba(255, 255, 255, 1);
      transform: translateX(4px);
    }
    .link-icon {
      width: 48px;
      height: 48px;
      background: linear-gradient(135deg, #003366, #0066CC);
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-right: 20px;
      flex-shrink: 0;
    }
    .link-content { flex: 1; }
    .link-title { font-weight: 700; color: #212529 !important; margin-bottom: 4px; }
    .link-url { color: #0066CC !important; font-size: 14px; word-break: break-all; }
    .link-action { margin-left: 16px; }
    
    .actions {
      display: flex;
      gap: 16px;
      justify-content: center;
      flex-wrap: wrap;
    }
    .action-btn {
      padding: 14px 32px !important;
      font-size: 15px !important;
      font-weight: 700 !important;
      border-radius: 12px !important;
    }
  `]
})
export class RunResultComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private runsService = inject(RunsService);
  
  runId = '';
  run: RunDetail | null = null;

  ngOnInit() {
    this.runId = this.route.snapshot.paramMap.get('runId') || '';
    this.runsService.getRun(this.runId).subscribe({
      next: (data) => this.run = data,
      error: (err) => console.error('Ошибка загрузки:', err)
    });
  }

  openApp() {
    if (this.run?.appUrl) {
      window.open(this.run.appUrl, '_blank');
    }
  }

  openRepo() {
    if (this.run?.repoUrl) {
      window.open(this.run.repoUrl, '_blank');
    }
  }

  newRun() {
    this.router.navigate(['/new']);
  }
}