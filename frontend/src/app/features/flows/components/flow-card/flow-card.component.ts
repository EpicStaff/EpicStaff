import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, EventEmitter, inject, Input, Output, signal } from '@angular/core';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { CheckboxComponent } from '../../../../shared/components/checkbox/checkbox.component';
import { GetGraphLightRequest, SubflowLightDto } from '../../models/graph.model';
import { getLabelColorOption } from '../../models/label.model';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { FlowMenuComponent } from './flow-menu/flow-menu.component';

export type FlowAction = 'viewSessions' | 'delete' | 'open' | 'rename' | 'run' | 'copy' | 'export';

export interface FlowCardAction {
    action: FlowAction;
    flow: GetGraphLightRequest;
}

@Component({
    selector: 'app-flow-card',
    standalone: true,
    imports: [CommonModule, ButtonComponent, FlowMenuComponent, CheckboxComponent, AppSvgIconComponent],
    templateUrl: './flow-card.component.html',
    styleUrls: ['./flow-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowCardComponent {
    @Input({ required: true }) flow!: GetGraphLightRequest;
    @Input() selectMode: boolean = false;
    @Input() isSelected: boolean = false;
    @Output() selectionToggle = new EventEmitter<void>();
    @Output() cardClick = new EventEmitter<GetGraphLightRequest>();
    @Output() action = new EventEmitter<FlowCardAction>();

    private readonly labelsStorage = inject(LabelsStorageService);

    public isMenuOpen = false;
    public isExpanded = signal<boolean>(false);
    public subflowMenuStates = new Map<number, boolean>();

    get hasSubflows(): boolean {
        return !!this.flow?.subflows?.length;
    }

    toggleSubflows(event: MouseEvent): void {
        event.stopPropagation();
        this.isExpanded.update((v) => !v);
    }

    getLabelName(id: number): string {
        const label = this.labelsStorage.labels().find((l) => l.id === id);
        if (!label) return '';
        return !label.parent ? label.name : `/${label.name}`;
    }

    getLabelChipStyles(id: number): { background: string; color: string } {
        const label = this.labelsStorage.labels().find((l) => l.id === id);
        const option = getLabelColorOption(label?.metadata?.color);
        return { background: option.chipBg, color: option.chipColor };
    }

    formatDate(dateStr?: string): string {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return (
            d.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
            }) +
            ', ' +
            d.toLocaleTimeString('en-US', {
                hour: 'numeric',
                minute: '2-digit',
                second: '2-digit',
            })
        );
    }

    formatDateOnly(dateStr?: string): string {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
        });
    }

    formatTimeOnly(dateStr?: string): string {
        if (!dateStr) return '';
        const d = new Date(dateStr);
        return d.toLocaleTimeString('en-US', {
            hour: 'numeric',
            minute: '2-digit',
            second: '2-digit',
        });
    }

    onCardClick(): void {
        this.cardClick.emit(this.flow);
    }

    onMenuToggle(isOpen: boolean): void {
        this.isMenuOpen = isOpen;
    }

    onActionSelected(action: string): void {
        this.emitAction(action as FlowAction);
    }

    onSelectionToggle(event: MouseEvent): void {
        event.stopPropagation();
        this.selectionToggle.emit();
    }

    private emitAction(action: FlowAction): void {
        this.action.emit({
            action,
            flow: this.flow,
        });
    }

    public isSubflowMenuOpen(id: number): boolean {
        return this.subflowMenuStates.get(id) ?? false;
    }

    public onSubflowMenuToggle(id: number, isOpen: boolean): void {
        this.subflowMenuStates.set(id, isOpen);
    }

    public onSubflowActionSelected(action: string, subflow: SubflowLightDto): void {
        const flowLike: GetGraphLightRequest = {
            id: subflow.id,
            uuid: '',
            name: subflow.name,
            description: subflow.description,
            tags: subflow.tags,
            label_ids: subflow.label_ids,
            created_at: subflow.created_at,
            updated_at: subflow.updated_at,
        };
        this.action.emit({ action: action as FlowAction, flow: flowLike });
    }

    public onSubflowClick(subflow: SubflowLightDto): void {
        const flowLike: GetGraphLightRequest = {
            id: subflow.id,
            uuid: '',
            name: subflow.name,
            description: subflow.description,
            tags: subflow.tags,
            label_ids: subflow.label_ids,
            created_at: subflow.created_at,
            updated_at: subflow.updated_at,
        };
        this.cardClick.emit(flowLike);
    }
}
