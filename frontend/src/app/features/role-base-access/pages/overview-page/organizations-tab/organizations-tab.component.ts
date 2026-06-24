import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppSvgIconComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    ConfirmationDialogService,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    TableRow,
} from '@shared/components';
import { GetOrganizationResponse } from '@shared/models';
import { finalize } from 'rxjs';

import { ToastService } from '../../../../../services/notifications';
import { AdminsCellComponent } from '../../../components/admins-cell/admins-cell.component';
import { CreateOrganizationDialogComponent } from '../../../components/create-organization-dialog/create-organization-dialog.component';
import { OrgAvatarComponent } from '../../../components/org-avatar/org-avatar.component';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';

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
        AppSvgIconComponent,
        LoadingSpinnerComponent,
        StatusBadgeComponent,
        OrgAvatarComponent,
        AdminsCellComponent,
        DatePipe,
        MatTooltip,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrganizationsTabComponent implements OnInit {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private confirmation = inject(ConfirmationDialogService);
    private organizationStorage = inject(OrganizationsStorageService);
    private toast = inject(ToastService);

    searchTerm = signal('');
    isLoading = signal(true);

    readonly columns: AppTableColumnDef[] = [
        { key: 'organization', label: 'Organization', width: '2fr' },
        { key: 'admin', label: 'Admin', width: '2fr' },
        { key: 'members', label: 'Members', width: '1fr' },
        { key: 'created', label: 'Created', width: '1.5fr' },
        { key: 'status', label: 'Status', width: '1.5fr', filterItems: STATUS_ITEMS },
        { key: 'actions', label: 'Actions', width: '130px', align: 'center' },
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
            .subscribe();
    }

    onCreateOrganization(): void {
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
                        error: (e) => this.toast.error(e.error?.message),
                    });
            });
    }

    onReactivateOrganization(row: TableRow): void {
        const id = row['id'] as number;
        this.organizationStorage.reactivateOrganization(id).pipe(takeUntilDestroyed(this.destroyRef)).subscribe();
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
