// agents-section.component.ts
import {
    Component,
    OnInit,
    OnDestroy,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    ElementRef,
    Renderer2,
    NgZone,
    ApplicationRef,
    Output,
    EventEmitter,
    HostBinding,
    ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { Subscription } from 'rxjs';
import { ProjectStateService } from '../services/project-state.service';
import { FullAgent, FullAgentService } from '../../features/staff/services/full-agent.service';
import {
    GridControlsComponent,
    GridSizeOption,
} from './grid-controls/grid-controls.component';
import {
    trigger,
    style,
    transition,
    animate,
    AnimationEvent,
} from '@angular/animations';
import {
    CardState,
    StaffAgentCardComponent,
} from './grid-controls/dropdown-staff-agents/staff-agent-card/staff-agent-card.component';
import { Dialog } from '@angular/cdk/dialog';
import { CreateAgentFormComponent } from '../../shared/components/create-agent-form-dialog/create-agent-form-dialog.component';
import { AgentsService } from '../../features/staff/services/staff.service';
import { ToastService } from '../../services/notifications/toast.service';
import { ClickOutsideDirective } from '../../shared/directives/click-outside.directive';

@Component({
    selector: 'app-agents-section',
    templateUrl: './agents-section.component.html',
    styleUrls: ['./agents-section.component.scss'],
    standalone: true,
    imports: [
        CommonModule,
        FormsModule,
        ClickOutsideDirective,
        GridControlsComponent,
        StaffAgentCardComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AgentsSectionComponent implements OnInit, OnDestroy {
    @ViewChild('gridControls') gridControls!: GridControlsComponent;

    public agents: FullAgent[] = [];
    public currentGridSize: GridSizeOption = 'medium';

    @HostBinding('class.size-small') get isSmallSize() {
        return this.currentGridSize === 'small';
    }
    @HostBinding('class.size-medium') get isMediumSize() {
        return this.currentGridSize === 'medium';
    }
    @HostBinding('class.size-large') get isLargeSize() {
        return this.currentGridSize === 'large';
    }

    public cardState: CardState = 'removing';

    private agentsSubscription!: Subscription;
    public isLoaded: boolean = false;
    constructor(
        private projectStateService: ProjectStateService,
        private cdr: ChangeDetectorRef,
        private dialog: Dialog,
        private agentsService: AgentsService,
        private toastService: ToastService,
        private fullAgentService: FullAgentService
    ) {}

    ngOnInit(): void {
        this.agentsSubscription = this.projectStateService.agents$.subscribe({
            next: (agents: FullAgent[]) => {
                this.agents = agents;
                this.isLoaded = true;
                this.cdr.markForCheck();
            },
        });
    }

    ngOnDestroy(): void {
        if (this.agentsSubscription) {
            this.agentsSubscription.unsubscribe();
        }
    }

    onGridSizeChanged(size: GridSizeOption): void {
        this.currentGridSize = size;

        this.cdr.markForCheck();
    }

    public onOutsideClick(): void {
        // Close the dropdown when clicking outside the agents section
        // Also close the actual dropdown in grid controls
        if (this.gridControls) {
            this.gridControls.onCloseDropdown();
        }
        this.cdr.markForCheck();
    }
    public onRemoveStaffAgent(staffAgent: FullAgent) {
        this.projectStateService.removeAgent(staffAgent);
    }

    public onEditAgent(agent: FullAgent): void {
        const dialogRef = this.dialog.open<FullAgent>(
            CreateAgentFormComponent,
            {
                maxWidth: '95vw',
                maxHeight: '90vh',
                autoFocus: true,
                data: { agent, isEditMode: true },
            }
        );

        dialogRef.closed.subscribe((updatedAgent) => {
            if (updatedAgent) {
                // Update the agent via service
                this.agentsService.updateAgent(updatedAgent as any).subscribe({
                    next: (result) => {
                        // After updating the agent, refresh the full agent data
                        this.projectStateService.refreshAgent(result.id);
                    },
                    error: (error) => {
                        console.error('Error updating agent:', error);
                        this.toastService.error('Failed to update agent');
                    },
                });
            }
        });
    }

    public trackAgentById(
        index: number,
        staffAgent: FullAgent
    ): string | number {
        return staffAgent.id;
    }
}
