import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ConfirmationDialogService,
    SearchComponent,
    TableRow,
} from '@shared/components';
import { EMPTY, switchMap } from 'rxjs';

import { ToastService } from '../../../../../services/notifications';
import { RoleInfoDialogComponent } from '../../../components/role-info-dialog/role-info-dialog.component';
import { RolesService } from '../../../services/admin/roles.service';

@Component({
    selector: 'app-roles-tab',
    templateUrl: './roles-tab.component.html',
    styleUrls: ['./roles-tab.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [AppTableComponent, AppTableCellDirective, AppSvgIconComponent, SearchComponent],
})
export class RolesTabComponent implements OnInit {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private confirmation = inject(ConfirmationDialogService);
    protected rolesService = inject(RolesService);

    readonly searchTerm = signal('');
    readonly isLoading = signal(false);

    ngOnInit(): void {
        this.isLoading.set(true);
        this.rolesService
            .loadRoles()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ complete: () => this.isLoading.set(false) });
    }

    readonly columns: AppTableColumnDef[] = [
        { key: 'name', label: 'ROLE NAME', width: '1fr' },
        { key: 'description', label: 'DESCRIPTION', width: '3fr' },
        { key: 'members', label: 'MEMBERS', width: '1fr' },
        { key: 'actions', label: 'ACTIONS', width: '130px', align: 'center' },
    ];

    readonly tableData = computed<TableRow[]>(() =>
        this.rolesService.roles().map((role) => ({
            id: role.id,
            name: role.name,
            description: role.description,
            members: role.assigned_count,
            isBuiltIn: role.is_built_in,
        }))
    );

    readonly filteredRoles = computed<TableRow[]>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        if (!term) return this.tableData();
        return this.tableData().filter(
            (row) =>
                (row['name'] as string)?.toLowerCase().includes(term) ||
                (row['description'] as string)?.toLowerCase().includes(term)
        );
    });

    onViewRole(row: TableRow): void {
        const role = this.rolesService.roles().find((r) => r.id === row['id']);
        if (!role) return;
        this.dialog.open(RoleInfoDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: role,
        });
    }

    onDeleteRole(row: TableRow): void {
        const id = row['id'] as number;
        this.confirmation
            .confirm({
                title: 'Delete the role?',
                message: `The ${row['name']} role will be deleted.`,
                caution: 'Permissions will be revoked for all members with this role',
                type: 'danger',
                confirmText: 'Delete',
                cancelText: 'Cancel',
            })
            .pipe(
                switchMap((confirmed) => (confirmed === true ? this.rolesService.deleteRole(id) : EMPTY)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => this.toast.success('Role deleted successfully'),
                error: (e) => this.toast.error(e.error?.message),
            });
    }
}
