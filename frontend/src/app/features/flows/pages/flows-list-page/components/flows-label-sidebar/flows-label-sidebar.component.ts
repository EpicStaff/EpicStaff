import { Dialog, DialogModule } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    inject,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppSvgIconComponent } from '../../../../../../shared/components/app-svg-icon/app-svg-icon.component';
import {
    ConfirmationDialogComponent,
    DialogResult,
} from '../../../../../../shared/components/cofirm-dialog/confirmation-dialog.component';
import { LabelColorPickerComponent } from '../../../../components/label-color-picker/label-color-picker.component';
import { getLabelColorOption, LabelColor, LabelDto } from '../../../../models/label.model';
import { FlowsStorageService } from '../../../../services/flows-storage.service';
import { LabelsStorageService, LabelTreeNode } from '../../../../services/labels-storage.service';

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

@Component({
    selector: 'app-flows-label-sidebar',
    imports: [CommonModule, FormsModule, DialogModule, AppSvgIconComponent, LabelColorPickerComponent],
    templateUrl: './flows-label-sidebar.component.html',
    styleUrls: ['./flows-label-sidebar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FlowsLabelSidebarComponent implements OnInit {
    closeSidebar = output<void>();

    private readonly labelsStorage = inject(LabelsStorageService);
    private readonly flowsStorageService = inject(FlowsStorageService);
    private readonly dialog = inject(Dialog);
    private readonly el = inject(ElementRef);

    // Expose from storage
    readonly labelTree = this.labelsStorage.labelTree;
    readonly activeLabelFilter = this.labelsStorage.activeLabelFilter;

    // Local UI state
    readonly expandedNodes = signal<Set<number>>(new Set());
    readonly addingRootLabel = signal<boolean>(false);
    readonly addingChildOf = signal<number | null>(null);
    readonly editingLabelId = signal<number | null>(null);

    // Plain properties for ngModel bindings
    readonly newLabelNameValue = signal<string>('');
    readonly editingLabelNameValue = signal<string>('');

    // Color picker state
    readonly newLabelColor = signal<LabelColor>(LabelColor.Default);
    readonly editingLabelColor = signal<LabelColor>(LabelColor.Default);

    // Validation error messages
    readonly newLabelError = signal<string>('');
    readonly renameLabelError = signal<string>('');

    readonly flatTree = computed<FlatLabelNode[]>(() => {
        const result: FlatLabelNode[] = [];
        const flatten = (nodes: LabelTreeNode[], depth: number) => {
            for (const node of nodes) {
                result.push({ node, depth });
                if (this.isExpanded(node.id) && node.children.length > 0) {
                    flatten(node.children, depth + 1);
                }
            }
        };
        flatten(this.labelTree(), 0);
        return result;
    });

    ngOnInit(): void {
        this.labelsStorage.loadLabels().subscribe();
    }

    toggleExpand(id: number): void {
        this.expandedNodes.update((set) => {
            const next = new Set(set);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    }

    isExpanded(id: number): boolean {
        return this.expandedNodes().has(id);
    }

    selectAll(): void {
        this.labelsStorage.setActiveLabelFilter('all');
    }

    selectUnlabeled(): void {
        this.labelsStorage.setActiveLabelFilter('unlabeled');
    }

    selectLabel(id: number): void {
        this.labelsStorage.setActiveLabelFilter(id);
    }

    startAddRootLabel(): void {
        this.cancelRename();
        this.addingRootLabel.set(true);
        this.addingChildOf.set(null);
        this.newLabelNameValue.set('');
        this.newLabelError.set('');
    }

    cancelAddLabel(): void {
        this.addingRootLabel.set(false);
        this.addingChildOf.set(null);
        this.newLabelNameValue.set('');
        this.newLabelColor.set(LabelColor.Default);
        this.newLabelError.set('');
    }

    startAddChildLabel(parentId: number): void {
        this.cancelRename();
        this.addingChildOf.set(parentId);
        this.addingRootLabel.set(false);
        this.newLabelNameValue.set('');
        this.newLabelError.set('');
        this.expandedNodes.update((s) => new Set([...s, parentId]));
        this.scrollChildAddRowIntoView();
    }

    confirmAddLabel(): void {
        const name = this.newLabelNameValue().trim();
        if (!name) {
            this.cancelAddLabel();
            return;
        }
        this.newLabelError.set('');
        const parentId = this.addingChildOf();
        this.labelsStorage.createLabel(name, parentId ?? undefined, this.newLabelColor()).subscribe({
            next: () => {
                this.cancelAddLabel();
            },
            error: (err) => {
                this.newLabelError.set(this.parseCreateError(err));
            },
        });
    }

    onNewLabelInput(): void {
        if (this.newLabelError()) {
            this.newLabelError.set('');
        }
    }

    startRename(label: LabelDto): void {
        this.cancelAddLabel();
        this.editingLabelId.set(label.id);
        this.editingLabelNameValue.set(label.name);
        this.renameLabelError.set('');
        this.scrollRenameRowIntoView();
        this.editingLabelColor.set(label.metadata?.color ?? LabelColor.Default);
    }

    cancelRename(): void {
        this.editingLabelId.set(null);
        this.editingLabelNameValue.set('');
        this.editingLabelColor.set(LabelColor.Default);
        this.renameLabelError.set('');
    }

    confirmRename(id: number): void {
        const name = this.editingLabelNameValue().trim();
        if (!name) {
            this.cancelRename();
            return;
        }
        this.renameLabelError.set('');
        this.labelsStorage.renameLabel(id, name, this.editingLabelColor()).subscribe({
            next: () => {
                this.cancelRename();
            },
            error: (err) => {
                this.renameLabelError.set(this.parseCreateError(err));
            },
        });
    }

    onRenameLabelInput(): void {
        if (this.renameLabelError()) {
            this.renameLabelError.set('');
        }
    }

    openDeleteDialog(label: LabelTreeNode): void {
        const flows = this.flowsStorageService.flows();
        const sublabelCount = this.countAllDescendants(label);
        const sublabelIds = this.getAllDescendantIds(label);

        const directFlowCount = flows.filter((f) => (f.label_ids || []).includes(label.id)).length;

        const sublabelFlowCount =
            sublabelIds.length > 0
                ? flows.filter((f) => (f.label_ids || []).some((id) => sublabelIds.includes(id))).length
                : 0;

        let caution: string | undefined;
        if (directFlowCount > 0 || sublabelCount > 0) {
            const parts: string[] = [];
            if (directFlowCount > 0) {
                parts.push(`<strong>${directFlowCount} flow${directFlowCount !== 1 ? 's' : ''}</strong>`);
            }
            if (sublabelCount > 0) {
                const sublabelPart = `<strong>${sublabelCount} sublabel${sublabelCount !== 1 ? 's' : ''}</strong>`;
                if (sublabelFlowCount > 0) {
                    parts.push(
                        `${sublabelPart} containing <strong>${sublabelFlowCount} flow${sublabelFlowCount !== 1 ? 's' : ''}</strong>`
                    );
                } else {
                    parts.push(sublabelPart);
                }
            }
            caution = `The label is used in ${parts.join(' and ')}.`;
        }

        const dialogRef = this.dialog.open<DialogResult>(ConfirmationDialogComponent, {
            width: '500px',
            data: {
                title: 'Delete labels',
                message: `Are you sure you want to delete <strong>${label.name}</strong> label? This will remove it from all flows and sublabels.`,
                confirmText: 'Delete',
                type: 'danger',
                isShownBorder: true,
                caution,
            },
        });

        dialogRef.closed.subscribe((result) => {
            if (result === 'confirm') {
                this.labelsStorage.deleteLabel(label.id).subscribe({
                    next: () => {
                        this.flowsStorageService.getFlows(true).subscribe();
                    },
                    error: (err) => {
                        console.error('Error deleting label', err);
                    },
                });
            }
        });
    }

    private countAllDescendants(node: LabelTreeNode): number {
        return node.children.reduce((acc, child) => acc + 1 + this.countAllDescendants(child), 0);
    }

    private getAllDescendantIds(node: LabelTreeNode): number[] {
        const ids: number[] = [];
        const collect = (n: LabelTreeNode) => {
            for (const child of n.children) {
                ids.push(child.id);
                collect(child);
            }
        };
        collect(node);
        return ids;
    }

    getLabelIconColor(node: LabelTreeNode): string {
        const color = node.metadata?.color;
        if (!color || color === LabelColor.Default) return '';
        return getLabelColorOption(color).circleBg;
    }

    getIndentPadding(depth: number): string {
        return `${depth * 1.2 + 1}rem`;
    }

    private scrollChildAddRowIntoView(): void {
        setTimeout(() => {
            const input = this.el.nativeElement.querySelector('.add-label-row.child-add input') as HTMLElement;
            if (input) input.scrollIntoView({ block: 'nearest', inline: 'start' });
        }, 0);
    }

    private scrollRenameRowIntoView(): void {
        setTimeout(() => {
            const input = this.el.nativeElement.querySelector('.rename-input') as HTMLElement;
            if (input) input.scrollIntoView({ block: 'nearest', inline: 'start' });
        }, 0);
    }

    private parseCreateError(err: HttpErrorResponse): string {
        const msg: string = err?.error?.message ?? err?.message ?? '';
        if (
            msg.includes('Top-level label with this name already exists') ||
            msg.includes('name, parent must make a unique set')
        ) {
            return 'This label name already exists. Please try another name.';
        }
        return 'Failed to save label. Please try again.';
    }
}
