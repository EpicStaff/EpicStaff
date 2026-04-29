import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';

import { authGuard } from './core/guards/auth.guard';
import { guestGuard } from './core/guards/guest.guard';
import { onboardingGuard } from './core/guards/onboarding.guard';
import { UnsavedChangesGuard } from './core/guards/unsaved-changes.guard';
import { MainLayoutComponent } from './layouts/main-layout/main-layout.component';
import { RoutedAuthShellComponent } from './layouts/routed-auth-shell/routed-auth-shell.component';
import { LastVisitedTabService } from './services/last-visited-tab.service';

export const routes: Routes = [
    {
        path: 'login',
        loadComponent: () =>
            import('./features/auth/components/login-page/login-page.component').then((m) => m.LoginPageComponent),
        canActivate: [guestGuard],
    },
    {
        path: 'sign-up',
        loadComponent: () =>
            import('./features/auth/components/sign-up-page/sign-up-page.component').then((m) => m.SignUpPageComponent),
        canActivate: [guestGuard],
    },
    {
        path: 'onboarding',
        loadComponent: () =>
            import('./features/auth/components/onboarding-page/onboarding-page.component').then(
                (m) => m.OnboardingPageComponent
            ),
        canActivate: [onboardingGuard],
    },
    {
        path: '',
        component: RoutedAuthShellComponent,
        canActivate: [authGuard],
        children: [
            {
                path: '',
                component: MainLayoutComponent,
                children: [
                    {
                        path: '',
                        canActivate: [
                            () => {
                                const last = inject(LastVisitedTabService).get('/projects');
                                return inject(Router).parseUrl(last ?? '/projects/my');
                            },
                        ],
                        children: [],
                    },
                    {
                        path: 'projects',
                        loadComponent: () =>
                            import('./features/projects/pages/projects-list-page/projects-list-page.component').then(
                                (m) => m.ProjectsListPageComponent
                            ),
                        children: [
                            { path: '', redirectTo: 'my', pathMatch: 'full' },
                            {
                                path: 'my',
                                loadComponent: () =>
                                    import('./features/projects/pages/projects-list-page/components/my-projects/my-projects.component').then(
                                        (m) => m.MyProjectsComponent
                                    ),
                            },
                            {
                                path: 'templates',
                                loadComponent: () =>
                                    import('./features/projects/pages/projects-list-page/components/templates/project-templates.component').then(
                                        (m) => m.ProjectTemplatesComponent
                                    ),
                            },
                        ],
                    },
                    {
                        path: 'projects/:projectId',
                        loadComponent: () =>
                            import('./open-project-page/open-project-page.component').then(
                                (m) => m.OpenProjectPageComponent
                            ),
                        canDeactivate: [UnsavedChangesGuard],
                    },
                    {
                        path: 'staff',
                        loadComponent: () =>
                            import('./pages/staff-page/staff-page.component').then((m) => m.StaffPageComponent),
                        canDeactivate: [UnsavedChangesGuard],
                    },
                    {
                        path: 'tools',
                        loadComponent: () =>
                            import('./features/tools/pages/tools-list-page/tools-list-page.component').then(
                                (m) => m.ToolsListPageComponent
                            ),
                        children: [
                            {
                                path: '',
                                canActivate: [
                                    () => {
                                        const last = inject(LastVisitedTabService).get('/tools');
                                        return inject(Router).parseUrl(last ?? '/tools/custom');
                                    },
                                ],
                                children: [],
                            },
                            {
                                path: 'custom',
                                loadComponent: () =>
                                    import('./features/tools/pages/tools-list-page/components/custom-tools/custom-tools.component').then(
                                        (m) => m.CustomToolsComponent
                                    ),
                            },
                            {
                                path: 'mcp',
                                loadComponent: () =>
                                    import('./features/tools/pages/tools-list-page/components/mcp-tools/mcp-tools.component').then(
                                        (m) => m.McpToolsComponent
                                    ),
                            },
                        ],
                    },
                    {
                        path: 'flows',
                        loadComponent: () =>
                            import('./features/flows/pages/flows-list-page/flows-list-page.component').then(
                                (m) => m.FlowsListPageComponent
                            ),
                        children: [
                            {
                                path: '',
                                canActivate: [
                                    () => {
                                        const last = inject(LastVisitedTabService).get('/flows');
                                        return inject(Router).parseUrl(last ?? '/flows/my');
                                    },
                                ],
                                children: [],
                            },
                            {
                                path: 'my',
                                loadComponent: () =>
                                    import('./features/flows/pages/flows-list-page/components/my-flows/my-flows.component').then(
                                        (m) => m.MyFlowsComponent
                                    ),
                            },
                            {
                                path: 'templates',
                                loadComponent: () =>
                                    import('./features/flows/pages/flows-list-page/components/flow-templates/flow-templates.component').then(
                                        (m) => m.FlowTemplatesComponent
                                    ),
                            },
                        ],
                    },
                    {
                        path: 'flows/:id',
                        loadComponent: () =>
                            import('./pages/flows-page/components/flow-visual-programming/flow-visual-programming.component').then(
                                (m) => m.FlowVisualProgrammingComponent
                            ),
                        canDeactivate: [UnsavedChangesGuard],
                    },
                    {
                        path: 'graph/:graphId/session/:sessionId',
                        loadComponent: () =>
                            import('./pages/running-graph/pages/running-graph-page/running-graph-page.component').then(
                                (m) => m.RunningGraphComponent
                            ),
                    },
                    {
                        path: 'knowledge-sources',
                        redirectTo: 'files',
                        pathMatch: 'full',
                    },
                    {
                        path: 'files',
                        loadComponent: () =>
                            import('./features/files/pages/files-list-page/files-list-page.component').then(
                                (m) => m.FilesListPageComponent
                            ),
                        children: [
                            {
                                path: '',
                                canActivate: [
                                    () => {
                                        const last = inject(LastVisitedTabService).get('/files');
                                        return inject(Router).parseUrl(last ?? '/files/knowledge-sources');
                                    },
                                ],
                                children: [],
                            },
                            {
                                path: 'knowledge-sources',
                                loadComponent: () =>
                                    import('./features/knowledge-sources/pages/collections-list-page/collections-list-page.component').then(
                                        (m) => m.CollectionsListPageComponent
                                    ),
                            },
                            {
                                path: 'storage',
                                loadComponent: () =>
                                    import('./features/files/pages/files-list-page/components/storage-page/storage-page.component').then(
                                        (m) => m.StoragePageComponent
                                    ),
                            },
                        ],
                    },
                    {
                        path: 'chats',
                        loadComponent: () =>
                            import('./pages/chats-page/chats-page.component').then((m) => m.ChatsPageComponent),
                    },
                    {
                        path: 'sessions',
                        loadComponent: () =>
                            import('./features/flows/pages/global-sessions-list/global-sessions-list.component').then(
                                (m) => m.GlobalSessionsListComponent
                            ),
                    },
                ],
            },
            {
                path: '**',
                loadComponent: () =>
                    import('./pages/not-found-page/not-found-page.component').then((m) => m.NotFoundPageComponent),
            },
        ],
    },
];
