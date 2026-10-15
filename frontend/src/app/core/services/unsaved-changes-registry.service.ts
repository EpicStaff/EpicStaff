import { Injectable } from '@angular/core';
import { isObservable, Observable, of } from 'rxjs';

import { CanComponentDeactivate } from '../guards/unsaved-changes.guard';

/**
 * Registry of the currently-active component that owns unsaved changes.
 *
 * Some in-app actions (e.g. switching organization) do not trigger Angular's
 * CanDeactivate flow but still need to show the same unsaved-changes dialog
 * before proceeding. Pages implementing CanComponentDeactivate register
 * themselves here so callers can invoke canDeactivate() directly and decide
 * whether to continue.
 */
@Injectable({
    providedIn: 'root',
})
export class UnsavedChangesRegistry {
    private component: CanComponentDeactivate | null = null;

    register(component: CanComponentDeactivate): void {
        this.component = component;
    }

    unregister(component: CanComponentDeactivate): void {
        if (this.component === component) {
            this.component = null;
        }
    }

    /** Returns true if the current view allows leaving (or nothing is registered). */
    canLeave(): Observable<boolean> {
        if (!this.component) return of(true);
        const result = this.component.canDeactivate();
        return isObservable(result) ? result : of(result);
    }
}
