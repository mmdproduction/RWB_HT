import { Component } from '@angular/core';
import { RouterOutlet, RouterLink } from '@angular/router';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [
    RouterOutlet, 
    RouterLink, 
    MatToolbarModule, 
    MatButtonModule,
    MatIconModule  // <-- ДОБАВЛЕНО
  ],
  templateUrl: './app.component.html'
})
export class AppComponent {
  title = 'platform-ui';
}