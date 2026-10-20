import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { config } from 'rxjs';

import { afterNavigationRender, isPlainPrimaryClick } from './navigation.util';

@Component({ template: '' })
class OwnerComponent {}

@Component({ template: '' })
class PageComponent {}

describe('afterNavigationRender', () => {
    let letThrough: (allowed: boolean) => void = () => undefined;

    let fixture: ComponentFixture<OwnerComponent>;

    // The hooks belong to the owner's view: they run when it renders.
    const render = (): void => fixture.detectChanges();
    const nextMacrotask = (): Promise<void> => new Promise((resolve) => setTimeout(resolve));

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    {
                        // Held at its guard until a spec lets it through: a navigation in progress.
                        path: 'slow',
                        canActivate: [() => new Promise<boolean>((resolve) => (letThrough = resolve))],
                        component: PageComponent,
                    },
                ]),
            ],
        });
        fixture = TestBed.createComponent(OwnerComponent);
    });

    /** Starts a navigation that waits at its guard, then lets `callback` wait for it. */
    async function waitForSlowNavigation(callback: () => void): Promise<{ navigation: Promise<boolean> }> {
        const router = TestBed.inject(Router);
        const navigation = router.navigateByUrl('/slow');
        await nextMacrotask();
        afterNavigationRender(router, fixture.componentRef.injector, callback);
        render();
        // Wrapped: an async function's returned promise would be waited for, and this one waits for `letThrough`.
        return { navigation };
    }

    it('runs right after the next render when no navigation is in progress', () => {
        const callback = vi.fn();
        afterNavigationRender(TestBed.inject(Router), fixture.componentRef.injector, callback);
        expect(callback).not.toHaveBeenCalled();
        render();
        expect(callback).toHaveBeenCalledTimes(1);
    });

    it('waits for a navigation in progress, then for the render after it', async () => {
        const callback = vi.fn();
        const { navigation } = await waitForSlowNavigation(callback);
        expect(callback).not.toHaveBeenCalled();

        letThrough(true);
        await navigation;
        expect(callback).not.toHaveBeenCalled();
        render();
        expect(callback).toHaveBeenCalledTimes(1);
    });

    it('runs nothing, and throws nothing, when its owner is destroyed before the navigation ends', async () => {
        // An error thrown in a router event subscriber is collected here, not thrown.
        const errors: unknown[] = [];
        const reportUnhandledError = config.onUnhandledError;
        config.onUnhandledError = (error) => errors.push(error);
        try {
            const callback = vi.fn();
            const { navigation } = await waitForSlowNavigation(callback);

            fixture.destroy();
            letThrough(true);
            await navigation;
            // RxJS reports it a macrotask later.
            await nextMacrotask();

            expect(errors).toEqual([]);
            expect(callback).not.toHaveBeenCalled();
        } finally {
            config.onUnhandledError = reportUnhandledError;
        }
    });
});

describe('isPlainPrimaryClick', () => {
    it('is a primary click without a modifier key, as RouterLink follows it', () => {
        expect(isPlainPrimaryClick(new MouseEvent('click', { button: 0 }))).toBe(true);
        expect(isPlainPrimaryClick(new MouseEvent('click', { button: 1 }))).toBe(false);
        for (const modifier of ['ctrlKey', 'metaKey', 'shiftKey', 'altKey'] as const) {
            expect(isPlainPrimaryClick(new MouseEvent('click', { button: 0, [modifier]: true }))).toBe(false);
        }
    });
});
