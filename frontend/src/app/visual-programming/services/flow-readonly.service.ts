import { computed, DestroyRef, inject, Injectable } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActionCode, ResourceCode } from '@shared/models';
import { Subject, throttleTime } from 'rxjs';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';

/**
 * Whether the visual-programming editor may change the flow: not for a user with Flows:Read
 * without Flows:Update, and never inside a version preview. Also owns the throttled message
 * shown when a write interaction is blocked.
 *
 * `providedIn: 'root'` for the live editor; the version preview gets its own instance through
 * FLOW_EDITOR_STATE_PROVIDERS, next to its FLOW_EDITOR_PREVIEW = true.
 */
@Injectable({ providedIn: 'root' })
export class FlowReadOnlyService {
    public readonly isPreview = inject(FLOW_EDITOR_PREVIEW);

    private readonly perms = inject(PermissionsService);
    private readonly toast = inject(ToastService);
    private readonly destroyRef = inject(DestroyRef);

    public readonly isReadOnly = computed(
        () => this.isPreview || !this.perms.can(ResourceCode.Flows, ActionCode.Update)
    );

    private readonly blocked$ = new Subject<void>();

    constructor() {
        this.blocked$.pipe(throttleTime(3000), takeUntilDestroyed(this.destroyRef)).subscribe(() => {
            if (this.isPreview) {
                this.toast.info('Preview mode is read-only. Exit preview to edit the flow', 3000, 'bottom-right');
                return;
            }
            this.toast.info('You have read-only access to this flow.');
        });
    }

    /** Say why a write interaction was blocked, at most once per 3 seconds. */
    public notifyBlocked(): void {
        this.blocked$.next();
    }
}
