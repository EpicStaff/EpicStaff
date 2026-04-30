import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectorRef,
    Component,
    DestroyRef,
    ElementRef,
    HostListener,
    Inject,
    inject,
    OnInit,
    QueryList,
    ViewChild,
    ViewChildren,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { IconButtonComponent } from '@shared/components';
import { filter, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications/toast.service';
import { ConfirmationDialogService } from '../../../../shared/components/cofirm-dialog/confimation-dialog.service';
import { SpinnerComponent } from '../../../../shared/components/spinner/spinner.component';
import { GraphVersionDto } from '../../models/graph.model';
import { FlowsApiService } from '../../services/flows-api.service';

@Component({
    selector: 'app-version-history-panel',
    imports: [IconButtonComponent, CommonModule, FormsModule, SpinnerComponent],
    templateUrl: './version-history-panel.component.html',
    styleUrl: './version-history-panel.component.scss',
})
export class VersionHistoryPanelComponent implements OnInit {
    public versionsList: GraphVersionDto[] = [];
    public isLoading = true;
    public openMenuId: number | null = null;
    public editingVersionId: number | null = null;
    public editingField: 'name' | 'description' | null = null;
    public editingValue: string = '';
    private editingVersion: GraphVersionDto | null = null;
    private isSaving = false;

    @ViewChild('versionEditInput') editInput?: ElementRef<HTMLInputElement | HTMLTextAreaElement>;
    @ViewChildren('versionMenu') versionMenus!: QueryList<ElementRef>;

    private destroyRef = inject(DestroyRef);

    @HostListener('document:click', ['$event'])
    onDocumentClick(event: MouseEvent): void {
        const clickedInsideMenu = this.versionMenus?.some((menuRef) =>
            menuRef.nativeElement.contains(event.target as Node)
        );
        if (!clickedInsideMenu) {
            this.openMenuId = null;
        }
    }

    @HostListener('document:mousedown', ['$event'])
    onDocumentMouseDown(event: MouseEvent): void {
        const editing = this.editingVersion;
        if (!editing) return;
        if (this.editInput && !this.editInput.nativeElement.contains(event.target as Node)) {
            this.saveEdit(editing);
        }
    }

    constructor(
        private flowApiService: FlowsApiService,
        private toastService: ToastService,
        private confirmationDialog: ConfirmationDialogService,
        private cdr: ChangeDetectorRef,
        @Inject(DIALOG_DATA) public data: { graphId: number },
        public dialogRef: DialogRef<void>
    ) {}

    public ngOnInit(): void {
        this.loadVersions();
    }

    public toggleMenu(id: number): void {
        this.openMenuId = this.openMenuId === id ? null : id;
    }

    public startEdit(version: GraphVersionDto, field: 'name' | 'description'): void {
        this.openMenuId = null;
        this.editingVersion = version;
        this.editingVersionId = version.id;
        this.editingField = field;
        this.editingValue = field === 'name' ? version.name : version.description || '';
        this.cdr.detectChanges();
        setTimeout(() => {
            this.editInput?.nativeElement.focus();
        });
    }

    public saveEdit(version: GraphVersionDto): void {
        if (!this.editingVersionId || !this.editingField || this.isSaving) return;

        const field = this.editingField;
        const value = this.editingValue.trim();
        const originalValue = field === 'name' ? version.name : version.description || '';

        if (!value || value === originalValue) {
            this.cancelEdit();
            return;
        }

        this.isSaving = true;

        const payload =
            field === 'name'
                ? { name: value, description: version.description || '' }
                : { name: version.name, description: value };

        this.flowApiService
            .updateGraphVersion(version.id, payload)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (updated) => {
                    const idx = this.versionsList.findIndex((v) => v.id === version.id);
                    if (idx !== -1) {
                        this.versionsList[idx] = updated;
                    }
                    this.toastService.success(field === 'name' ? 'Version was renamed' : 'Description was updated');
                    this.cancelEdit();
                },
                error: () => {
                    this.toastService.error('Failed to update version');
                    this.isSaving = false;
                },
                complete: () => {
                    this.isSaving = false;
                },
            });
    }

    public cancelEdit(): void {
        this.editingVersionId = null;
        this.editingField = null;
        this.editingValue = '';
        this.editingVersion = null;
    }

    public onEditKeydown(event: KeyboardEvent, version: GraphVersionDto): void {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.saveEdit(version);
        } else if (event.key === 'Escape') {
            this.cancelEdit();
        }
    }

    public deleteVersion(version: GraphVersionDto, event?: MouseEvent): void {
        event?.stopPropagation();
        this.openMenuId = null;
        this.confirmationDialog
            .confirm({
                title: 'Delete Version',
                message: `This version will be permanently <strong>removed</strong> from the list and cannot be restored.`,
                confirmText: 'Delete',
                cancelText: 'Cancel',
                type: 'danger',
            })
            .pipe(
                filter((result) => result === true),
                switchMap(() => this.flowApiService.deleteGraphVersion(version.id)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.versionsList = this.versionsList.filter((v) => v.id !== version.id);
                    this.toastService.success('Version deleted');
                },
                error: () => {
                    this.toastService.error('Failed to delete version');
                },
            });
    }

    private loadVersions(): void {
        this.flowApiService
            .getGraphVersions(this.data.graphId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (result) => {
                    this.versionsList = result;
                    this.isLoading = false;
                },
                error: (err) => {
                    console.error('Failed to load graph versions', err);
                    this.isLoading = false;
                },
            });
    }
}
