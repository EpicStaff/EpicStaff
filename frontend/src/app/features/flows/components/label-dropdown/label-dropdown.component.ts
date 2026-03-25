import { CommonModule } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    HostListener,
    inject,
    Input,
    OnChanges,
    OnInit,
    output,
    signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AppIconComponent } from '../../../../shared/components/app-icon/app-icon.component';
import { ButtonComponent } from '../../../../shared/components/buttons/button/button.component';
import { LabelsStorageService, LabelTreeNode } from '../../services/labels-storage.service';

interface FlatLabelNode {
    node: LabelTreeNode;
    depth: number;
}

@Component({
    selector: 'app-label-dropdown',
    imports: [CommonModule, FormsModule, AppIconComponent, ButtonComponent],
    templateUrl: './label-dropdown.component.html',
    styleUrls: ['./label-dropdown.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class LabelDropdownComponent implements OnInit, OnChanges {
    @Input() selectedLabelIds: number[] = [];
    selectionChange = output<number[]>();

    private readonly labelsStorage = inject(LabelsStorageService);
    private readonly elementRef = inject(ElementRef);

    readonly isOpen = signal<boolean>(false);
    readonly localSelectedIds = signal<Set<number>>(new Set());
    readonly expandedIds = signal<Set<number>>(new Set());
    readonly addingChildOf = signal<number | null>(null);
    readonly addingRoot = signal<boolean>(false);

    readonly newLabelName = signal<string>('');
    readonly addLabelError = signal<string>('');

    readonly labelTree = this.labelsStorage.labelTree;

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

    get triggerLabel(): string {
        const count = this.selectedLabelIds.length;
        if (count === 0) return 'Select label';
        return `${count} label${count !== 1 ? 's' : ''} selected`;
    }

    ngOnInit(): void {
        this.labelsStorage.loadLabels().subscribe();
    }

    ngOnChanges(): void {
        if (!this.isOpen()) {
            this.localSelectedIds.set(new Set(this.selectedLabelIds));
        }
    }

    @HostListener('document:click', ['$event'])
    onDocumentClick(event: MouseEvent): void {
        if (!this.elementRef.nativeElement.contains(event.target)) {
            if (this.isOpen()) {
                this.close();
            }
        }
    }

    open(): void {
        this.localSelectedIds.set(new Set(this.selectedLabelIds));
        this.isOpen.set(true);
    }

    close(): void {
        this.isOpen.set(false);
        this.cancelAdd();
    }

    toggle(): void {
        if (this.isOpen()) {
            this.close();
        } else {
            this.open();
        }
    }

    save(): void {
        this.selectionChange.emit(Array.from(this.localSelectedIds()));
        this.isOpen.set(false);
        this.cancelAdd();
    }

    clear(): void {
        this.localSelectedIds.set(new Set());
    }

    toggleSelection(id: number): void {
        this.localSelectedIds.update((set) => {
            const next = new Set(set);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    }

    toggleExpand(id: number): void {
        this.expandedIds.update((set) => {
            const next = new Set(set);
            if (next.has(id)) {
                next.delete(id);
            } else {
                next.add(id);
            }
            return next;
        });
    }

    isSelected(id: number): boolean {
        return this.localSelectedIds().has(id);
    }

    isExpanded(id: number): boolean {
        return this.expandedIds().has(id);
    }

    startAddRoot(): void {
        this.addingRoot.set(true);
        this.addingChildOf.set(null);
        this.newLabelName.set('');
        this.addLabelError.set('');
    }

    startAddChild(parentId: number): void {
        this.addingChildOf.set(parentId);
        this.addingRoot.set(false);
        this.newLabelName.set('');
        this.addLabelError.set('');
        this.expandedIds.update((s) => new Set([...s, parentId]));
        this.scrollChildAddRowIntoView();
    }

    cancelAdd(): void {
        this.addingRoot.set(false);
        this.addingChildOf.set(null);
        this.newLabelName.set('');
        this.addLabelError.set('');
    }

    confirmAdd(): void {
        const name = this.newLabelName().trim();
        if (!name) {
            this.cancelAdd();
            return;
        }
        this.addLabelError.set('');
        const parentId = this.addingChildOf();
        this.labelsStorage.createLabel(name, parentId ?? undefined).subscribe({
            next: () => {
                this.cancelAdd();
            },
            error: (err: HttpErrorResponse) => {
                this.addLabelError.set(this.parseError(err));
            },
        });
    }

    onNewLabelInput(): void {
        if (this.addLabelError()) {
            this.addLabelError.set('');
        }
    }

    getIndentPadding(depth: number): string {
        return `${depth * 1 + 0.25}rem`;
    }

    onTreeRowHover(event: MouseEvent): void {
        const treeRow = event.currentTarget as HTMLElement;
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                const btn = treeRow.querySelector('.add-child-btn') as HTMLElement;
                if (btn) {
                    btn.scrollIntoView({ block: 'nearest', inline: 'nearest' });
                }
            });
        });
    }

    private scrollChildAddRowIntoView(): void {
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                const row = this.elementRef.nativeElement.querySelector('.add-label-row.child-add') as HTMLElement;
                if (!row) return;
                const buttons = row.querySelectorAll('button');
                const lastBtn = buttons[buttons.length - 1] as HTMLElement;
                if (lastBtn) lastBtn.scrollIntoView({ block: 'nearest', inline: 'nearest' });
            });
        });
    }

    private parseError(err: HttpErrorResponse): string {
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
