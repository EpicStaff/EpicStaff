import { Dialog } from '@angular/cdk/dialog';
import { inject, Injectable, Injector } from '@angular/core';
import { map, Observable } from 'rxjs';

import { InlineSurface } from '../../../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';
import { LocalSurfaceDialogComponent, LocalSurfaceDialogData } from './local-surface-dialog.component';

/**
 * Opens the full-screen "Local Surface" editor dialog, which reuses the agent-definitions
 * `SurfaceCardComponent` to create/edit an anonymous, node-local `InlineSurface`.
 */
@Injectable({ providedIn: 'root' })
export class LocalSurfaceDialogService {
    private readonly dialog = inject(Dialog);
    private readonly injector = inject(Injector);

    /**
     * @param data.mode 'create' to start from an empty surface, 'edit' to load `inlineSurface`.
     * @param data.inlineSurface the current `InlineSurface` (or `null`/omitted contents for create).
     * @param data.llmConfigId the owning node's agent definition's LLM, so the RAG tab can
     * compute suggested search params instead of showing its "assign an LLM" lock (EST-3986).
     * @returns the confirmed `InlineSurface` on Confirm, or `null` on Cancel/backdrop/Esc.
     */
    open(data: {
        mode: 'create' | 'edit';
        inlineSurface: InlineSurface | null;
        llmConfigId: number | null;
    }): Observable<InlineSurface | null> {
        const dialogRef = this.dialog.open<InlineSurface | null, LocalSurfaceDialogData>(LocalSurfaceDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            maxWidth: '100vw',
            panelClass: 'local-surface-dialog-panel',
            injector: this.injector,
            data,
        });

        return dialogRef.closed.pipe(map((result) => result ?? null));
    }
}
