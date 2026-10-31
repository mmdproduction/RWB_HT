import { Component } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';
import { QwenStatusComponent } from '../qwen-status';
import { EnvironmentStatusComponent } from './environment-status';
import { MatButtonModule } from '@angular/material/button';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    RouterOutlet, 
    RouterLink, 
    MatButtonModule,
    QwenStatusComponent,
    EnvironmentStatusComponent
  ],
  templateUrl: './app.component.html'
})
export class AppComponent {
  title = 'platform-ui';
}
