import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, inject, viewChild } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { Surface } from '../../../../../features/agent-definitions/models/surface.model';
import { SurfaceCardComponent } from '../../../../../features/agent-definitions/pages/agent-definitions-page/components/agent-detail/agent-surfaces-panel/surface-card/surface-card.component';
import { SurfaceCatalogsStore } from '../../../../../features/agent-definitions/services/surface-catalogs-store.service';
import { InlineSurface } from '../../../../../pages/flows-page/components/flow-visual-programming/models/task-node.model';
import { inlineSurfaceToSurface } from '../../../../utils/surface/inline-surface.mapper';

export interface LocalSurfaceDialogData {
    mode: 'create' | 'edit';
    inlineSurface: InlineSurface | null;
    llmConfigId: number | null;
}

const EMPTY_INLINE_SURFACE: InlineSurface = {
    instructions: '',
    python_tools: [],
    mcp_tools: [],
    storage_items: [],
    knowledge: [],
};

@Component({
    selector: 'app-local-surface-dialog',
    imports: [AppSvgIconComponent, SurfaceCardComponent],
    templateUrl: './local-surface-dialog.component.html',
    styleUrls: ['./local-surface-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [SurfaceCatalogsStore],
})
export class LocalSurfaceDialogComponent {
    private readonly dialogRef = inject<DialogRef<InlineSurface | null>>(DialogRef);
    private readonly data = inject<LocalSurfaceDialogData>(DIALOG_DATA);

    private readonly surfaceCard = viewChild(SurfaceCardComponent);

    readonly isCreateMode = this.data.mode === 'create';
    readonly title = this.isCreateMode ? 'Create Local Surface' : 'Edit Local Surface';

    readonly workingSurface: Surface = inlineSurfaceToSurface(this.data.inlineSurface ?? EMPTY_INLINE_SURFACE);
    readonly llmConfigId = this.data.llmConfigId;

    onConfirm(): void {
        const card = this.surfaceCard();
        if (!card) {
            this.dialogRef.close(null);
            return;
        }

        const payload = card.buildCreateRequest('');
        const result: InlineSurface = {
            instructions: payload.instructions ?? '',
            python_tools: payload.python_tools ?? [],
            mcp_tools: payload.mcp_tools ?? [],
            storage_items: payload.storage_items ?? [],
            knowledge: payload.knowledge ?? [],
        };

        const incoming = this.data.inlineSurface;
        if (this.data.mode === 'edit' && incoming) {
            result.id = incoming.id;
            result.created_at = incoming.created_at;
            result.updated_at = incoming.updated_at;
        }

        this.dialogRef.close(result);
    }

    onCancel(): void {
        this.dialogRef.close(null);
    }
}
