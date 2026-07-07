import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { AppSvgIconComponent } from '@shared/components';

export type SurfaceUsagePlace = 'every-place' | 'flow' | 'chat';

export interface SurfaceAgentUsage {
    agentId: number;
    agentName: string;
    place: SurfaceUsagePlace;
    placeLabel: string;
}

export interface SurfaceDirectUsage {
    id: number;
    name: string;
    active?: boolean;
}

export interface SurfaceUsage {
    agents: SurfaceAgentUsage[];
    flows: SurfaceDirectUsage[];
    chats: SurfaceDirectUsage[];
}

export interface SurfaceUsageDialogData {
    usage: SurfaceUsage;
}

@Component({
    selector: 'app-surface-usage-dialog',
    imports: [AppSvgIconComponent],
    templateUrl: './surface-usage-dialog.component.html',
    styleUrls: ['./surface-usage-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceUsageDialogComponent {
    private readonly dialogRef = inject<DialogRef<number | undefined>>(DialogRef);
    private readonly data = inject<SurfaceUsageDialogData>(DIALOG_DATA);

    readonly usage = this.data.usage;

    readonly agentCount = computed(() => this.usage.agents.length);
    readonly flowCount = computed(() => this.usage.flows.length);
    readonly chatCount = computed(() => this.usage.chats.length);
    readonly total = computed(() => this.agentCount() + this.flowCount() + this.chatCount());

    close(): void {
        this.dialogRef.close();
    }

    openAgent(agentId: number): void {
        this.dialogRef.close(agentId);
    }
}
