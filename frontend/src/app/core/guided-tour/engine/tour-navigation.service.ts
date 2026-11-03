import { inject, Injectable } from '@angular/core';
import {
    Event as RouterEvent,
    Navigation,
    NavigationCancel,
    NavigationCancellationCode,
    NavigationEnd,
    NavigationError,
    NavigationSkipped,
    Router,
} from '@angular/router';
import { map, Observable, take } from 'rxjs';
import { filter } from 'rxjs/operators';

import { isAtOrUnderPath, isOnPath } from './tour-url-match';

/**
 * Whether `event` ends a navigation for good. A guard redirect or a superseding navigation also cancels one, but
 * another navigation follows, so those are not the end.
 */
function isNavigationSettled(event: RouterEvent): boolean {
    if (event instanceof NavigationCancel) {
        return (
            event.code !== NavigationCancellationCode.Redirect &&
            event.code !== NavigationCancellationCode.SupersededByNewNavigation
        );
    }
    return event instanceof NavigationEnd || event instanceof NavigationError || event instanceof NavigationSkipped;
}

/** The router side of a tour: taking the user somewhere, and noticing when they leave. */
@Injectable({
    providedIn: 'root',
})
export class TourNavigation {
    private readonly router = inject(Router);

    /**
     * Brings the user to `url`. Emits once the router has settled there (at once if it already is), then completes;
     * completes without emitting when the navigation settles elsewhere, e.g. the user chose to stay in the page's
     * unsaved-changes dialog. Unsubscribing stops waiting; the navigation itself goes on.
     *
     * There is only ever one navigation. One already heading under `followNavigationsInto` (e.g. started by the link the
     * user clicked, maybe waiting on that dialog) is followed: a second one would supersede it and ask the page again.
     * Any other navigation in flight is superseded by the tour's own.
     */
    arriveAt(url: string, followNavigationsInto: string = url): Observable<void> {
        return new Observable<void>((subscriber) => {
            const navigation = this.router.currentNavigation();
            if (!navigation && this.isOn(this.router.url, url)) {
                subscriber.next();
                subscriber.complete();
                return undefined;
            }
            const settled = this.router.events.pipe(filter(isNavigationSettled), take(1)).subscribe(() => {
                if (this.isOn(this.router.url, url)) {
                    subscriber.next();
                }
                subscriber.complete();
            });
            if (!navigation || !this.isHeadingInto(navigation, followNavigationsInto)) {
                void this.router.navigateByUrl(url);
            }
            return settled;
        });
    }

    /** Emits each time a navigation ends anywhere but `url` (by path; query parameters and fragment may change). */
    leaves(url: string): Observable<void> {
        return this.router.events.pipe(
            filter((event): event is NavigationEnd => event instanceof NavigationEnd),
            filter((event) => !this.isOn(event.urlAfterRedirects, url)),
            map(() => undefined)
        );
    }

    /** Recognised routes may have redirected (finalUrl); before recognition only the requested URL is known. */
    private isHeadingInto(navigation: Navigation, url: string): boolean {
        return isAtOrUnderPath(navigation.finalUrl ?? navigation.extractedUrl, this.router.parseUrl(url));
    }

    private isOn(currentUrl: string, url: string): boolean {
        return isOnPath(this.router.parseUrl(currentUrl), this.router.parseUrl(url));
    }
}
