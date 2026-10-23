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
    it('consumes plugins/<identifier> and everything below it, with identifier as the route param', () => {
        const deep = segments('plugins', 'weather', 'forecast', 'berlin');

        expect(pluginPageMatcher(segments('plugins', 'weather'))).toEqual({
            consumed: segments('plugins', 'weather'),
            posParams: { identifier: new UrlSegment('weather', {}) },
        });
        expect(pluginPageMatcher(deep)?.consumed).toBe(deep);
        expect(pluginPageMatcher(deep)?.posParams?.['identifier'].path).toBe('weather');
    });

    it('matches nothing else', () => {
        expect(pluginPageMatcher(segments('plugins'))).toBeNull();
        expect(pluginPageMatcher(segments('flows', 'weather'))).toBeNull();
        expect(pluginPageMatcher([])).toBeNull();
    });

    it('matches no address with matrix params on any segment, so they can never stand in for the identifier', () => {
        const withParams = (index: number): UrlSegment[] =>
            segments('plugins', 'weather', 'forecast').map((segment, position) =>
                position === index ? new UrlSegment(segment.path, { identifier: 'chat' }) : segment
            );

        for (const index of [0, 1, 2]) {
            expect(pluginPageMatcher(withParams(index))).toBeNull();
        }
    });

    it('leaves /plugins/weather/x;identifier=chat unmatched by the router, rather than opening chat', async () => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    { matcher: pluginPageMatcher, component: StubPageComponent },
                    { path: '**', component: FallbackPageComponent },
                ]),
            ],
        });
        const harness = await RouterTestingHarness.create();

        const routed = await harness.navigateByUrl('/plugins/weather/forecast;identifier=chat');

        expect(routed).toBeInstanceOf(FallbackPageComponent);
    });

    it('keeps a /plugins/<identifier> link active on every deep link of that plugin, and only that one', async () => {
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

        await harness.navigateByUrl('/plugins/weather/forecast/berlin?days=3');

        expect(isActive('/plugins/weather', router, subset)()).toBe(true);
        expect(isActive('/plugins/weathers', router, subset)()).toBe(false);
        expect(isActive('/plugins/chat', router, subset)()).toBe(false);
    });
});
