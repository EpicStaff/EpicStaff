// agents-section.component.ts
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    EventEmitter,
    HostBinding,
    OnDestroy,
    OnInit,
    Output,
    ViewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ClickOutsideDirective } from '@shared/directives';
import { Subscription } from 'rxjs';

import { FullAgent } from '../../features/staff/services/full-agent.service';
import { ProjectStateService } from '../services/project-state.service';
import {
    CardState,
    StaffAgentCardComponent,
} from './grid-controls/dropdown-staff-agents/staff-agent-card/staff-agent-card.component';
import { GridControlsComponent, GridSizeOption } from './grid-controls/grid-controls.component';

export type AgentPendingAction =
    | { kind: 'add'; agentId: number }
    | { kind: 'remove'; agentId: number }
    | { kind: 'update'; agent: FullAgent };

@Component({
    selector: 'app-agents-section',
    templateUrl: './agents-section.component.html',
    styleUrls: ['./agents-section.component.scss'],
    imports: [CommonModule, FormsModule, ClickOutsideDirective, GridControlsComponent, StaffAgentCardComponent],
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

    @Output() agentsIdsChange = new EventEmitter<number[]>();
    @Output() agentUpdatePending = new EventEmitter<FullAgent>();
    @Output() dirtyChange = new EventEmitter<boolean>();
    @Output() agentsPendingChange = new EventEmitter<AgentPendingAction>();

    public cardState: CardState = 'removing';

    private agentsSubscription!: Subscription;
    public isLoaded: boolean = false;
    constructor(
        private projectStateService: ProjectStateService,
        private cdr: ChangeDetectorRef
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
        const id = Number(staffAgent.id);
        this.agents = this.agents.filter((a) => Number(a.id) !== id);
        const nextIds = this.agents.map((a) => Number(a.id));
        this.agentsIdsChange.emit(nextIds);
        this.agentsPendingChange.emit({ kind: 'remove', agentId: id });
        this.projectStateService.updateAgents(this.agents);
        this.dirtyChange.emit(true);
        this.cdr.markForCheck();
    }

    public trackAgentById(index: number, staffAgent: FullAgent): string | number {
        return staffAgent.id;
    }

    public onAddStaffAgent(staffAgent: FullAgent): void {
        const id = Number(staffAgent.id);
        if (this.agents.some((a) => Number(a.id) === id)) return;
        this.agents = [...this.agents, staffAgent];
        const nextIds = this.agents.map((a) => Number(a.id));
        this.agentsIdsChange.emit(nextIds);
        this.agentsPendingChange.emit({ kind: 'add', agentId: id });
        this.projectStateService.updateAgents(this.agents);
        this.dirtyChange.emit(true);
        this.cdr.markForCheck();
    }
}
