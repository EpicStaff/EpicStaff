import { Routes } from '@angular/router';

import { UnsavedChangesGuard } from './core/guards/unsaved-changes.guard';
import { MainLayoutComponent } from './layouts/main-layout/main-layout.component';

export const routes: Routes = [
    {
        path: '',
        component: MainLayoutComponent,
        children: [
            {
                path: '',
                redirectTo: 'projects',
                pathMatch: 'full',
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
                    import('./open-project-page/open-project-page.component').then((m) => m.OpenProjectPageComponent),
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
                    { path: '', redirectTo: 'custom', pathMatch: 'full' },
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
                    { path: '', redirectTo: 'my', pathMatch: 'full' },
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
                loadComponent: () =>
                    import('./features/knowledge-sources/pages/collections-list-page/collections-list-page.component').then(
                        (m) => m.CollectionsListPageComponent
                    ),
            },
            {
                path: 'chats',
                loadComponent: () =>
                    import('./pages/chats-page/chats-page.component').then((m) => m.ChatsPageComponent),
            },

            { path: '**', redirectTo: '' },
        ],
    },
];
