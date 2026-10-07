import type { Routes } from '@angular/router';

import { ChatPageComponent } from './chat/chat-page/chat-page.component';

/**
 * Hash routes (`#/conversations/c_…`): a sandboxed page may only change its URL's query and
 * fragment, and the SDK reports every change to EpicStaff, which shows it in its own address bar.
 */
export const routes: Routes = [
    { path: '', pathMatch: 'full', redirectTo: 'chat' },
    { path: 'chat', component: ChatPageComponent, title: 'Chat' },
    { path: 'chat/:id', component: ChatPageComponent, title: 'Chat' },
    {
        path: 'conversations',
        title: 'Conversations',
        loadComponent: () =>
            import('./conversations/conversations-page/conversations-page.component').then(
                (module) => module.ConversationsPageComponent
            ),
    },
    {
        path: 'conversations/:key',
        title: 'Conversation',
        loadComponent: () =>
            import('./conversations/conversation-detail-page/conversation-detail-page.component').then(
                (module) => module.ConversationDetailPageComponent
            ),
    },
    {
        path: 'about',
        title: 'About',
        loadComponent: () =>
            import('./about/about-page/about-page.component').then((module) => module.AboutPageComponent),
    },
    { path: '**', redirectTo: 'chat' },
];
