import { OverlayModule } from '@angular/cdk/overlay';
import { CommonModule } from '@angular/common';
import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    DestroyRef,
    ElementRef,
    HostListener,
    inject,
    input,
    OnInit,
    output,
    ViewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router } from '@angular/router';
import {
    AppSvgIconComponent,
    ConfirmationDialogService,
    IconButtonComponent,
    SpinnerComponent,
} from '@shared/components';
import { filter, switchMap } from 'rxjs';

import { ToastService } from '../../../../services/notifications';
import { GraphVersionDto } from '../../models/graph.model';
import { CreateGraphWarningsService } from '../../services/create-graph-warnings.service';
import { FlowsApiService } from '../../services/flows-api.service';

@Component({
    selector: 'app-version-history-panel',
    imports: [
        IconButtonComponent,
        CommonModule,
        FormsModule,
        SpinnerComponent,
        AppSvgIconComponent,
        MatTooltipModule,
        OverlayModule,
    ],
    templateUrl: './version-history-panel.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrl: './version-history-panel.component.scss',
})
export class VersionHistoryPanelComponent implements OnInit {
    public versionsList: GraphVersionDto[] = [];
    public isLoading = true;
    public openMenuId: number | null = null;
    public selectedVersionId: number | null = null;
    public editingVersionId: number | null = null;
    public editingField: 'name' | 'description' | null = null;
    public editingValue: string = '';
    private editingVersion: GraphVersionDto | null = null;
    private isSaving = false;

    @ViewChild('versionEditInput') editInput?: ElementRef<HTMLInputElement | HTMLTextAreaElement>;

    private destroyRef = inject(DestroyRef);

    public graphId = input.required<number>();
    public graphSaveVersion = input<number | undefined>();
    public hasUnsavedChanges = input<boolean>(false);

    public closed = output<void>();
    public restoreRequested = output<GraphVersionDto>();

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
        private confirmationDialogService: ConfirmationDialogService,
        private cdr: ChangeDetectorRef,
        private router: Router,
        private createGraphWarningsService: CreateGraphWarningsService
    ) {}

    public ngOnInit(): void {
        this.loadVersions();
    }

    public toggleMenu(id: number): void {
        this.openMenuId = this.openMenuId === id ? null : id;
    }

    public selectVersion(version: GraphVersionDto): void {
        this.selectedVersionId = version.id;
    }

    public restoreVersion(version: GraphVersionDto, event?: MouseEvent): void {
        event?.stopPropagation();
        this.openMenuId = null;
        this.restoreRequested.emit(version);
    }

    public restoreSelectedVersion(): void {
        const version = this.versionsList.find((v) => v.id === this.selectedVersionId);
        if (!version) return;

        const pendingName =
            this.editingVersionId === version.id && this.editingField === 'name' && this.editingValue.trim()
                ? this.editingValue.trim()
                : null;

        this.restoreRequested.emit(pendingName ? { ...version, name: pendingName } : version);
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

        if ((field === 'name' && !value) || value === originalValue) {
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
        this.confirmationDialogService
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
                    if (this.selectedVersionId === version.id) {
                        this.selectedVersionId = null;
                    }
                    this.toastService.success('Version deleted');
                },
                error: () => {
                    this.toastService.error('Failed to delete version');
                },
            });
    }

    public loadVersions(): void {
        this.flowApiService
            .getGraphVersions(this.graphId())
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

    public createFlowFromVersion(version: GraphVersionDto, $event: MouseEvent): void {
        $event.stopPropagation();
        this.openMenuId = null;
        this.flowApiService
            .createGraphFromVersion(version.id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (response) => {
                    this.toastService.success('New flow created');
                    if (response.warnings.length) {
                        this.createGraphWarningsService.setPending(response.warnings);
                    }
                    this.closed.emit();
                    this.router.navigate(['/flows', response.graph_id]);
                },
                error: () => this.toastService.error('Failed to create flow'),
            });
    }
}
