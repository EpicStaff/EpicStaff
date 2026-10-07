import {
    type ApplicationConfig,
    inject,
    provideAppInitializer,
    provideBrowserGlobalErrorListeners,
    provideZonelessChangeDetection,
} from '@angular/core';
import { provideRouter, withComponentInputBinding, withHashLocation } from '@angular/router';

import { routes } from './app.routes';
import { PluginBridgeService } from './core/plugin-bridge.service';

export const appConfig: ApplicationConfig = {
    providers: [
        provideBrowserGlobalErrorListeners(),
        provideZonelessChangeDetection(),
        provideRouter(routes, withHashLocation(), withComponentInputBinding()),
        // Connect before the router's first navigation, so nav sync reports it and the theme is in place.
        provideAppInitializer(() => inject(PluginBridgeService).connect()),
    ],
};
