import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, provideAppInitializer, provideZoneChangeDetection } from '@angular/core';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideMarkdown } from 'ngx-markdown';
import { provideMonacoEditor } from 'ngx-monaco-editor-v2';

import { routes } from './app.routes';
import { activeOrgInterceptor } from './core/interceptors/active-org.interceptor';
import { authInterceptor } from './core/interceptors/auth.interceptor';
import { forbiddenInterceptor } from './core/interceptors/forbidden.interceptor';
import { networkConnectionInterceptor } from './core/interceptors/network-connection.interceptor';
import { preflightPermissionInterceptor } from './core/interceptors/preflight-permission.interceptor';
import { validationErrorsInterceptor } from './core/interceptors/validation-errors.interceptor';
import { provideConfigureModelsStorages } from './features/configure-models/configure-models.providers';
import { provideFlowsStorages } from './features/flows/flows.providers';
import { provideKnowledgeSourcesStorages } from './features/knowledge-sources/knowledge-sources.providers';
import { provideRoleBaseAccessStorages } from './features/role-base-access/role-base-access.providers';
import { provideToolsStorages } from './features/tools/tools.providers';
import { ActiveOrgService } from './services/auth/active-org.service';
import { PermissionsService } from './services/auth/permissions.service';
import { ConfigService } from './services/config';
import { APP_STORAGE } from './shared/services/app-storage.token';
import { provideSharedStorages } from './shared/services/shared-storages.providers';

export const appConfig: ApplicationConfig = {
    providers: [
        provideZoneChangeDetection({ eventCoalescing: true }),
        provideRouter(routes, withComponentInputBinding()),

        provideHttpClient(
            withInterceptors([
                preflightPermissionInterceptor,
                authInterceptor,
                activeOrgInterceptor,
                validationErrorsInterceptor,
                forbiddenInterceptor,
                networkConnectionInterceptor,
            ])
        ),
        provideMarkdown(),
        provideMonacoEditor(),

        provideAppInitializer(() => {
            const configService = inject(ConfigService);
            return configService.loadConfig();
        }),
        {
            provide: MAT_FORM_FIELD_DEFAULT_OPTIONS,
            useValue: {
                appearance: 'outline',
            },
        },

        { provide: APP_STORAGE, useExisting: ActiveOrgService, multi: true },
        { provide: APP_STORAGE, useExisting: PermissionsService, multi: true },
        ...provideRoleBaseAccessStorages(),
        ...provideConfigureModelsStorages(),
        ...provideFlowsStorages(),
        ...provideToolsStorages(),
        ...provideKnowledgeSourcesStorages(),
        ...provideSharedStorages(),
    ],
};
