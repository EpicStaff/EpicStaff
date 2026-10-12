import { Route } from '@angular/router';

import { routes } from './app.routes';
import { permissionGuard } from './core/guards/workspace.guard';
import { chatEnabledGuard } from './features/chat/guards/chat-enabled.guard';

const findRoute = (list: Route[], path: string): Route | undefined => {
    for (const route of list) {
        if (route.path === path) return route;
        const nested = findRoute(route.children ?? [], path);
        if (nested) return nested;
    }
    return undefined;
};

describe('chat routes', () => {
    it('serves the bindings list, the all-bindings inbox and a binding workspace behind the chat guards', () => {
        const chat = findRoute(routes, 'chat-bindings')!;
        expect(chat.canActivate).toEqual([chatEnabledGuard, permissionGuard]);
        expect(chat.children?.map((child) => child.path)).toEqual(['', 'all', ':bindingId']);
        expect(chat.children?.every((child) => typeof child.loadComponent === 'function')).toBe(true);
    });

    it('redirects the old chat page to the bindings list', () => {
        expect(findRoute(routes, 'chat')).toEqual(
            expect.objectContaining({ redirectTo: 'chat-bindings', pathMatch: 'full' })
        );
    });
});
