import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { DatePipe } from '@angular/common';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    ActivateButtonComponent,
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    ConfirmationDialogService,
    DeleteButtonComponent,
    EditButtonComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    StopButtonComponent,
    TableRow,
} from '@shared/components';
import { ActionCode, GetOrganizationResponse, ResourceCode } from '@shared/models';
import { escapeHtml } from '@shared/utils';
import { combineLatest, debounceTime, EMPTY, finalize } from 'rxjs';
import { catchError, distinctUntilChanged, switchMap, tap } from 'rxjs/operators';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../services/notifications';
import { AdminsCellComponent } from '../../../components/admins-cell/admins-cell.component';
import { CreateOrganizationDialogComponent } from '../../../components/create-organization-dialog/create-organization-dialog.component';
import { OrgAvatarComponent } from '../../../components/org-avatar/org-avatar.component';
import { StatusBadgeComponent } from '../../../components/status-badge/status-badge.component';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { HardDeleteFlowService } from '../../../services/hard-delete-flow.service';
import { buildOrganizationDeleteContent, rbacErrorMessage } from '../../../utils';

const STATUS_ITEMS: SelectItem[] = [
    { name: 'Active', value: true },
    { name: 'Deactivated', value: false },
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
        StopButtonComponent,
        EditButtonComponent,
        ActivateButtonComponent,
        DeleteButtonComponent,
        DatePipe,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrganizationsTabComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private confirmation = inject(ConfirmationDialogService);
    private organizationStorage = inject(OrganizationsStorageService);
    private toast = inject(ToastService);
    private permissionsService = inject(PermissionsService);
    private hardDeleteFlow = inject(HardDeleteFlowService);

    searchTerm = signal('');
    statusFilter = signal<boolean[]>([]);
    isLoading = signal(true);

    /** Superadmin-only: create/deactivate/reactivate are platform actions per catalog. */
    readonly isSuperadmin = this.permissionsService.isSuperadmin;

    readonly columns: AppTableColumnDef[] = [
        { key: 'organization', label: 'Organization', width: 'minmax(180px, 2fr)' },
        { key: 'admin', label: 'Admin', width: 'minmax(180px, 2fr)' },
        { key: 'members', label: 'Members', width: 'minmax(90px, 1fr)' },
        { key: 'created', label: 'Created', width: 'minmax(120px, 1.5fr)' },
        {
            key: 'status',
            label: 'Status',
            width: 'minmax(120px, 1.5fr)',
            filterItems: STATUS_ITEMS,
            filterServerSide: true,
        },
        { key: 'actions', label: 'Actions', width: '130px', align: 'end' },
    ];

    organizations = this.organizationStorage.organizations;

    tableData = computed<TableRow[]>(() => this.organizations().map((org) => this.orgToRow(org)));

    private readonly filters$ = combineLatest([
        toObservable(this.statusFilter),
        toObservable(this.searchTerm).pipe(debounceTime(300), distinctUntilChanged()),
    ]);

    constructor() {
        this.filters$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(() => this.isLoading.set(true)),
                switchMap(() =>
                    this.organizationStorage
                        .getOrganizations(true, {
                            is_active: this.statusFilter().length ? this.statusFilter() : undefined,
                            search: this.searchTerm() || undefined,
                        })
                        .pipe(
                            catchError((err: HttpErrorResponse) => {
                                this.toast.error(rbacErrorMessage(err, 'Failed to load organizations.'));

                                return EMPTY;
                            }),
                            finalize(() => this.isLoading.set(false))
                        )
                )
            )
            .subscribe();
    }

    showDeactivateOrg(row: TableRow): boolean {
        return this.isSuperadmin && row['status'] === 'active';
    }

    showReactivateOrg(row: TableRow): boolean {
        return this.isSuperadmin && row['status'] !== 'active';
    }

    onFilterChange(event: { key: string; values: unknown[] }): void {
        if (event.key !== 'status') return;
        this.statusFilter.set(event.values as boolean[]);
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
                message: `The ${escapeHtml(row['name'] as string)} organization will be deactivated, but all data will be preserved.`,
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

    onDeleteOrganization(row: TableRow): void {
        if (!this.isSuperadmin) return;
        const id = row['id'] as number;
        const name = row['name'] as string;
        this.hardDeleteFlow
            .run(
                (dryRun, verificationPhrase) =>
                    this.organizationStorage.deleteOrganization(id, dryRun, verificationPhrase),
                (report) => buildOrganizationDeleteContent(name, report),
                {
                    title: 'Delete the organization?',
                    verificationTarget: name,
                    successMessage: 'Organization deleted successfully',
                    previewErrorFallback: 'Failed to preview organization deletion.',
                    deleteErrorFallback: 'Failed to delete organization.',
                }
            )
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe();
    }

    canEditRow(row: TableRow): boolean {
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
