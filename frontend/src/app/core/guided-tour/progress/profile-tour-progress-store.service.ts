import { computed, inject, Injectable } from '@angular/core';
import { map, Observable } from 'rxjs';

import { ProfileService } from '../../../services/auth/profile.service';
import { TourProgressStore } from './tour-progress-store';

/**
 * Tour progress kept with the user's profile: the profile lists the tours the user completed, and each completion is
 * saved by its own call. Any valid tour key can be saved; the backend caps how many distinct tours one user can
 * complete, and a save past that cap fails like any other failed save.
 */
@Injectable({
    providedIn: 'root',
})
export class ProfileTourProgressStore implements TourProgressStore {
    private readonly profileService = inject(ProfileService);

    readonly userId = computed<number | null>(() => this.profileService.currentUserSignal()?.id ?? null);
    readonly completedTourKeys = computed<ReadonlySet<string>>(
        () => new Set(this.profileService.currentUserSignal()?.completed_tours ?? [])
    );

    markCompleted(tourKey: string): Observable<void> {
        return this.profileService.markTourCompleted(tourKey).pipe(map(() => undefined));
    }
}
