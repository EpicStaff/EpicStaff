import { CdkMonitorFocus } from '@angular/cdk/a11y';
import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';
import { AppSvgIconComponent, LabelDropdownComponent } from '@shared/components';
import { LABELS_STORE } from '@shared/services';

import { AgentGroupsStorageService } from '../../../../services/agent-groups-storage.service';

/** The group of the item a breadcrumb trail leads to; ungrouped items have no group crumb. */
export interface DetailGroupCrumb {
    groupId: number;
    /** A picker that moves the item to another group or out of it; read-only text otherwise (an owned surface follows its agent). */
    editable: boolean;
}

export interface DetailCrumb {
    label: string;
    navAgentId?: number;
    navAgentSurfacesId?: number;
    navAgentInstructionsId?: number;
    group?: DetailGroupCrumb;
}

@Component({
    selector: 'app-detail-header',
    imports: [AppSvgIconComponent, CdkMonitorFocus, LabelDropdownComponent, MatTooltip],
    templateUrl: './detail-header.component.html',
    styleUrls: ['./detail-header.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [{ provide: LABELS_STORE, useExisting: AgentGroupsStorageService }],
})
export class DetailHeaderComponent {
    showSidebar = input<boolean>(true);
    crumbs = input<DetailCrumb[]>([]);

    readonly toggleSidebar = output<void>();
    readonly navAgent = output<number>();
    readonly navAgentSurfaces = output<number>();
    readonly navAgentInstructions = output<number>();
    /** Picked in the group crumb: a group id, or null for Ungrouped. */
    readonly groupChange = output<number | null>();

    protected onGroupPicked(ids: number[]): void {
        this.groupChange.emit(ids[0] ?? null);
    }
}
