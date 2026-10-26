import { computed, inject, Injectable } from '@angular/core';
import { map, Observable, throwError } from 'rxjs';

import type { TourProgressStore } from '../../core/guided-tour';
import { ProfileService } from '../../services/auth/profile.service';
import { QUICK_START_TOUR_KEY } from './quick-start-tour.definition';

/**
 * Tour progress over today's profile API, which keeps a single flag: whether the user completed the Quick Start tour.
 * So only that tour's key is stored, and saving any other fails. It lives with the Quick Start feature because that
 * flag is the feature's; an adapter over generic per-tour storage replaces it once the backend has one.
 */
@Injectable({
    providedIn: 'root',
})
export class ProfileTourProgressStore implements TourProgressStore {
    private readonly profileService = inject(ProfileService);

    readonly userId = computed<number | null>(() => this.profileService.currentUserSignal()?.id ?? null);
    readonly completedTourKeys = computed<ReadonlySet<string>>(() =>
        this.profileService.currentUserSignal()?.quickstart_tour_completed
            ? new Set([QUICK_START_TOUR_KEY])
            : new Set<string>()
    );

    markCompleted(tourKey: string): Observable<void> {
        if (tourKey !== QUICK_START_TOUR_KEY) {
            return throwError(() => new Error(`The profile API cannot store the progress of tour "${tourKey}".`));
        }
        return this.profileService.markQuickStartTourCompleted().pipe(map(() => undefined));
    }
}
