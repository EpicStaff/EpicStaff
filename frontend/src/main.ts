// main.ts
import { bootstrapApplication } from '@angular/platform-browser';

import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';

// Setup Monaco environment with webpack approach
(window as unknown as { MonacoEnvironment: Record<string, unknown> }).MonacoEnvironment = {
    getWorkerUrl: function () {
        return './assets/monaco/min/vs/base/worker/workerMain.js';
    },
};
bootstrapApplication(AppComponent, appConfig).catch((err) => console.error(err));
