import { Dialog } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable } from '@angular/core/rxjs-interop';
import {
    AppTableCellDirective,
    AppTableColumnDef,
    AppTableComponent,
    ButtonComponent,
    ConfirmationDialogService,
    DeleteButtonComponent,
    DuplicateButtonComponent,
    EditButtonComponent,
    LoadingSpinnerComponent,
    SearchComponent,
    SelectItem,
    TableRow,
    ViewButtonComponent,
} from '@shared/components';
import { ActionCode, GetRoleResponse, ResourceCode } from '@shared/models';
import { escapeHtml } from '@shared/utils';
import { combineLatest, debounceTime, EMPTY, finalize, switchMap } from 'rxjs';
import { catchError, distinctUntilChanged, tap } from 'rxjs/operators';

import { ActiveOrgService } from '../../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../services/notifications';
import {
    CopyRoleDialogComponent,
    CopyRoleDialogData,
} from '../../../components/copy-role-dialog/copy-role-dialog.component';
import {
    CreateRoleDialogComponent,
    CreateRoleDialogData,
    CreateRoleDialogResult,
} from '../../../components/create-role-dialog/create-role-dialog.component';
import { RoleInfoDialogComponent } from '../../../components/role-info-dialog/role-info-dialog.component';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { LoadRolesParams, RolesService } from '../../../services/admin/roles.service';
import { rbacErrorMessage } from '../../../utils';

@Component({
    selector: 'app-roles-tab',
    templateUrl: './roles-tab.component.html',
    styleUrls: ['./roles-tab.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        AppTableComponent,
        AppTableCellDirective,
        ButtonComponent,
        SearchComponent,
        LoadingSpinnerComponent,
        DeleteButtonComponent,
        DuplicateButtonComponent,
        EditButtonComponent,
        ViewButtonComponent,
    ],
})
export class RolesTabComponent {
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);
    private toast = inject(ToastService);
    private confirmation = inject(ConfirmationDialogService);
    private permissionsService = inject(PermissionsService);
    private orgStorage = inject(OrganizationsStorageService);
    private activeOrgService = inject(ActiveOrgService);
    protected rolesService = inject(RolesService);

    readonly searchTerm = signal('');
    readonly isLoading = signal(true);
    readonly orgFilterIds = signal<number[]>([]);
    readonly reloadTrigger = signal(0);

    /** All orgs whose custom roles the current user can list. Populated once on init. */
    readonly readableOrgs = signal<{ id: number; name: string }[]>([]);

    readonly canCreateOrCopyAnywhere = computed(() => {
        if (this.permissionsService.isSuperadmin) return true;
        return this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create).length > 0;
    });

    readonly orgFilterItems = computed<SelectItem[]>(() =>
        this.readableOrgs().map((o) => ({ name: o.name, value: o.id }))
    );

    /** Preselected org filter — follows the currently active org, but only if the caller can
     *  actually read roles there. Otherwise stays empty so the initial load falls back to
     *  fetching all readable orgs (see `ngOnInit`). */
    private readonly activeOrgDefault = computed<number[] | undefined>(() => {
        const id = this.activeOrgService.activeOrgId();
        if (id === null) return;
        if (this.permissionsService.isSuperadmin) return [id];
        return this.readableOrgs().some((o) => o.id === id) ? [id] : undefined;
    });

    readonly columns = computed<AppTableColumnDef[]>(() => [
        { key: 'name', label: 'ROLE NAME', width: 'minmax(160px, 1.2fr)' },
        { key: 'description', label: 'DESCRIPTION', width: 'minmax(200px, 2.5fr)' },
        {
            key: 'organization',
            label: 'ORGANIZATION',
            width: 'minmax(175px, 1fr)',
            filterItems: this.orgFilterItems(),
            filterKind: 'multi',
            filterServerSide: true,
            defaultValues: this.activeOrgDefault(),
        },
        { key: 'members', label: 'MEMBERS', width: 'minmax(90px, 0.8fr)', align: 'center' },
        { key: 'actions', label: 'ACTIONS', width: '160px', align: 'end' },
    ]);

    /** Combined rows: built-in roles first (org label = "All"), then custom roles. */
    readonly rows = computed<TableRow[]>(() => [
        ...this.rolesService.builtInRoles().map((r) => this.roleToRow(r)),
        ...this.rolesService.customRoles().map((r) => this.roleToRow(r)),
    ]);

    private readonly filters$ = combineLatest([
        toObservable(this.orgFilterIds),
        toObservable(this.searchTerm).pipe(debounceTime(300), distinctUntilChanged()),
        toObservable(this.reloadTrigger),
    ]);

    constructor() {
        this.loadReadableOrgs();
        this.filters$
            .pipe(
                takeUntilDestroyed(this.destroyRef),
                tap(() => this.isLoading.set(true)),
                switchMap(([orgIds, searchTerm]) => {
                    const params: LoadRolesParams = {};
                    const search = searchTerm.trim();
                    if (orgIds.length) params.orgIds = orgIds;
                    if (search) params.search = search;
                    return this.rolesService.loadRoles(params).pipe(
                        catchError((err) => {
                            this.toast.error(rbacErrorMessage(err, 'Failed to load roles'));
                            return EMPTY;
                        }),
                        finalize(() => this.isLoading.set(false))
                    );
                })
            )
            .subscribe();
    }

    private loadReadableOrgs(): void {
        if (this.permissionsService.isSuperadmin) {
            this.orgStorage
                .getOrganizations()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((orgs) =>
                    this.readableOrgs.set(orgs.filter((o) => o.is_active).map((o) => ({ id: o.id, name: o.name })))
                );
            return;
        }
        this.readableOrgs.set(this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Read));
    }

    private roleToRow(role: GetRoleResponse): TableRow {
        return {
            id: role.id,
            name: role.name,
            description: role.description ?? '',
            members: role.assigned_count,
            isBuiltIn: role.is_built_in,
            organization: role.is_built_in ? 'All' : (role.org?.name ?? '—'),
            orgId: role.org_id,
        };
    }

    canEditRow(row: TableRow): boolean {
        if (row['isBuiltIn']) return false;
        const orgId = row['orgId'] as number | null;
        if (orgId === null) return false;
        return this.permissionsService.canInOrg(orgId, ResourceCode.Roles, ActionCode.Update);
    }

    canDeleteRow(row: TableRow): boolean {
        if (row['isBuiltIn']) return false;
        const orgId = row['orgId'] as number | null;
        if (orgId === null) return false;
        return this.permissionsService.canInOrg(orgId, ResourceCode.Roles, ActionCode.Delete);
    }

    onFilterChange(evt: { key: string; values: unknown[] }): void {
        if (evt.key !== 'organization') return;
        this.orgFilterIds.set(evt.values.map((v) => Number(v)).filter((n) => Number.isFinite(n)));
    }

    onCreateRole(): void {
        const ref = this.dialog.open<CreateRoleDialogResult, CreateRoleDialogData>(CreateRoleDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
            data: {},
        });
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result?.action === 'created') this.reloadTrigger.update((v) => v + 1);
        });
    }

    onViewRole(row: TableRow): void {
        const id = row['id'] as number;
        const role =
            this.rolesService.customRoles().find((r) => r.id === id) ??
            this.rolesService.builtInRoles().find((r) => r.id === id);
        if (!role) return;
        this.dialog.open(RoleInfoDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            data: role,
        });
    }

    onEditRole(row: TableRow): void {
        const id = row['id'] as number;
        const role = this.rolesService.customRoles().find((r) => r.id === id);
        if (!role) return;
        const ref = this.dialog.open<CreateRoleDialogResult, CreateRoleDialogData>(CreateRoleDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
            data: { role },
        });
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result?.action === 'updated') this.reloadTrigger.update((v) => v + 1);
        });
    }

    onCopyRole(row: TableRow): void {
        const id = row['id'] as number;
        const role = this.rolesService.customRoles().find((r) => r.id === id);
        if (!role) return;
        const ref = this.dialog.open<'copied' | undefined, CopyRoleDialogData>(CopyRoleDialogComponent, {
            width: '480px',
            disableClose: true,
            data: { source: role },
        });
        ref.closed.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((result) => {
            if (result === 'copied') this.reloadTrigger.update((v) => v + 1);
        });
    }

    onDeleteRole(row: TableRow): void {
        const id = row['id'] as number;
        this.rolesService
            .previewDeleteRole(id)
            .pipe(
                switchMap((preview) => {
                    const affected = preview.affected_users ?? [];
                    const emails = affected
                        .slice(0, 5)
                        .map((u) => escapeHtml(u.email))
                        .join(', ');
                    const moreCount = Math.max(0, affected.length - 5);
                    const caution =
                        preview.assigned_count > 0
                            ? `${preview.assigned_count} user${preview.assigned_count === 1 ? '' : 's'} will be reassigned to the Viewer role${
                                  emails ? `: ${emails}${moreCount ? ` and ${moreCount} more` : ''}` : ''
                              }.`
                            : 'This role is not currently assigned to any user.';
                    return this.confirmation.confirm({
                        title: 'Delete the role?',
                        message: `The ${escapeHtml(row['name'] as string)} role will be permanently deleted.`,
                        caution,
                        type: 'danger',
                        confirmText: 'Delete',
                        cancelText: 'Cancel',
                    });
                }),
                switchMap((confirmed) => (confirmed === true ? this.rolesService.deleteRole(id) : EMPTY)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (res) => {
                    this.toast.success(
                        res.reassigned_count > 0
                            ? `Role deleted. ${res.reassigned_count} user${res.reassigned_count === 1 ? '' : 's'} moved to Viewer.`
                            : 'Role deleted.'
                    );
                },
                error: (e) => this.toast.error(e.error?.message ?? 'Failed to delete role'),
            });
    }
}
