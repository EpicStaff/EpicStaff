import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
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
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, CatalogResponse, GetRoleResponse, ResourceCode } from '@shared/models';
import { rolePermissionsToSet, setToRolePermissions } from '@shared/utils';
import { finalize } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { PermissionsTableComponent } from '../permissions-table/permissions-table.component';

/** Snapshot passed to the dialog when opening it in duplicate-mode. */
export interface DuplicateRoleSource {
    name: string;
    description: string | null;
    permissions: string[];
    orgId: number | null;
}

export interface CreateRoleDialogData {
    /** Present in edit-mode; absent in create/duplicate-mode. */
    role?: GetRoleResponse;
    /** Pre-selected target org when opening in create-mode from a row-level action. */
    preselectedOrgId?: number;
    /** Present in duplicate-mode; seeds name/description/permissions/org. */
    duplicateSource?: DuplicateRoleSource;
}

export type CreateRoleDialogResult = { action: 'created' | 'updated'; role: GetRoleResponse } | undefined;

type DialogMode = 'create' | 'edit' | 'duplicate';

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
    private dialog = inject(Dialog);
    private destroyRef = inject(DestroyRef);

    readonly mode: DialogMode = this.dialogData?.role
        ? 'edit'
        : this.dialogData?.duplicateSource
          ? 'duplicate'
          : 'create';

    readonly isEditMode = this.mode === 'edit';
    readonly isDuplicateMode = this.mode === 'duplicate';

    /** In edit-mode fixed to the role's org; otherwise user-selectable (seeded from source in duplicate-mode). */
    readonly targetOrgId = signal<number | null>(
        this.dialogData?.role?.org_id ??
            this.dialogData?.duplicateSource?.orgId ??
            this.dialogData?.preselectedOrgId ??
            null
    );

    readonly form = new FormGroup({
        name: new FormControl(this.initialName(), {
            nonNullable: true,
            validators: [
                notWhitespaceValidator(),
                Validators.required,
                Validators.minLength(3),
                Validators.maxLength(50),
            ],
        }),
        description: new FormControl<string | null>(
            this.dialogData?.role?.description ?? this.dialogData?.duplicateSource?.description ?? ''
        ),
    });

    readonly selectedPermissions = signal<Set<string>>(this.initialSelectedPermissions());

    private initialName(): string {
        if (this.dialogData?.role) return this.dialogData.role.name;
        if (this.dialogData?.duplicateSource) return `${this.dialogData.duplicateSource.name} (Copy)`;
        return '';
    }

    private initialSelectedPermissions(): Set<string> {
        if (this.dialogData?.role) return rolePermissionsToSet(this.dialogData.role.permissions);
        if (this.dialogData?.duplicateSource) return new Set(this.dialogData.duplicateSource.permissions);
        return new Set();
    }

    readonly catalog = computed<CatalogResponse | null>(() => this.permissionsService.catalog());

    /** Options for the target-org picker (create-mode only). */
    readonly orgOptions = signal<SelectItem<number>[]>([]);

    readonly isSubmitting = signal(false);

    /** Ceiling set: keys the actor CANNOT grant in the currently-selected target org.
     *  In duplicate-mode the ceiling is removed — actor can preview & submit any subset;
     *  the backend enforces escalation and we surface its error via the toast. */
    readonly disabledPermissions = computed<Set<string>>(() => {
        const catalog = this.catalog();
        const orgId = this.targetOrgId();
        if (!catalog || orgId === null || this.permissionsService.isSuperadmin || this.isDuplicateMode) {
            return new Set<string>();
        }
        const disabled = new Set<string>();
        for (const rt of catalog.resource_types) {
            for (const action of rt.applicable_actions) {
                if (!this.permissionsService.canInOrg(orgId, rt.code as ResourceCode, action)) {
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
        if (this.isDuplicateMode) return 'Duplicate role';
        return 'Create role';
    });

    readonly primaryButtonLabel = computed(() => {
        if (this.isEditMode) return 'Save';
        if (this.isDuplicateMode) return 'Duplicate';
        return 'Create';
    });

    /** Whether a Duplicate button should be shown in the header (edit-mode only, and only if the actor
     *  can create roles somewhere). */
    canDuplicate(): boolean {
        if (!this.isEditMode) return false;
        if (this.permissionsService.isSuperadmin) return true;
        return this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create).length > 0;
    }

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
                    const opts = orgs.filter((o) => o.is_active).map((o) => ({ name: o.name, value: o.id }));
                    this.orgOptions.set(opts);
                    this.reconcileTargetOrg(opts);
                });
            return;
        }

        const creatable = this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create);
        const opts: SelectItem<number>[] = creatable.map((o) => ({ name: o.name, value: o.id }));
        this.orgOptions.set(opts);
        this.reconcileTargetOrg(opts);
    }

    /** Drops a preselected org that isn't in the creatable set (duplicate-mode source org may be forbidden);
     *  auto-picks the single option when nothing is selected. */
    private reconcileTargetOrg(opts: SelectItem<number>[]): void {
        const current = this.targetOrgId();
        if (current !== null && !opts.some((o) => o.value === current)) {
            this.targetOrgId.set(null);
        }
        if (this.targetOrgId() === null && opts.length === 1) {
            this.targetOrgId.set(opts[0].value);
        }
    }

    onTargetOrgChanged(value: unknown): void {
        this.targetOrgId.set(typeof value === 'number' ? value : null);
        if (this.isDuplicateMode) return;
        // If the newly-selected org lowers the ceiling, prune ungrantable keys from selection.
        this.selectedPermissions.update((set) => {
            const disabled = this.disabledPermissions();
            if (disabled.size === 0) return set;
            const next = new Set<string>();
            for (const k of set) if (!disabled.has(k)) next.add(k);
            return next;
        });
    }

    onPermissionToggle(event: { resourceType: ResourceCode; action: ActionCode }): void {
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

    onResourceToggle(event: { resourceCode: ResourceCode; select: boolean }): void {
        const catalog = this.catalog();
        if (!catalog) return;
        const resource = catalog.resource_types.find((rt) => rt.code === event.resourceCode);
        if (!resource) return;
        const disabled = this.disabledPermissions();
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const action of resource.applicable_actions) {
                const key = `${resource.code}:${action}`;
                if (disabled.has(key)) continue;
                event.select ? next.add(key) : next.delete(key);
            }
            return next;
        });
    }

    onGroupToggle(event: { groupKey: string; select: boolean }): void {
        const catalog = this.catalog();
        if (!catalog) return;
        const disabled = this.disabledPermissions();
        const resources = catalog.resource_types.filter((rt) => rt.group === event.groupKey);
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const rt of resources) {
                for (const action of rt.applicable_actions) {
                    const key = `${rt.code}:${action}`;
                    if (disabled.has(key)) continue;
                    event.select ? next.add(key) : next.delete(key);
                }
            }
            return next;
        });
    }

    onGroupActionToggle(event: { groupKey: string; actionCode: ActionCode; select: boolean }): void {
        const catalog = this.catalog();
        if (!catalog) return;
        const disabled = this.disabledPermissions();
        const resources = catalog.resource_types.filter((rt) => rt.group === event.groupKey);
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const rt of resources) {
                if (!rt.applicable_actions.includes(event.actionCode)) continue;
                const key = `${rt.code}:${event.actionCode}`;
                if (disabled.has(key)) continue;
                event.select ? next.add(key) : next.delete(key);
            }
            return next;
        });
    }

    onEnableRecommendedForResource(event: { resourceCode: ResourceCode; keys: string[] }): void {
        const disabled = this.disabledPermissions();
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const key of event.keys) {
                if (disabled.has(key)) continue;
                next.add(key);
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
                    this.toast.success(this.successToast());
                    this.dialogRef.close({ action: this.isEditMode ? 'updated' : 'created', role });
                },
                error: (err: HttpErrorResponse) => this.handleError(err),
            });
    }

    private successToast(): string {
        if (this.isEditMode) return 'Role updated';
        if (this.isDuplicateMode) return 'Role duplicated';
        return 'Role created';
    }

    /** Opens a new instance of this dialog in duplicate-mode, seeded with the currently-displayed state. */
    onDuplicate(): void {
        if (!this.canDuplicate()) return;
        const source: DuplicateRoleSource = {
            name: this.form.controls.name.value,
            description: this.form.controls.description.value || null,
            permissions: Array.from(this.selectedPermissions()),
            orgId: this.targetOrgId(),
        };
        this.dialog.open<CreateRoleDialogResult, CreateRoleDialogData>(CreateRoleDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
            disableClose: true,
            data: { duplicateSource: source },
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
                if (!control) continue;
                control.setErrors({ server: [e.reason] });
            }
            return;
        }
        this.toast.error(err.error?.message ?? 'Failed to save role');
    }

    onCancel(): void {
        this.dialogRef.close();
    }
}
