import { provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { APP_INITIALIZER, ApplicationConfig, provideZoneChangeDetection } from '@angular/core';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideMarkdown } from 'ngx-markdown';
import { provideMonacoEditor } from 'ngx-monaco-editor-v2';

import { routes } from './app.routes';
import { activeOrgInterceptor } from './core/interceptors/active-org.interceptor';
import { authInterceptor } from './core/interceptors/auth.interceptor';
import { forbiddenInterceptor } from './core/interceptors/forbidden.interceptor';
import { validationErrorsInterceptor } from './core/interceptors/validation-errors.interceptor';
import { ConfigService } from './services/config/config.service';

export function initializeApp(configService: ConfigService) {
    return () => configService.loadConfig();
}

export const appConfig: ApplicationConfig = {
    providers: [
        provideZoneChangeDetection({ eventCoalescing: true }),
        provideRouter(routes, withComponentInputBinding()),

        provideHttpClient(
            withXhr(),
            withInterceptors([authInterceptor, activeOrgInterceptor, validationErrorsInterceptor, forbiddenInterceptor])
        ),
        provideMarkdown(),
        provideMonacoEditor(),

        {
            provide: APP_INITIALIZER,
            useFactory: initializeApp,
            deps: [ConfigService],
            multi: true,
        },
        {
            provide: MAT_FORM_FIELD_DEFAULT_OPTIONS,
            useValue: {
                appearance: 'outline',
            },
        },
    ],
};
