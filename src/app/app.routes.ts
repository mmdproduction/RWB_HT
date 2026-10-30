import { Routes } from '@angular/router';
import { NewRunComponent } from './pages/new-run/new-run.component';
import { RunStatusComponent } from './pages/run-status/run-status.component';
import { RunResultComponent } from './pages/run-result/run-result.component';

export const routes: Routes = [
  { path: '', redirectTo: '/new', pathMatch: 'full' },
  { path: 'new', component: NewRunComponent },
  { path: 'status/:runId', component: RunStatusComponent },
  { path: 'result/:runId', component: RunResultComponent },
  { path: '**', redirectTo: '/new' }
];