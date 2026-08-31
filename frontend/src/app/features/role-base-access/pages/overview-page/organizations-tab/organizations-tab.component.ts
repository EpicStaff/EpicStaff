import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    AppTableRowAction,
    ButtonComponent,
    ConfirmationDialogService,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { ActionCode, GetOrganizationResponse, ResourceCode } from '@shared/models';
import { finalize } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../services/notifications';
import { AdminsCellComponent } from '../../../components/admins-cell/admins-cell.component';
import { CreateOrganizationDialogComponent } from '../../../components/create-organization-dialog/create-organization-dialog.component';
import { OrgAvatarComponent } from '../../../components/org-avatar/org-avatar.component';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { rbacErrorMessage } from '../../../utils/rbac-error-messages.util';

const STATUS_ITEMS: SelectItem[] = [
    { name: 'Active', value: 'active' },
    { name: 'Deactivated', value: 'deactivated' },
];

@Component({
    selector: 'app-organizations-tab',
    templateUrl: './organizations-tab.component.html',
    styleUrls: ['./organizations-tab.component.scss'],
    imports: [
        AppTableComponent,
        AppTableCellDirective,
        ButtonComponent,
        SearchComponent,
        LoadingSpinnerComponent,
        StatusBadgeComponent,
        OrgAvatarComponent,
        AdminsCellComponent,
        DatePipe,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrganizationsTabComponent implements OnInit {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private confirmation = inject(ConfirmationDialogService);
    private organizationStorage = inject(OrganizationsStorageService);
    private toast = inject(ToastService);
    private permissionsService = inject(PermissionsService);

    searchTerm = signal('');
    isLoading = signal(true);

    /** Superadmin-only: create/deactivate/reactivate are platform actions per catalog. */
    readonly isSuperadmin = this.permissionsService.isSuperadmin;

    private readonly rowActions: AppTableRowAction[] = [
        {
            icon: 'edit',
            tooltip: 'Edit organization',
            hidden: (row) => !this.canEditRow(row),
            onClick: (row) => this.onEditOrganization(row),
        },
        {
            icon: 'stop',
            tooltip: 'Deactivate organization',
            variant: 'danger',
            hidden: (row) => !this.isSuperadmin || row['status'] !== 'active',
            onClick: (row) => this.onDeactivateOrganization(row),
        },
        {
            icon: 'play',
            tooltip: 'Activate organization',
            variant: 'muted',
            hidden: (row) => !this.isSuperadmin || row['status'] === 'active',
            onClick: (row) => this.onReactivateOrganization(row),
        },
    ];

    readonly columns: AppTableColumnDef[] = [
        { key: 'organization', label: 'Organization', width: 'minmax(180px, 2fr)' },
        { key: 'admin', label: 'Admin', width: 'minmax(180px, 2fr)' },
        { key: 'members', label: 'Members', width: 'minmax(90px, 1fr)' },
        { key: 'created', label: 'Created', width: 'minmax(120px, 1.5fr)' },
        { key: 'status', label: 'Status', width: 'minmax(120px, 1.5fr)', filterItems: STATUS_ITEMS },
        { key: 'actions', label: 'Actions', width: '130px', align: 'center', actions: this.rowActions },
    ];

    organizations = this.organizationStorage.organizations;

    tableData = computed<TableRow[]>(() => this.organizations().map((org) => this.orgToRow(org)));

    filteredOrgs = computed<TableRow[]>(() => {
        const term = this.searchTerm().toLowerCase().trim();
        const rows = this.tableData();
        if (!term) return rows;
        return rows.filter((o) => String(o['name']).toLowerCase().includes(term));
    });

    ngOnInit(): void {
        this.organizationStorage
            .getOrganizations(true)
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                finalize(() => this.isLoading.set(false))
            )
            .subscribe({
                error: (err: HttpErrorResponse) =>
                    this.toast.error(rbacErrorMessage(err, 'Failed to load organizations.')),
            });
    }

    onCreateOrganization(): void {
        if (!this.isSuperadmin) return;
        const ref = this.dialog.open(CreateOrganizationDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
        });
        this.refreshOnClose(ref);
    }

    onEditOrganization(row: TableRow): void {
        const org = this.organizations().find((o) => o.id === row['id']);
        if (!org) return;
        const ref = this.dialog.open(CreateOrganizationDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
            data: org,
        });
        this.refreshOnClose(ref);
    }

    private refreshOnClose(ref: DialogRef<unknown, CreateOrganizationDialogComponent>): void {
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result) {
                this.organizationStorage.getOrganizations(true).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
            }
        });
    }

    onDeactivateOrganization(row: TableRow): void {
        if (!this.isSuperadmin) return;
        const id = row['id'] as number;
        this.confirmation
            .confirm({
                title: 'Deactivate the organization?',
                message: `The ${row['name']} organization will be deactivated, but all data will be preserved.`,
                caution: 'Access will be revoked for all members of this organization',
                type: 'danger',
                confirmText: 'Deactivate',
                cancelText: 'Cancel',
            })
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((confirmed) => {
                if (confirmed !== true) return;
                this.organizationStorage
                    .deactivateOrganization(id)
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        next: () => this.toast.success('Organization deactivated successfully'),
                        error: (err: HttpErrorResponse) =>
                            this.toast.error(rbacErrorMessage(err, 'Failed to deactivate organization.')),
                    });
            });
    }

    onReactivateOrganization(row: TableRow): void {
        if (!this.isSuperadmin) return;
        const id = row['id'] as number;
        this.organizationStorage
            .reactivateOrganization(id)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: (err: HttpErrorResponse) =>
                    this.toast.error(rbacErrorMessage(err, 'Failed to reactivate organization.')),
            });
    }

    private canEditRow(row: TableRow): boolean {
        return this.permissionsService.canInOrg(row['id'] as number, ResourceCode.Organizations, ActionCode.Update);
    }

    private orgToRow(org: GetOrganizationResponse): TableRow {
        return {
            id: org.id,
            name: org.name,
            admins: org.admins,
            members: org.member_count,
            created: org.created_at,
            status: org.is_active ? 'active' : 'deactivated',
        };
    }
}
