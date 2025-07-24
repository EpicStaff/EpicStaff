import { Routes } from '@angular/router';
import { MainLayoutComponent } from './layouts/main-layout/main-layout.component';

import { BuiltInToolsComponent } from './features/tools/pages/tools-list-page/components/built-in-tools/built-in-tools.component';
import { CustomToolsComponent } from './features/tools/pages/tools-list-page/components/custom-tools/custom-tools.component';

import { OpenProjectPageComponent } from './open-project-page/open-project-page.component';

import { FlowVisualProgrammingComponent } from './pages/flows-page/components/flow-visual-programming/flow-visual-programming.component';
import { StaffPageComponent } from './pages/staff-page/staff-page.component';
import { RunningGraphComponent } from './pages/running-graph/running-graph-page.component';
import { KnowledgeSourcesComponent } from './pages/knowledge-sources/knowledge-sources.component';
import { ChatsPageComponent } from './pages/chats-page/chats-page.component';

import { ProjectsListPageComponent } from './features/projects/pages/projects-list-page/projects-list-page.component';
import { MyProjectsComponent } from './features/projects/pages/projects-list-page/components/my-projects/my-projects.component';
import { ProjectTemplatesComponent } from './features/projects/pages/projects-list-page/components/templates/project-templates.component';
import { MyFlowsComponent } from './features/flows/pages/flows-list-page/components/my-flows/my-flows.component';
import { FlowTemplatesComponent } from './features/flows/pages/flows-list-page/components/flow-templates/flow-templates.component';
import { UnsavedChangesGuard } from './core/guards/unsaved-changes.guard';
import { ToolsListPageComponent } from './features/tools/pages/tools-list-page/tools-list-page.component';
import { FlowsListPageComponent } from './features/flows/pages/flows-list-page/flows-list-page.component';

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
        component: ProjectsListPageComponent,
        children: [
          { path: '', redirectTo: 'my', pathMatch: 'full' },
          { path: 'my', component: MyProjectsComponent },
          { path: 'templates', component: ProjectTemplatesComponent },
        ],
      },
      { path: 'projects/:projectId', component: OpenProjectPageComponent },
      {
        path: 'staff',
        component: StaffPageComponent,
      },
      {
        path: 'tools',
        component: ToolsListPageComponent,
        children: [
          { path: '', redirectTo: 'built-in', pathMatch: 'full' },
          { path: 'built-in', component: BuiltInToolsComponent },
          { path: 'custom', component: CustomToolsComponent },
        ],
      },
      {
        path: 'flows',
        component: FlowsListPageComponent,
        children: [
          { path: '', redirectTo: 'my', pathMatch: 'full' },
          { path: 'my', component: MyFlowsComponent },
          { path: 'templates', component: FlowTemplatesComponent },
        ],
      },
      {
        path: 'flows/:id',
        component: FlowVisualProgrammingComponent,
        canDeactivate: [UnsavedChangesGuard],
      },
      {
        path: 'graph/:graphId/session/:sessionId',
        component: RunningGraphComponent,
      },
      {
        path: 'knowledge-sources',
        component: KnowledgeSourcesComponent,
      },
      {
        path: 'chats',
        component: ChatsPageComponent,
      },

      { path: '**', redirectTo: '' },
    ],
  },
];
