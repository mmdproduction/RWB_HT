import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { productFetch } from '../product-api';

@Component({
  selector: 'generated-panel',
  standalone: true,
  imports: [CommonModule, FormsModule, MatButtonModule, MatCardModule, MatProgressBarModule],
  templateUrl: './generated-panel.html',
  styleUrls: ['./generated-panel.css']
})
export class GeneratedPanel implements OnInit, OnDestroy {
  loading = true;
  error = '';
  session: any = null;
  events: any[] = [];
  private timer: any;

  ngOnInit() {
    this.load();
    this.timer = setInterval(() => this.load(true), 5000);
  }

  ngOnDestroy() {
    if (this.timer) clearInterval(this.timer);
  }

  async load(quiet = false) {
    if (!quiet) {
      this.loading = true;
      this.error = '';
    }
    try {
      const res = await productFetch('/api/generated/status');
      if (!res.ok) throw new Error('Ошибка загрузки данных');
      const data = await res.json();
      this.session = data.session;
      this.events = data.events || [];
    } catch (e: any) {
      if (!quiet) this.error = e.message || 'Не удалось загрузить данные';
    } finally {
      if (!quiet) this.loading = false;
    }
  }

  get remainingMinutes(): number {
    if (!this.session?.remainingSeconds) return 0;
    return Math.floor(this.session.remainingSeconds / 60);
  }

  get isWarning(): boolean {
    return this.session && this.session.remainingSeconds <= 600;
  }

  trackById(index: number, item: any): any {
    return item.id;
  }
}
