import { Dialog, DialogModule } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    HostBinding,
    inject,
    input,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { HasPermissionDirective, ResizableSidebarDirective } from '@shared/directives';
import { ActionCode, getLabelColorOption, LabelColor, LabelDto, LabelTreeNode, ResourceCode } from '@shared/models';
import { LABELS_STORE, SidebarWidthService } from '@shared/services';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogComponent, DialogResult } from '../cofirm-dialog';
import { LabelColorPickerComponent } from '../label-color-picker/label-color-picker.component';

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

/**
 * Reusable label branches sidebar. Consumers must provide the LABELS_STORE
 * injection token (see @shared/services/labels-store.token). Feature-specific
 * wording, permissions, and delete-confirmation caution copy are passed in
 * as inputs. A labelDeleted output is emitted so parents can trigger any
 * post-delete side effects (e.g. refreshing their item list).
 */

@Component({
    selector: 'app-label-sidebar',
    imports: [
        CommonModule,
        FormsModule,
        DialogModule,
        AppSvgIconComponent,
        LabelColorPickerComponent,
        MatTooltipModule,
        HasPermissionDirective,
        ResizableSidebarDirective,
    ],
    templateUrl: './label-sidebar.component.html',
    styleUrls: ['./label-sidebar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LabelSidebarComponent implements OnInit {
    // Wording
    readonly allItemsLabel = input<string>('All Items');
    // Optional callback that returns caution HTML for the delete confirmation
    // dialog. Return undefined for no caution row.
    readonly deleteCaution = input<((node: LabelTreeNode) => string | undefined) | null>(null);
    // Delete confirmation message (HTML). Falls back to a generic message
    // if not provided.
    readonly deleteMessage = input<((node: LabelTreeNode) => string) | null>(null);
    // Permission ResourceCode used to gate add/edit/delete buttons.
    readonly resourceCode = input<ResourceCode>(ResourceCode.Flows);

    closeSidebar = output<void>();
    labelDeleted = output<number>();

    private readonly labelsStorage = inject(LABELS_STORE);
    private readonly dialog = inject(Dialog);
    private readonly el = inject(ElementRef);
    private readonly sidebarWidthService = inject(SidebarWidthService);

    readonly storageKey = input.required<string>();

    protected readonly sidebarWidth = computed(() => this.sidebarWidthService.getWidth(this.storageKey())());

    @HostBinding('style.width.px')
    get hostWidth(): number {
        return this.sidebarWidth();
    }

    protected get hostElement(): HTMLElement {
        return this.el.nativeElement;
    }

    readonly labelTree = this.labelsStorage.labelTree;
    readonly activeLabelFilter = this.labelsStorage.activeLabelFilter;

    readonly expandedNodes = signal<Set<number>>(new Set());
    readonly addingRootLabel = signal<boolean>(false);
    readonly addingChildOf = signal<number | null>(null);
    readonly editingLabelId = signal<number | null>(null);

    readonly newLabelNameValue = signal<string>('');
    readonly editingLabelNameValue = signal<string>('');

    readonly newLabelColor = signal<LabelColor>(LabelColor.Default);
    readonly editingLabelColor = signal<LabelColor>(LabelColor.Default);

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
        const cautionFn = this.deleteCaution();
        const messageFn = this.deleteMessage();
        const caution = cautionFn ? cautionFn(label) : undefined;
        const message = messageFn
            ? messageFn(label)
            : 'Are you sure you want to delete <strong>${label.name}</strong> label?';

        const dialogRef = this.dialog.open<DialogResult>(ConfirmationDialogComponent, {
            width: '500px',
            data: {
                title: 'Delete labels',
                message,
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
                        this.labelDeleted.emit(label.id);
                    },
                    error: (err) => {
                        console.error('Error deleting label', err);
                    },
                });
            }
        });
    }

    getLabelIconColor(node: LabelTreeNode): string {
        const color = node.metadata?.color;
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

    protected readonly ActionCode = ActionCode;
}
