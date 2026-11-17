import { afterNextRender, DestroyRef, Injector } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ActivatedRoute,
    NavigationCancel,
    NavigationEnd,
    NavigationError,
    NavigationSkipped,
    Router,
} from '@angular/router';
import { filter, take } from 'rxjs';

/** A router URL without its query and fragment: the page it shows, whatever state the page keeps in its query. */
export function urlPath(url: string): string {
    return url.split(/[?#]/)[0];
}

/** How a router navigation can end: done, cancelled, failed, or skipped (to the URL already shown). */
export type NavigationOver = NavigationEnd | NavigationCancel | NavigationError | NavigationSkipped;

export function isNavigationOver(event: unknown): event is NavigationOver {
    return (
        event instanceof NavigationEnd ||
        event instanceof NavigationCancel ||
        event instanceof NavigationError ||
        event instanceof NavigationSkipped
    );
}

/**
 * Runs `callback` after the next render or, while a navigation is in progress then, after the render that follows its
 * end: the focus a closing panel hands back finds the page that navigation leads to, not the one it leaves. Nothing
 * runs once `injector`'s owner is destroyed (that navigation may have replaced it).
 */
export function afterNavigationRender(router: Router, injector: Injector, callback: () => void): void {
    const destroyRef = injector.get(DestroyRef);
    afterNextRender(
        () => {
            if (!router.currentNavigation()) {
                callback();
                return;
            }
            router.events.pipe(filter(isNavigationOver), take(1), takeUntilDestroyed(destroyRef)).subscribe(() => {
                if (!destroyRef.destroyed) afterNextRender(callback, { injector });
            });
        },
        { injector }
    );
}

/**
 * A click that follows a link in the page: the primary button without a modifier key. RouterLink leaves the others
 * (a new tab, a new window, a download) to the browser, so they leave the page, and its open panels, as they are.
 */
export function isPlainPrimaryClick(event: MouseEvent): boolean {
    return event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey;
}

/**
 * Reads a page's one-shot deep-link query params (a link that opens one item) and drops them from the URL, so a reload
 * or a Back navigation does not open the item again. A param the URL lacks is absent from the result.
 *
 * Call it once as the page starts (`ngOnInit`) and keep the result until the page's data has loaded. Called later, from
 * a load's callback, its URL cleanup would cancel a navigation the user started while the data loaded.
 */
export function takeQueryParams<Name extends string>(
    route: ActivatedRoute,
    router: Router,
    names: readonly Name[]
): Partial<Record<Name, string>> {
    const params: Partial<Record<Name, string>> = {};
    for (const name of names) {
        const value = route.snapshot.queryParamMap.get(name);
        if (value !== null) params[name] = value;
    }
    if (Object.keys(params).length === 0) return params;
    void router.navigate([], {
        relativeTo: route,
        queryParams: Object.fromEntries(names.map((name) => [name, null])),
        queryParamsHandling: 'merge',
        preserveFragment: true,
        replaceUrl: true,
        // The history entry is replaced, so it keeps the state the navigation that made it carried.
        state: router.lastSuccessfulNavigation()?.extras.state,
    });
    return params;
}
