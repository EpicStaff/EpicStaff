import { inject } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { ActionCode, ResourceCode } from '@shared/models';

import { authGuard } from './core/guards/auth.guard';
import { bootstrapGuard } from './core/guards/bootstrap.guard';
import { guestGuard } from './core/guards/guest.guard';
import { onboardingGuard, resourceGuard, unassignedGuard } from './core/guards/resource.guard';
import { UnsavedChangesGuard } from './core/guards/unsaved-changes.guard';
import { permissionGuard, superAdminGuard, workspaceGuard } from './core/guards/workspace.guard';
import { CustomToolsPort } from './features/tools/pages/tools-list-page/components/tools-list/custom-tools.port';
import { McpToolsPort } from './features/tools/pages/tools-list-page/components/tools-list/mcp-tools.port';
import { TOOLS_LIST_PORT } from './features/tools/pages/tools-list-page/components/tools-list/tools-list-port';
import { MainLayoutComponent } from './layouts/main-layout/main-layout.component';
import { RoutedAuthShellComponent } from './layouts/routed-auth-shell/routed-auth-shell.component';
import { PermissionsService } from './services/auth/permissions.service';
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
        path: 'forgot-password',
        loadComponent: () =>
            import('./features/auth/components/forgot-pass-page/forgot-password-page.component').then(
                (m) => m.ForgotPasswordPageComponent
            ),
        canActivate: [guestGuard],
    },
    {
        path: 'reset-password',
        loadComponent: () =>
            import('./features/auth/components/reset-password-page/reset-password-page.component').then(
                (m) => m.ResetPasswordPageComponent
            ),
        canActivate: [guestGuard],
    },
    {
        path: '',
        component: RoutedAuthShellComponent,
        canActivate: [authGuard, bootstrapGuard],
        children: [
            {
                path: 'onboarding',
                loadComponent: () =>
                    import('./features/auth/components/onboarding-page/onboarding-page.component').then(
                        (m) => m.OnboardingPageComponent
                    ),
                canActivate: [onboardingGuard],
            },
            {
                path: 'unassigned',
                loadComponent: () =>
                    import('./features/auth/components/unassigned-user-page/unassigned-user-page.component').then(
                        (m) => m.UnassignedUserPageComponent
                    ),
                canActivate: [unassignedGuard],
            },
            {
                path: '',
                component: MainLayoutComponent,
                canActivate: [resourceGuard],
                children: [
                    {
                        path: '',
                        canActivate: [
                            () => {
                                return inject(Router).parseUrl(inject(PermissionsService).resolveDefaultRoute());
                            },
                        ],
                        children: [],
                    },
                    {
                        path: 'agents',
                        loadComponent: () =>
                            import('./features/agent-definitions/pages/agent-definitions-page/agent-definitions-page.component').then(
                                (m) => m.AgentDefinitionsPageComponent
                            ),
                        canDeactivate: [UnsavedChangesGuard],
                        canActivate: [permissionGuard],
                        data: { permission: [ResourceCode.Agents, ActionCode.Read] },
                    },
                    // Legacy CrewAI routes. `**` only acts as a wildcard when it is the
                    // whole path, so it has to live in children — `path: 'projects/**'`
                    // would match the literal URL /projects/** and nothing else. Nesting
                    // it here also swallows any depth (/projects/12/edit) instead of
                    // carrying the leftover segments over to /agents.
                    {
                        path: 'projects',
                        children: [{ path: '**', redirectTo: '/agents' }],
                    },
                    {
                        path: 'staff',
                        redirectTo: '/agents',
                        pathMatch: 'full',
                    },
                    {
                        path: 'tools',
                        loadComponent: () =>
                            import('./features/tools/pages/tools-list-page/tools-list-page.component').then(
                                (m) => m.ToolsListPageComponent
                            ),
                        canActivate: [permissionGuard],
                        data: { permission: [ResourceCode.Tools, ActionCode.Read] },
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
                                    import('./features/tools/pages/tools-list-page/components/tools-list/tools-list.component').then(
                                        (m) => m.ToolsListComponent
                                    ),
                                providers: [{ provide: TOOLS_LIST_PORT, useClass: CustomToolsPort }],
                            },
                            {
                                path: 'mcp',
                                loadComponent: () =>
                                    import('./features/tools/pages/tools-list-page/components/tools-list/tools-list.component').then(
                                        (m) => m.ToolsListComponent
                                    ),
                                providers: [{ provide: TOOLS_LIST_PORT, useClass: McpToolsPort }],
                            },
                        ],
                    },
                    {
                        path: 'flows',
                        loadComponent: () =>
                            import('./features/flows/pages/flows-list-page/flows-list-page.component').then(
                                (m) => m.FlowsListPageComponent
                            ),
                        canActivate: [permissionGuard],
                        data: { permission: [ResourceCode.Flows, ActionCode.Read] },
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
                        canActivate: [permissionGuard],
                        data: { permission: [ResourceCode.Flows, ActionCode.Read] },
                        canDeactivate: [UnsavedChangesGuard],
                    },
                    {
                        path: 'graph/:graphId/session/:sessionId',
                        loadComponent: () =>
                            import('./pages/running-graph/pages/running-graph-page/running-graph-page.component').then(
                                (m) => m.RunningGraphComponent
                            ),
                        canActivate: [permissionGuard],
                        data: { permission: [ResourceCode.Flows, ActionCode.Read] },
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
                                canActivate: [permissionGuard],
                                data: { permission: [ResourceCode.KnowledgeSources, ActionCode.Read] },
                            },
                            {
                                path: 'storage',
                                loadComponent: () =>
                                    import('./features/files/pages/files-list-page/components/storage-page/storage-page.component').then(
                                        (m) => m.StoragePageComponent
                                    ),
                                canActivate: [permissionGuard],
                                data: { permission: [ResourceCode.Files, ActionCode.Read] },
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
                        canActivate: [permissionGuard],
                        data: { permission: [ResourceCode.Flows, ActionCode.Read] },
                    },
                    {
                        path: 'workspace',
                        loadComponent: () =>
                            import('./features/role-base-access/pages/overview-page/overview.component').then(
                                (m) => m.OverviewComponent
                            ),
                        canActivate: [workspaceGuard],
                        children: [
                            {
                                path: '',
                                redirectTo: 'main',
                                pathMatch: 'full',
                            },
                            {
                                path: 'main',
                                loadComponent: () =>
                                    import('./features/role-base-access/pages/overview-page/main-tab/main-tab.component').then(
                                        (m) => m.MainTabComponent
                                    ),
                                canActivate: [superAdminGuard],
                            },
                            {
                                path: 'organizations',
                                loadComponent: () =>
                                    import('./features/role-base-access/pages/overview-page/organizations-tab/organizations-tab.component').then(
                                        (m) => m.OrganizationsTabComponent
                                    ),
                                canActivate: [permissionGuard],
                                data: { permission: [ResourceCode.Organizations, ActionCode.Read] },
                            },
                            {
                                path: 'users',
                                loadComponent: () =>
                                    import('./features/role-base-access/pages/overview-page/users-tab/users-tab.component').then(
                                        (m) => m.UsersTabComponent
                                    ),
                                canActivate: [permissionGuard],
                                data: { permission: [ResourceCode.Users, ActionCode.Read] },
                            },
                            {
                                path: 'roles',
                                loadComponent: () =>
                                    import('./features/role-base-access/pages/overview-page/roles-tab/roles-tab.component').then(
                                        (m) => m.RolesTabComponent
                                    ),
                                canActivate: [permissionGuard],
                                data: { permission: [ResourceCode.Roles, ActionCode.Read] },
                            },
                            {
                                path: 'api-keys',
                                loadComponent: () =>
                                    import('./features/role-base-access/pages/overview-page/api-keys-tab/api-keys-tab.component').then(
                                        (m) => m.ApiKeysTabComponent
                                    ),
                                canActivate: [permissionGuard],
                                data: { permission: [ResourceCode.Secrets, ActionCode.Read] },
                            },
                        ],
                    },
                    {
                        path: 'profile',
                        loadComponent: () =>
                            import('./features/role-base-access/pages/profile-page/profile-page.component').then(
                                (m) => m.ProfilePageComponent
                            ),
                        children: [
                            {
                                path: '',
                                redirectTo: 'overview',
                                pathMatch: 'full',
                            },
                            {
                                path: 'overview',
                                loadComponent: () =>
                                    import('./features/role-base-access/pages/profile-page/overview-tab/profile-overview-tab.component').then(
                                        (m) => m.ProfileOverviewTabComponent
                                    ),
                            },
                            {
                                path: 'api-keys',
                                loadComponent: () =>
                                    import('./features/role-base-access/pages/profile-page/api-keys-tab/profile-api-keys-tab.component').then(
                                        (m) => m.ProfileApiKeysTabComponent
                                    ),
                            },
                        ],
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
