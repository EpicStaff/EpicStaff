import { InjectionToken, Signal } from '@angular/core';
import { Observable } from 'rxjs';

/** Which tours the signed-in user has completed, and where that is saved. The engine knows nothing else of storage. */
export interface TourProgressStore {
    /** The signed-in user the progress belongs to; null while nobody is signed in or the profile is still loading. */
    readonly userId: Signal<number | null>;
    /** Keys of the tours the user finished or skipped. Empty while nobody is signed in. */
    readonly completedTourKeys: Signal<ReadonlySet<string>>;
    /** Saves `tourKey` as completed for the signed-in user. Saving it twice is harmless. */
    markCompleted(tourKey: string): Observable<void>;
}

/**
 * Bound at the composition root, next to provideGuidedTours() (which explains why it is separate); specs bind a fake.
 * No default on purpose: without a binding GuidedTourService fails to be created, rather than lose progress quietly.
 */
export const TOUR_PROGRESS_STORE = new InjectionToken<TourProgressStore>('TOUR_PROGRESS_STORE');
