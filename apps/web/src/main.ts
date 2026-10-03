import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

import { environment } from './environments/environment';

bootstrapApplication(App, appConfig)
  .catch((err) => console.error(err));

// Installable, offline-readable app (BACKLOG 9.6): production builds only, so
// development never serves stale files.
if (environment.production && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js');
  });
}
