import { computed, effect, inject, Injectable } from '@angular/core';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ToastService } from '../../services/notifications';
import { FLOW_EDITOR_PREVIEW } from '../core/providers/flow-editor-preview.token';

/**
 * Whether the visual-programming editor may change the flow: not for a user with Flows:Read
 * without Flows:Update, and never inside a version preview. Also owns the message shown when a
 * write interaction is blocked.
 *
 * `providedIn: 'root'` for the live editor; the version preview gets its own instance through
 * FLOW_EDITOR_STATE_PROVIDERS, next to its FLOW_EDITOR_PREVIEW = true.
 */
@Injectable({ providedIn: 'root' })
export class FlowReadOnlyService {
    public readonly isPreview = inject(FLOW_EDITOR_PREVIEW);

    private readonly perms = inject(PermissionsService);
    private readonly toast = inject(ToastService);

    public readonly isReadOnly = computed(
        () => this.isPreview || !this.perms.can(ResourceCode.Flows, ActionCode.Update)
    );

    private hasNotified = false;

    private readonly resetNotificationEffect = effect(() => {
        if (!this.isReadOnly()) {
            this.hasNotified = false;
        }
    });

    /**
     * In a preview, every blocked action says why (nothing else on screen explains it). A read-only
     * user is told once per read-only session.
     */
    public notifyBlocked(): void {
        if (this.isPreview) {
            this.toast.info('Preview mode is read-only. Exit preview to edit the flow', 3000, 'bottom-right');
            return;
        }
        if (this.hasNotified) return;
        this.hasNotified = true;
        this.toast.info('You have read-only access to this flow.');
    }
}
