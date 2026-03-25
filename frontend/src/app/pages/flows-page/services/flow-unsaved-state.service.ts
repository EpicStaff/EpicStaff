import { Injectable } from '@angular/core';
import { Observable, of, switchMap } from 'rxjs';
import { CanComponentDeactivate } from '../../../core/guards/unsaved-changes.guard';

interface FlowRefreshTarget extends CanComponentDeactivate {
    refreshCurrentFlow: () => void;
}

/**
 * Keeps a reference to the currently active flow component so that
 * external callers can reuse its canDeactivate logic and existing
 * "unsaved changes" dialog before refreshing only the flow content.
 */
@Injectable({
    providedIn: 'root',
})
export class FlowUnsavedStateService {
    private flowComponent: FlowRefreshTarget | null = null;

    public register(component: FlowRefreshTarget): void {
        this.flowComponent = component;
    }

    public unregister(): void {
        this.flowComponent = null;
    }

    /**
     * Asks the current flow component (via its canDeactivate) whether it
     * is safe to leave, and on approval refreshes only the current flow.
     */
    public confirmAndRefreshFlow(): Observable<void> {
        const comp = this.flowComponent;
        if (!comp?.canDeactivate) {
            this.reloadPage();
            return of(void 0);
        }
        if (!comp.refreshCurrentFlow) {
            this.reloadPage();
            return of(void 0);
        }

        const result = comp.canDeactivate();
        const result$ = typeof result === 'boolean' ? of(result) : result;

        return result$.pipe(
            switchMap((allowed) => {
                if (allowed) {
                    comp.refreshCurrentFlow();
                }
                return of(void 0);
            })
        );
    }

    private reloadPage(): void {
        window.location.reload();
    }
}

