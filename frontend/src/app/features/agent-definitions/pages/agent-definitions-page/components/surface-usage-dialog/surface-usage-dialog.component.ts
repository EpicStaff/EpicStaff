import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, ResourceRef } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import { AppSvgIconComponent } from '@shared/components';

import { SurfaceUsage, surfaceUsageAgentCount, surfaceUsageFlowCount } from '../../../../models/surface-usage.model';

export interface SurfaceUsageDialogData {
    usage: ResourceRef<SurfaceUsage | undefined>;
}

@Component({
    selector: 'app-surface-usage-dialog',
    imports: [AppSvgIconComponent, MatTooltip],
    templateUrl: './surface-usage-dialog.component.html',
    styleUrls: ['./surface-usage-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceUsageDialogComponent {
    private readonly dialogRef = inject<DialogRef<number | undefined>>(DialogRef);
    private readonly router = inject(Router);
    private readonly data = inject<SurfaceUsageDialogData>(DIALOG_DATA);

    protected readonly usage = computed<SurfaceUsage | null>(() =>
        this.data.usage.hasValue() ? this.data.usage.value() : null
    );
    protected readonly failed = computed<boolean>(() => this.data.usage.error() !== undefined);

    protected readonly agentCount = computed(() => {
        const usage = this.usage();
        return usage ? surfaceUsageAgentCount(usage) : 0;
    });
    protected readonly flowCount = computed(() => {
        const usage = this.usage();
        return usage ? surfaceUsageFlowCount(usage) : 0;
    });
    protected readonly total = computed(() => this.agentCount() + this.flowCount());

    close(): void {
        this.dialogRef.close();
    }

    retry(): void {
        this.data.usage.reload();
    }

    openAgent(agentId: number): void {
        this.dialogRef.close(agentId);
    }

    openFlow(flowId: number, nodeId?: number): void {
        const queryParams = nodeId === undefined ? undefined : { nodeId };
        const url = this.router.serializeUrl(this.router.createUrlTree(['/flows', flowId], { queryParams }));
        window.open(url, '_blank', 'noopener');
    }
}
