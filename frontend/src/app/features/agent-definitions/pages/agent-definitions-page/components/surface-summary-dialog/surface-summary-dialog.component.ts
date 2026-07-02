import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

import { CombinedSurface, Surface } from '../../../../models/surface.model';
import { SurfaceCardComponent } from '../agent-detail/agent-surfaces-panel/surface-card/surface-card.component';

@Component({
    selector: 'app-surface-summary-dialog',
    imports: [AppSvgIconComponent, SurfaceCardComponent],
    templateUrl: './surface-summary-dialog.component.html',
    styleUrls: ['./surface-summary-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceSummaryDialogComponent {
    combined = input.required<CombinedSurface>();
    placeLabel = input<string>('');

    close = output<void>();

    readonly summarySurface = computed<Surface>(() => {
        const c = this.combined();
        return {
            id: -1,
            organization: 0,
            name: `${this.placeLabel()} summary`,
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
}
