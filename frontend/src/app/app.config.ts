import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, provideAppInitializer, provideZoneChangeDetection } from '@angular/core';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';
import { MAT_TOOLTIP_DEFAULT_OPTIONS, MatTooltipDefaultOptions } from '@angular/material/tooltip';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideMarkdown } from 'ngx-markdown';
import { provideMonacoEditor } from 'ngx-monaco-editor-v2';
import { firstValueFrom } from 'rxjs';

import { routes } from './app.routes';
import { APP_TOURS } from './app.tours';
import { SAFE_MARKED_OPTIONS_PROVIDER } from './core/config/safe-markdown-options.factory';
import { ProfileTourProgressStore, provideGuidedTours, TOUR_PROGRESS_STORE } from './core/guided-tour';
import { activeOrgInterceptor } from './core/interceptors/active-org.interceptor';
import { authInterceptor } from './core/interceptors/auth.interceptor';
import { forbiddenInterceptor } from './core/interceptors/forbidden.interceptor';
import { networkConnectionInterceptor } from './core/interceptors/network-connection.interceptor';
import { preflightPermissionInterceptor } from './core/interceptors/preflight-permission.interceptor';
import { validationErrorsInterceptor } from './core/interceptors/validation-errors.interceptor';
import { provideAuditStorages } from './features/audit/audit.providers';
import { provideChatStorages } from './features/chat/chat.providers';
import { provideConfigureModelsStorages } from './features/configure-models/configure-models.providers';
import { provideFlowsStorages } from './features/flows/flows.providers';
import { provideKeyValueTablesStorages } from './features/key-value-tables/key-value-tables.providers';
import { provideKnowledgeSourcesStorages } from './features/knowledge-sources/knowledge-sources.providers';
import { providePluginsExtensions, providePluginsStorages } from './features/plugins/plugins.providers';
import { provideRoleBaseAccessStorages } from './features/role-base-access/role-base-access.providers';
import { provideToolsStorages } from './features/tools/tools.providers';
import { ActiveOrgService } from './services/auth/active-org.service';
import { AuthService } from './services/auth/auth.service';
import { PermissionsService } from './services/auth/permissions.service';
import { ConfigService } from './services/config';
import { APP_STORAGE } from './shared/services/app-storage.token';
import { provideSharedStorages } from './shared/services/shared-storages.providers';
import { provideVisualProgrammingStorages } from './visual-programming/visual-programming.providers';

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
        provideMarkdown({ markedOptions: SAFE_MARKED_OPTIONS_PROVIDER }),
        provideMonacoEditor(),
        provideGuidedTours(...APP_TOURS),
        { provide: TOUR_PROGRESS_STORE, useExisting: ProfileTourProgressStore },

        provideAppInitializer(async () => {
            const configService = inject(ConfigService);
            const authService = inject(AuthService);
            await configService.loadConfig();
            await firstValueFrom(authService.restoreSession());
        }),
        {
            provide: MAT_FORM_FIELD_DEFAULT_OPTIONS,
            useValue: {
                appearance: 'outline',
            },
        },
        {
            // Without a delay, every pointer pass over a dense canvas or table flashes tooltips.
            // Material replaces its defaults with this object instead of merging, so the other two repeat its values.
            provide: MAT_TOOLTIP_DEFAULT_OPTIONS,
            useValue: { showDelay: 400, hideDelay: 0, touchendHideDelay: 1500 } satisfies MatTooltipDefaultOptions,
        },

        { provide: APP_STORAGE, useExisting: ActiveOrgService, multi: true },
        { provide: APP_STORAGE, useExisting: PermissionsService, multi: true },
        ...provideRoleBaseAccessStorages(),
        ...provideAuditStorages(),
        ...provideConfigureModelsStorages(),
        ...provideFlowsStorages(),
        ...provideToolsStorages(),
        ...provideKnowledgeSourcesStorages(),
        ...provideKeyValueTablesStorages(),
        ...provideChatStorages(),
        ...providePluginsStorages(),
        ...providePluginsExtensions(),
        ...provideSharedStorages(),
        ...provideVisualProgrammingStorages(),
    ],
};
