import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { isActive, provideRouter, Router, UrlSegment } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { pluginPageMatcher } from './plugin-page.matcher';

@Component({ template: '' })
class StubPageComponent {}

@Component({ template: '' })
class FallbackPageComponent {}

function segments(...paths: string[]): UrlSegment[] {
    return paths.map((path) => new UrlSegment(path, {}));
}

describe('pluginPageMatcher', () => {
    it('consumes plugins/<id> and everything below it, with id as the route param', () => {
        const deep = segments('plugins', '7', 'conversations', 'c_1');

        expect(pluginPageMatcher(segments('plugins', '7'))).toEqual({
            consumed: segments('plugins', '7'),
            posParams: { id: new UrlSegment('7', {}) },
        });
        expect(pluginPageMatcher(deep)?.consumed).toBe(deep);
        expect(pluginPageMatcher(deep)?.posParams?.['id'].path).toBe('7');
    });

    it('matches nothing else', () => {
        expect(pluginPageMatcher(segments('plugins'))).toBeNull();
        expect(pluginPageMatcher(segments('flows', '7'))).toBeNull();
        expect(pluginPageMatcher([])).toBeNull();
    });

    it('matches no address with matrix params on any segment, so they can never stand in for the id', () => {
        const withParams = (index: number): UrlSegment[] =>
            segments('plugins', '7', 'conversations').map((segment, position) =>
                position === index ? new UrlSegment(segment.path, { id: '9' }) : segment
            );

        for (const index of [0, 1, 2]) {
            expect(pluginPageMatcher(withParams(index))).toBeNull();
        }
    });

    it('leaves /plugins/7/x;id=9 unmatched by the router, rather than opening plugin 9', async () => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    { matcher: pluginPageMatcher, component: StubPageComponent },
                    { path: '**', component: FallbackPageComponent },
                ]),
            ],
        });
        const harness = await RouterTestingHarness.create();

        const routed = await harness.navigateByUrl('/plugins/7/conversations;id=9');

        expect(routed).toBeInstanceOf(FallbackPageComponent);
    });

    it('keeps a /plugins/<id> link active on every deep link of that plugin, and only that one', async () => {
        TestBed.configureTestingModule({
            providers: [provideRouter([{ matcher: pluginPageMatcher, component: StubPageComponent }])],
        });
        const harness = await RouterTestingHarness.create();
        const router = TestBed.inject(Router);
        // What the sidenav's routerLinkActive with `{ exact: false }` checks.
        const subset = {
            paths: 'subset',
            queryParams: 'subset',
            fragment: 'ignored',
            matrixParams: 'ignored',
        } as const;

        await harness.navigateByUrl('/plugins/7/conversations/c_1?sort=key');

        expect(isActive('/plugins/7', router, subset)()).toBe(true);
        expect(isActive('/plugins/70', router, subset)()).toBe(false);
        expect(isActive('/plugins/8', router, subset)()).toBe(false);
    });
});
