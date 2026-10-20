import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Route, Router, RouterOutlet } from '@angular/router';

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

@Component({ template: '' })
class StubPageComponent {}

@Component({ imports: [RouterOutlet], template: '<router-outlet />' })
class StubShellComponent {}

describe('chat routes', () => {
    it('serves All desks and a desk page inside the desks shell, behind the chat guards; the bare path opens All desks', () => {
        const chat = findRoute(routes, 'chat-bindings')!;
        expect(chat.canActivate).toEqual([chatEnabledGuard, permissionGuard]);
        // The shell holds the desk rail, so it stays while the pages below it change.
        expect(typeof chat.loadComponent).toBe('function');
        const [bare, ...pages] = chat.children ?? [];
        expect(bare).toEqual({ path: '', redirectTo: 'all', pathMatch: 'full' });
        expect(pages.map((child) => child.path)).toEqual(['all', ':bindingId']);
        expect(pages.every((child) => typeof child.loadComponent === 'function')).toBe(true);
    });

    it('redirects the old chat page to the desks', () => {
        expect(findRoute(routes, 'chat')).toEqual(
            expect.objectContaining({ redirectTo: 'chat-bindings', pathMatch: 'full' })
        );
    });

    it('lands both /chat-bindings and the old /chat on All desks', async () => {
        const chat = findRoute(routes, 'chat-bindings')!;
        // The real redirects, with the guards let through and the lazy shell and pages stubbed.
        const pagesStubbed = (chat.children ?? []).map((child) =>
            child.loadComponent ? { path: child.path, component: StubPageComponent } : child
        );
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    findRoute(routes, 'chat')!,
                    { path: chat.path, component: StubShellComponent, children: pagesStubbed },
                ]),
            ],
        });
        const router = TestBed.inject(Router);

        await router.navigateByUrl('/chat-bindings');
        expect(router.url).toBe('/chat-bindings/all');

        await router.navigateByUrl('/chat-bindings/b-1');
        expect(router.url).toBe('/chat-bindings/b-1');

        await router.navigateByUrl('/chat');
        expect(router.url).toBe('/chat-bindings/all');
    });
});
