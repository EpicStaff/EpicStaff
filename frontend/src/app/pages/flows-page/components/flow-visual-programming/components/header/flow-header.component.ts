import { Dialog as CdkDialog } from '@angular/cdk/dialog';
import { DialogModule } from '@angular/cdk/dialog';
import { OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, inject, Input, Output, signal } from '@angular/core';
import { Router, RouterModule } from '@angular/router';

import { FlowRenameDialogComponent } from '../../../../../../features/flows/components/flow-rename-dialog/flow-rename-dialog.component';
import { GraphDto } from '../../../../../../features/flows/models/graph.model';
// import { RunGraphService } from '../../../../../../features/flows/services/run-graph-session.service';
// import { ToastService } from '../../../../../../services/notifications/toast.service';
import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { Spinner2Component } from '../../../../../../shared/components/spinner-type2/spinner.component';
import { CollapseOnOverflowDirective } from '../../../../../../shared/directives/collapse-on-overflow.directive';
import { SaveDropdownComponent } from './save-dropdown/save-dropdown.component';

@Component({
    selector: 'app-flow-header',
    standalone: true,
    imports: [
        CommonModule,
        RouterModule,
        Spinner2Component,
        AppSvgIconComponent,
        DialogModule,
        OverlayModule,
        CollapseOnOverflowDirective,
        SaveDropdownComponent,
    ],
    templateUrl: './flow-header.component.html',
    styleUrls: ['./flow-header.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowHeaderComponent {
    @Input() graphName?: string;
    @Input() graphId?: number;
    @Input() isEpicChatEnabled = false;
    @Input() graph?: GraphDto;
    @Input() isSaving = false;
    @Input() isRunning = false;
    @Input() hasUnsavedChanges = false;
    @Output() save = new EventEmitter<void>();
    @Output() back = new EventEmitter<void>();
    @Output() viewSessions = new EventEmitter<void>();
    @Output() run = new EventEmitter<void>();
    @Output() getCurl = new EventEmitter<void>();
    @Output() connectChat = new EventEmitter<void>();
    @Output() flowEdited = new EventEmitter<GraphDto>();
    @Output() saveVersion = new EventEmitter<void>();
    @Output() viewVersionHistory = new EventEmitter<void>();

    public isSaveDropdownOpen = signal(false);

    private readonly dialog = inject(CdkDialog);

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

    onConnectChat() {
        this.connectChat.emit();
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
                },
            },
            width: '500px',
        });

        dialogRef.closed.subscribe((result) => {
            if (result && typeof result === 'object' && 'id' in result) {
                this.flowEdited.emit(result as GraphDto);
            }
        });
    }
}
