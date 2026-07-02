import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
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

@Component({
    selector: 'app-surface-usage-dialog',
    imports: [AppSvgIconComponent],
    templateUrl: './surface-usage-dialog.component.html',
    styleUrls: ['./surface-usage-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SurfaceUsageDialogComponent {
    usage = input.required<SurfaceUsage>();

    close = output<void>();
    openAgent = output<number>();

    readonly agentCount = computed(() => this.usage().agents.length);
    readonly flowCount = computed(() => this.usage().flows.length);
    readonly chatCount = computed(() => this.usage().chats.length);
    readonly total = computed(() => this.agentCount() + this.flowCount() + this.chatCount());
}
