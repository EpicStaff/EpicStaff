import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { ActionCode, CatalogResponse, GetRoleResponse, ResourceCode } from '@shared/models';
import { rolePermissionsToSet, setToRolePermissions } from '@shared/utils';
import { finalize } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { PermissionsTableComponent } from '../permissions-table/permissions-table.component';

export interface CreateRoleDialogData {
    /** Present in edit-mode; absent in create-mode. */
    role?: GetRoleResponse;
    /** Pre-selected target org when opening in create-mode from a row-level action. */
    preselectedOrgId?: number;
}

export type CreateRoleDialogResult = { action: 'created' | 'updated'; role: GetRoleResponse } | undefined;

@Component({
    selector: 'app-create-role-dialog',
    templateUrl: './create-role-dialog.component.html',
    styleUrls: ['./create-role-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ButtonComponent,
        ReactiveFormsModule,
        CustomInputComponent,
        SelectComponent,
        ValidationErrorsComponent,
        PermissionsTableComponent,
    ],
})
export class CreateRoleDialogComponent implements OnInit {
    private dialogRef = inject<DialogRef<CreateRoleDialogResult>>(DialogRef);
    private dialogData = inject<CreateRoleDialogData>(DIALOG_DATA, { optional: true });
    private permissionsService = inject(PermissionsService);
    private rolesService = inject(RolesService);
    private orgStorage = inject(OrganizationsStorageService);
    private toast = inject(ToastService);
    private destroyRef = inject(DestroyRef);

    readonly isEditMode = !!this.dialogData?.role;

    /** In edit-mode this is fixed to the role's org; in create-mode it's user-selectable. */
    readonly targetOrgId = signal<number | null>(
        this.dialogData?.role?.org_id ?? this.dialogData?.preselectedOrgId ?? null
    );

    readonly form = new FormGroup({
        name: new FormControl(this.dialogData?.role?.name ?? '', {
            nonNullable: true,
            validators: [Validators.required, Validators.minLength(3), Validators.maxLength(50)],
        }),
        description: new FormControl<string | null>(this.dialogData?.role?.description ?? ''),
    });

    readonly selectedPermissions = signal<Set<string>>(
        this.dialogData?.role ? rolePermissionsToSet(this.dialogData.role.permissions) : new Set()
    );

    readonly catalog = computed<CatalogResponse | null>(() => this.permissionsService.catalog());

    /** Options for the target-org picker (create-mode only). */
    readonly orgOptions = signal<SelectItem<number>[]>([]);

    readonly isSubmitting = signal(false);

    /** Ceiling set: keys the actor CANNOT grant in the currently-selected target org. */
    readonly disabledPermissions = computed<Set<string>>(() => {
        const catalog = this.catalog();
        const orgId = this.targetOrgId();
        if (!catalog || orgId === null || this.permissionsService.isSuperadmin) {
            return new Set<string>();
        }
        const disabled = new Set<string>();
        for (const rt of catalog.resource_types) {
            for (const action of rt.applicable_actions) {
                if (!this.permissionsService.canIn(orgId, rt.code as ResourceCode, action)) {
                    disabled.add(`${rt.code}:${action}`);
                }
            }
        }
        return disabled;
    });

    readonly dialogTitle = computed(() => {
        if (this.isEditMode) {
            const orgName = this.dialogData?.role?.org?.name;
            return orgName ? `Edit role in ${orgName}` : 'Edit role';
        }
        return 'Create role';
    });

    ngOnInit(): void {
        this.permissionsService.loadCatalog().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();

        if (!this.isEditMode) {
            this.loadCreatableOrgs();
        }
    }

    private loadCreatableOrgs(): void {
        if (this.permissionsService.isSuperadmin) {
            this.orgStorage
                .getOrganizations()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe((orgs) => {
                    this.orgOptions.set(orgs.filter((o) => o.is_active).map((o) => ({ name: o.name, value: o.id })));
                    if (this.targetOrgId() === null && this.orgOptions().length === 1) {
                        this.targetOrgId.set(this.orgOptions()[0].value);
                    }
                });
            return;
        }

        const creatable = this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create);
        this.orgOptions.set(creatable.map((o) => ({ name: o.name, value: o.id })));
        // Auto-selects the single available org when there's only one candidate and nothing was preselected.
        if (this.targetOrgId() === null && creatable.length === 1) {
            this.targetOrgId.set(creatable[0].id);
        }
    }

    onTargetOrgChanged(value: unknown): void {
        this.targetOrgId.set(typeof value === 'number' ? value : null);
        // If the newly-selected org lowers the ceiling, prune ungrantable keys from selection.
        this.selectedPermissions.update((set) => {
            const disabled = this.disabledPermissions();
            if (disabled.size === 0) return set;
            const next = new Set<string>();
            for (const k of set) if (!disabled.has(k)) next.add(k);
            return next;
        });
    }

    onPermissionToggle(event: { resourceType: string; action: string }): void {
        const key = `${event.resourceType}:${event.action}`;
        if (this.disabledPermissions().has(key)) return;
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            next.has(key) ? next.delete(key) : next.add(key);
            return next;
        });
    }

    onSelectAll(): void {
        const catalog = this.catalog();
        if (!catalog) return;
        const disabled = this.disabledPermissions();
        const all = new Set<string>();
        for (const rt of catalog.resource_types) {
            for (const action of rt.applicable_actions) {
                const key = `${rt.code}:${action}`;
                if (!disabled.has(key)) all.add(key);
            }
        }
        this.selectedPermissions.set(all);
    }

    onClearAll(): void {
        this.selectedPermissions.set(new Set());
    }

    onGroupSelectAll(groupKey: string): void {
        const catalog = this.catalog();
        if (!catalog) return;
        const disabled = this.disabledPermissions();
        const resources = catalog.resource_types.filter((rt) => rt.group === groupKey);
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const rt of resources) {
                for (const action of rt.applicable_actions) {
                    const key = `${rt.code}:${action}`;
                    if (!disabled.has(key)) next.add(key);
                }
            }
            return next;
        });
    }

    onGroupClear(groupKey: string): void {
        const catalog = this.catalog();
        if (!catalog) return;
        const resources = catalog.resource_types.filter((rt) => rt.group === groupKey);
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const rt of resources) {
                for (const action of rt.applicable_actions) {
                    next.delete(`${rt.code}:${action}`);
                }
            }
            return next;
        });
    }

    canSubmit(): boolean {
        if (this.isSubmitting()) return false;
        if (this.form.invalid) return false;
        if (!this.isEditMode && this.targetOrgId() === null) return false;
        return true;
    }

    onSubmit(): void {
        if (!this.canSubmit()) {
            this.form.markAllAsTouched();
            return;
        }
        const name = this.form.controls.name.value.trim();
        const description = this.form.controls.description.value?.trim() || null;
        const permissions = setToRolePermissions(this.selectedPermissions());

        this.isSubmitting.set(true);

        const request$ = this.isEditMode
            ? this.rolesService.updateRole(this.dialogData!.role!.id, { name, description, permissions })
            : this.rolesService.createRole({
                  org_id: this.targetOrgId()!,
                  name,
                  description,
                  permissions,
              });

        request$
            .pipe(
                finalize(() => this.isSubmitting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: (role) => {
                    this.toast.success(this.isEditMode ? 'Role updated' : 'Role created');
                    this.dialogRef.close({ action: this.isEditMode ? 'updated' : 'created', role });
                },
                error: (err: HttpErrorResponse) => this.handleError(err),
            });
    }

    private handleError(err: HttpErrorResponse): void {
        const code: string | undefined = err.error?.code;
        if (code === 'role_name_conflict') {
            this.toast.error('A role with this name already exists in the organization.');
            return;
        }
        if (code === 'permission_escalation_denied') {
            this.toast.error("You can't grant permissions you don't have in that organization.");
            return;
        }
        if (code === 'invalid' && Array.isArray(err.error?.errors)) {
            for (const e of err.error.errors) {
                const control = this.form.get(e.field);
                control?.setErrors({ server: e.reason });
            }
            return;
        }
        this.toast.error(err.error?.message ?? 'Failed to save role');
    }

    onCancel(): void {
        this.dialogRef.close();
    }
}
