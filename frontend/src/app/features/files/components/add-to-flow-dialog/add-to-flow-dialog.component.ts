import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    HostListener,
    inject,
    signal,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import { AppSvgIconComponent } from '../../../../shared/components/app-svg-icon/app-svg-icon.component';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog';
import { FlowsApiService } from '../../../flows/services/flows-api.service';
import { StorageItem } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';

export interface AddToFlowDialogData {
    item: StorageItem;
}

export interface AddToFlowDialogResult {
    addGraphIds: number[];
    removeGraphIds: number[];
}

interface FlowOption {
    id: number;
    name: string;
    checked: boolean;
}

@Component({
    selector: 'app-add-to-flow-dialog',
    imports: [FormsModule, AppSvgIconComponent],
    templateUrl: './add-to-flow-dialog.component.html',
    styleUrls: ['./add-to-flow-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AddToFlowDialogComponent {
    private dialogRef = inject(DialogRef<AddToFlowDialogResult>);
    readonly data: AddToFlowDialogData = inject(DIALOG_DATA);
    private flowsApiService = inject(FlowsApiService);
    private storageApiService = inject(StorageApiService);
    private confirmationDialogService = inject(ConfirmationDialogService);
    private destroyRef = inject(DestroyRef);

    @ViewChild('selectorEl') selectorElRef?: ElementRef<HTMLElement>;

    readonly searchQuery = signal('');
    readonly flows = signal<FlowOption[]>([]);
    readonly isLoading = signal(true);
    readonly dropdownOpen = signal(false);
    readonly dropdownMaxHeight = signal(400);
    private initialCheckedIds = new Set<number>();

    readonly visibleFlows = computed(() => {
        const query = this.searchQuery().toLowerCase().trim();
        const all = this.flows();
        return query ? all.filter((f) => f.name.toLowerCase().includes(query)) : all;
    });

    readonly selectedFlows = computed(() => this.flows().filter((f) => f.checked));

    get selectorLabel(): string {
        const selected = this.selectedFlows();
        if (selected.length === 0) return '';
        if (selected.length === 1) return selected[0].name;
        return `${selected.length} flows selected`;
    }

    get hasChanges(): boolean {
        const current = this.flows();
        return current.some((f) => f.checked !== this.initialCheckedIds.has(f.id));
    }

    ngOnInit(): void {
        forkJoin({
            graphs: this.flowsApiService.getGraphsLight(),
            info: this.storageApiService.info(this.data.item.path),
        })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: ({ graphs, info }) => {
                    const assignedIds = new Set((info.graphs ?? []).map((gr) => gr.id));
                    const options = graphs.map((g) => ({
                        id: g.id,
                        name: g.name,
                        checked: assignedIds.has(g.id),
                    }));
                    this.initialCheckedIds = new Set(options.filter((o) => o.checked).map((o) => o.id));
                    this.flows.set(options);
                    this.isLoading.set(false);
                },
                error: () => {
                    this.isLoading.set(false);
                },
            });
    }

    @HostListener('document:click')
    onDocumentClick(): void {
        this.dropdownOpen.set(false);
    }

    toggleDropdown(event: MouseEvent): void {
        event.stopPropagation();
        const opening = !this.dropdownOpen();
        if (opening && this.selectorElRef) {
            const rect = this.selectorElRef.nativeElement.getBoundingClientRect();
            this.dropdownMaxHeight.set(Math.max(120, window.innerHeight - rect.bottom - 12));
        }
        this.dropdownOpen.update((v) => !v);
    }

    stopPropagation(event: MouseEvent): void {
        event.stopPropagation();
    }

    toggleFlow(flow: FlowOption): void {
        flow.checked = !flow.checked;
        this.flows.update((list) => [...list]);
    }

    onConfirm(): void {
        if (!this.hasChanges) return;
        const all = this.flows();
        const addGraphIds = all.filter((f) => f.checked && !this.initialCheckedIds.has(f.id)).map((f) => f.id);
        const removeGraphIds = all.filter((f) => !f.checked && this.initialCheckedIds.has(f.id)).map((f) => f.id);
        if (!removeGraphIds.length) {
            this.dialogRef.close({ addGraphIds, removeGraphIds });
            return;
        }

        const removedFlows = all.filter((f) => removeGraphIds.includes(f.id));
        const itemType = this.data.item.type === 'folder' ? 'folder' : 'file';
        const title = this.data.item.type === 'folder' ? 'Remove Folder?' : 'Remove File?';
        const itemName = this.escapeHtml(this.data.item.name);
        const message =
            removedFlows.length === 1
                ? `Are you sure you want to remove <strong>${itemName}</strong> ${itemType} from the <strong>${this.escapeHtml(removedFlows[0].name)}</strong> flow?`
                : `Are you sure you want to remove <strong>${itemName}</strong> ${itemType} from ${removedFlows.length} flows?`;

        this.confirmationDialogService
            .confirm({
                title,
                message,
                confirmText: 'Remove',
                cancelText: 'Cancel',
                type: 'warning',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) {
                    return;
                }
                this.dialogRef.close({ addGraphIds, removeGraphIds });
            });
    }

    onCancel(): void {
        this.dialogRef.close();
    }

    private escapeHtml(value: string): string {
        return value
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}
