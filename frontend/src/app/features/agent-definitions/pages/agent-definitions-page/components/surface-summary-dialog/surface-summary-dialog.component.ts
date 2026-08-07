import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { CombinedSurface, Surface } from '../../../../models/surface.model';
import { SurfaceCatalogsStore } from '../../../../services/surface-catalogs-store.service';
import { SurfaceCardComponent } from '../agent-detail/agent-surfaces-panel/surface-card/surface-card.component';

export interface SurfaceSummaryDialogData {
    combined: CombinedSurface;
    placeLabel: string;
    hideInstructions?: boolean;
    hideDescriptions?: boolean;
}

@Component({
    selector: 'app-surface-summary-dialog',
    imports: [AppSvgIconComponent, SurfaceCardComponent],
    templateUrl: './surface-summary-dialog.component.html',
    styleUrls: ['./surface-summary-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [SurfaceCatalogsStore],
})
export class SurfaceSummaryDialogComponent {
    private readonly dialogRef = inject<DialogRef<void>>(DialogRef);
    private readonly data = inject<SurfaceSummaryDialogData>(DIALOG_DATA);

    readonly placeLabel = this.data.placeLabel;
    readonly hideInstructions = this.data.hideInstructions ?? false;
    readonly hideDescriptions = this.data.hideDescriptions ?? false;

    readonly summarySurface = computed<Surface>(() => {
        const c = this.data.combined;
        return {
            id: -1,
            organization: 0,
            name: `${this.data.placeLabel} summary`,
            description: '',
            instructions: c.instructions,
            owner_agent: null,
            allow_creation: c.allow_creation,
            python_tools: c.python_tools,
            mcp_tools: c.mcp_tools,
            storage_items: c.storage_items,
            knowledge: c.knowledge,
            created_at: '',
            updated_at: '',
        };
    });

    close(): void {
        this.dialogRef.close();
    }
}
