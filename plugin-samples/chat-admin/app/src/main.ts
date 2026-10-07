// First: the sandbox throws on storage access, so the stand-in must exist before any library touches it.
// angular.json also lists it under "polyfills": with code splitting, chunks shared with lazy routes are
// evaluated before main's own code, and only a separate entry is guaranteed to run before all of them.
import '@epicstaff/plugin-sdk/storage-shim';

import { bootstrapApplication } from '@angular/platform-browser';

import { AppComponent } from './app/app.component';
import { appConfig } from './app/app.config';

bootstrapApplication(AppComponent, appConfig).catch((error: unknown) => console.error(error));
