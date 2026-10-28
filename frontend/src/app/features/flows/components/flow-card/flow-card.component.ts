import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, input, output, signal } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, ButtonComponent, CheckboxComponent } from '@shared/components';
import { LabelDropDirective } from '@shared/directives';
import { getLabelColorOption, ResourceCode } from '@shared/models';

import { GetGraphLightRequest, SubflowLightDto } from '../../models/graph.model';
import { LabelsStorageService } from '../../services/labels-storage.service';
import { FlowMenuAction, FlowMenuComponent, FlowMenuSelection } from './flow-menu/flow-menu.component';

/** A ⋮ menu action, or `open` when the card itself was clicked. */
export type FlowAction = FlowMenuAction | 'open';

export interface FlowCardAction {
    action: FlowAction;
    flow: GetGraphLightRequest;
    /** The ⋮ button of the menu the action was chosen from; absent when the card itself was clicked. */
    trigger?: HTMLElement;
}

export interface FlowLabelDropEvent {
    flow: GetGraphLightRequest;
    labelIds: number[];
}

@Component({
    selector: 'app-flow-card',
    imports: [
        CommonModule,
        ButtonComponent,
        FlowMenuComponent,
        CheckboxComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        LabelDropDirective,
    ],
    templateUrl: './flow-card.component.html',
    styleUrls: ['./flow-card.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowCardComponent {
    readonly flow = input.required<GetGraphLightRequest>();
    readonly selectMode = input<boolean>(false);
    readonly isSelected = input<boolean>(false);
    /** True while a bulk delete is in flight; disables the selection checkbox and stops
     *  selection from being toggled, so a run that is about to complete can't wipe a
     *  selection made while it's running. */
    readonly isDeleting = input<boolean>(false);
    readonly selectionToggle = output<void>();
    readonly cardClick = output<GetGraphLightRequest>();
    readonly action = output<FlowCardAction>();
    readonly labelDrop = output<FlowLabelDropEvent>();

    private readonly labelsStorage = inject(LabelsStorageService);

    public isMenuOpen = false;
    public isExpanded = signal<boolean>(false);
    public subflowMenuStates = new Map<number, boolean>();

    protected readonly ResourceCode = ResourceCode;

    get hasSubflows(): boolean {
        return !!this.flow()?.subflows?.length;
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

    getLabelFullPath(id: number): string {
        const label = this.labelsStorage.labels().find((l) => l.id === id);
        if (!label || !label.parent) return '';
        return label.full_path;
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
                hour12: false,
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
            hour12: false,
        });
    }

    onCardClick(): void {
        this.cardClick.emit(this.flow());
    }

    onMenuToggle(isOpen: boolean): void {
        this.isMenuOpen = isOpen;
    }

    onActionSelected({ action, trigger }: FlowMenuSelection): void {
        this.emitAction(action, trigger);
    }

    onSelectionToggle(event: MouseEvent): void {
        event.stopPropagation();
        if (this.isDeleting()) return;
        this.selectionToggle.emit();
    }

    onLabelDropped(labelId: number): void {
        const currentIds = this.flow().label_ids ?? [];
        if (currentIds.includes(labelId)) return;
        this.labelDrop.emit({ flow: this.flow(), labelIds: [...currentIds, labelId] });
    }

    onSubflowLabelDropped(labelId: number, subflow: SubflowLightDto): void {
        const currentIds = subflow.label_ids ?? [];
        if (currentIds.includes(labelId)) return;
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
        this.labelDrop.emit({ flow: flowLike, labelIds: [...currentIds, labelId] });
    }

    private emitAction(action: FlowAction, trigger: HTMLElement): void {
        this.action.emit({
            action,
            flow: this.flow(),
            trigger,
        });
    }

    public isSubflowMenuOpen(id: number): boolean {
        return this.subflowMenuStates.get(id) ?? false;
    }

    public onSubflowMenuToggle(id: number, isOpen: boolean): void {
        this.subflowMenuStates.set(id, isOpen);
    }

    public onSubflowActionSelected({ action, trigger }: FlowMenuSelection, subflow: SubflowLightDto): void {
        this.action.emit({ action, flow: this.toFlowLike(subflow), trigger });
    }

    public onSubflowClick(subflow: SubflowLightDto): void {
        this.cardClick.emit(this.toFlowLike(subflow));
    }

    private toFlowLike(subflow: SubflowLightDto): GetGraphLightRequest {
        return {
            id: subflow.id,
            uuid: '',
            name: subflow.name,
            description: subflow.description,
            tags: subflow.tags,
            label_ids: subflow.label_ids,
            created_at: subflow.created_at,
            updated_at: subflow.updated_at,
            save_version: subflow.save_version,
        };
    }
}
