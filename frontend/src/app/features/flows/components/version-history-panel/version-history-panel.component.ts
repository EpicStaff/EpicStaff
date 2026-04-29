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
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { IconButtonComponent } from '@shared/components';

import { ToastService } from '../../../../services/notifications/toast.service';
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

    private destroyRef = inject(DestroyRef);

    @HostListener('document:click', ['$event'])
    onDocumentClick(event: MouseEvent): void {
        const menus = this.el.nativeElement.querySelectorAll('.version-menu');
        const clickedInsideMenu = Array.from(menus).some((m) => (m as HTMLElement).contains(event.target as Node));
        if (!clickedInsideMenu) {
            this.openMenuId = null;
        }
    }

    @HostListener('document:mousedown', ['$event'])
    onDocumentMouseDown(event: MouseEvent): void {
        const editing = this.editingVersion;
        if (!editing) return;
        const input = this.el.nativeElement.querySelector('.version-edit-input');
        if (input && !input.contains(event.target as Node)) {
            this.saveEdit(editing);
        }
    }

    constructor(
        private flowApiService: FlowsApiService,
        private toastService: ToastService,
        private el: ElementRef,
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
            const input = this.el.nativeElement.querySelector('.version-edit-input');
            if (input) input.focus();
        });
    }

    public saveEdit(version: GraphVersionDto): void {
        if (!this.editingVersionId || !this.editingField) return;
        const field = this.editingField;
        const value = this.editingValue.trim();
        const originalValue = field === 'name' ? version.name : version.description || '';
        this.cancelEdit();
        if (value === originalValue) return;
        if (field === 'name' && !value) return;

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
                },
                error: () => {
                    this.toastService.error('Failed to update version');
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

    private loadVersions(): void {
        this.isLoading = true;
        this.flowApiService.getGraphVersions(this.data.graphId).subscribe({
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
