import { Injectable } from '@angular/core';
import { isObservable, Observable, of } from 'rxjs';

import { CanComponentDeactivate } from '../guards/unsaved-changes.guard';

interface Entry {
    component: CanComponentDeactivate;
    onRefresh?: () => void;
}

/**
 * Registry of the currently-active component that owns unsaved changes.
 *
 * Some in-app actions (e.g. switching organization, refreshing the current
 * view from an external event) do not trigger Angular's CanDeactivate flow
 * but still need to show the same unsaved-changes dialog before proceeding.
 * Pages implementing CanComponentDeactivate register themselves here so
 * callers can invoke canDeactivate() directly and decide whether to continue.
 */
@Injectable({
    providedIn: 'root',
})
export class UnsavedChangesRegistry {
    private entry: Entry | null = null;

    register(component: CanComponentDeactivate, options?: { onRefresh?: () => void }): void {
        this.entry = { component, onRefresh: options?.onRefresh };
    }

    unregister(component: CanComponentDeactivate): void {
        if (this.entry?.component === component) {
            this.entry = null;
        }
    }

    /** Returns true if the current view allows leaving (or nothing is registered). */
    canLeave(): Observable<boolean> {
        const entry = this.entry;
        if (!entry) return of(true);
        const result = entry.component.canDeactivate();
        return isObservable(result) ? result : of(result);
    }

    /**
     * Asks the current view whether it is safe to leave; on approval, runs its
     * onRefresh handler (if registered) or falls back to a full page reload.
     */
    confirmAndRefresh(): void {
        const entry = this.entry;
        if (!entry?.onRefresh) {
            window.location.reload();
            return;
        }
        this.canLeave().subscribe((allowed) => {
            if (allowed) entry.onRefresh!();
        });
    }
}
