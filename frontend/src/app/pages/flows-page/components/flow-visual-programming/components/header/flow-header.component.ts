import { Dialog as CdkDialog, DialogModule } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    EventEmitter,
    inject,
    Input,
    input,
    Output,
    signal,
} from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterModule } from '@angular/router';
// import { RunGraphService } from '../../../../../../features/flows/services/run-graph-session.service';
// import { ToastService } from '../../../../../../services/notifications';
import { AppSvgIconComponent, Spinner2Component, StatusBadgeComponent } from '@shared/components';
import { CollapseOnOverflowDirective, HasPermissionDirective } from '@shared/directives';
import { ActionCode, GraphSessionStatus, ResourceCode } from '@shared/models';
import { LABELS_STORE } from '@shared/services';
import { PresentEditor } from 'src/app/features/flows/services/graph-collaboration.ws.service';

import { FlowRenameDialogComponent } from '../../../../../../features/flows/components/flow-rename-dialog/flow-rename-dialog.component';
import { GraphDto } from '../../../../../../features/flows/models/graph.model';
import { LabelsStorageService } from '../../../../../../features/flows/services/labels-storage.service';
import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { FLOW_ACTION_PERMISSIONS } from '../../../../../../visual-programming/core/constants/flow-action-permissions';
import { KeymapService } from '../../../../../../visual-programming/services/keymap.service';
import { PREVIEW_BLOCKED_MESSAGES } from './flow-header.constants';
import { FlowSaveStatus } from './flow-save-status.model';
import { GraphPresenceIndicatorsComponent } from './presence-indicator/graph-presence-indicators.component';
import { SaveDropdownComponent } from './save-dropdown/save-dropdown.component';

@Component({
    selector: 'app-flow-header',
    imports: [
        RouterModule,
        Spinner2Component,
        AppSvgIconComponent,
        DialogModule,
        OverlayModule,
        CollapseOnOverflowDirective,
        SaveDropdownComponent,
        GraphPresenceIndicatorsComponent,
        MatTooltipModule,
        HasPermissionDirective,
        StatusBadgeComponent,
    ],
    templateUrl: './flow-header.component.html',
    styleUrls: ['./flow-header.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowHeaderComponent {
    @Input() graphName?: string;
    @Input() graphId?: number;
    @Input() isAssistantOpen = false;
    @Input() graph?: GraphDto;
    @Input() isSaving = false;
    @Input() isRunning = false;
    readonly isPreviewMode = input(false);
    /** The status of the run in progress (regular or test); null hides the badge. */
    readonly runStatus = input<GraphSessionStatus | null>(null);
    readonly saveStatus = input<FlowSaveStatus | null>(null);
    @Input() editors: PresentEditor[] = [];
    @Output() save = new EventEmitter<void>();
    @Output() back = new EventEmitter<void>();
    @Output() viewSessions = new EventEmitter<void>();
    @Output() run = new EventEmitter<void>();
    @Output() getCurl = new EventEmitter<void>();
    @Output() toggleAssistant = new EventEmitter<void>();
    @Output() flowEdited = new EventEmitter<GraphDto>();
    @Output() saveVersion = new EventEmitter<void>();
    @Output() viewVersionHistory = new EventEmitter<void>();

    public isSaveDropdownOpen = signal(false);
    /** Shows Run and Get cURL; their shortcuts check the same requirement. */
    protected readonly canUseFlow = computed(() => this.permissions.meets(FLOW_ACTION_PERMISSIONS.useFlow));
    protected readonly previewBlockedMessages = PREVIEW_BLOCKED_MESSAGES;

    private readonly dialog = inject(CdkDialog);
    private readonly permissions = inject(PermissionsService);
    protected readonly keymap = inject(KeymapService);

    constructor(private router: Router) {}

    toggleSaveDropdown(event: Event): void {
        event.stopPropagation();
        this.isSaveDropdownOpen.update((v) => !v);
    }

    closeSaveDropdown(): void {
        this.isSaveDropdownOpen.set(false);
    }

    onSave() {
        this.save.emit();
    }

    onBack() {
        this.back.emit();
    }

    onViewSessions() {
        this.viewSessions.emit();
    }

    onRun() {
        this.run.emit();
    }

    onGetCurl() {
        this.getCurl.emit();
    }

    onToggleAssistant() {
        this.toggleAssistant.emit();
    }

    openRenameDialog(): void {
        if (!this.graph) return;
        const dialogRef = this.dialog.open<GraphDto>(FlowRenameDialogComponent, {
            data: {
                flowName: this.graph.name,
                flow: {
                    id: this.graph.id,
                    name: this.graph.name,
                    description: this.graph.description || '',
                    label_ids: this.graph.label_ids || [],
                    save_version: this.graph.save_version,
                },
            },
            width: '500px',
            providers: [{ provide: LABELS_STORE, useExisting: LabelsStorageService }],
        });

        dialogRef.closed.subscribe((result) => {
            if (result && typeof result === 'object' && 'id' in result) {
                this.flowEdited.emit(result as GraphDto);
            }
        });
    }

    protected readonly ResourceCode = ResourceCode;
    protected readonly ActionCode = ActionCode;
}
