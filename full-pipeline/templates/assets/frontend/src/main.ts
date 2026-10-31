import { bootstrapApplication } from '@angular/platform-browser';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';
import { provideServiceWorker } from '@angular/service-worker';
import { AppComponent } from './app/app';
bootstrapApplication(AppComponent, {providers:[provideAnimationsAsync(),provideServiceWorker('ngsw-worker.js',{enabled:true,registrationStrategy:'registerWhenStable:30000'})]}).catch(console.error);
