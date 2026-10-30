import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { hasModifierKey } from '@angular/cdk/keycodes';
import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, DestroyRef, inject, OnInit, signal } from '@angular/core';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ButtonComponent,
    CustomInputComponent,
    SelectComponent,
    SelectItem,
    ValidationErrorsComponent,
} from '@shared/components';
import { EnterSubmitDirective } from '@shared/directives';
import { notWhitespaceValidator } from '@shared/form-validators';
import { ActionCode, CatalogResponse, GetRoleResponse, ResourceCode } from '@shared/models';
import { rolePermissionsToSet, setToRolePermissions } from '@shared/utils';
import { distinctUntilChanged, filter, finalize, map, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import {
    PermissionExtensionFailure,
    PermissionExtensionRowsService,
} from '../permissions-table/permission-extension-rows.service';
import { PermissionMatrixGroup, PermissionMatrixRow } from '../permissions-table/permission-matrix.model';
import { catalogMatrixGroups, matrixRowKeys, permissionKey } from '../permissions-table/permission-matrix.util';
import { PermissionsTableComponent } from '../permissions-table/permissions-table.component';

/** Snapshot passed to the dialog when opening it in duplicate-mode. */
export interface DuplicateRoleSource {
    name: string;
    description: string | null;
    permissions: string[];
    /** Ticked cells of extension rows (e.g. plugins); kept where the target org has the same rows. */
    extensionPermissions: string[];
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
        CustomInputComponent,
        EnterSubmitDirective,
        PermissionsTableComponent,
        ReactiveFormsModule,
        SelectComponent,
        ValidationErrorsComponent,
    ],
    providers: [PermissionExtensionRowsService],
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
    /** Rows extensions (e.g. plugins) add to the matrix; saved through them after the role itself. */
    protected readonly extensionRows = inject(PermissionExtensionRowsService);

    /** How the dialog was opened; `mode` may move on from it. */
    private readonly openedAs: DialogMode = this.dialogData?.role
        ? 'edit'
        : this.dialogData?.duplicateSource
          ? 'duplicate'
          : 'create';

    /** Switches from create/duplicate to edit when the role was created but its extension rows were not saved. */
    readonly mode = signal<DialogMode>(this.openedAs);

    readonly isEditMode = computed(() => this.mode() === 'edit');
    readonly isDuplicateMode = computed(() => this.mode() === 'duplicate');

    /** The role being edited: the one passed in, or the one this dialog created. */
    private readonly editedRole = signal<GetRoleResponse | null>(this.dialogData?.role ?? null);

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

    /** Ticked catalog permissions; extension cells live in `extensionRows`. */
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

    /** Every group of the matrix: the catalog's, then the extensions'. */
    private readonly matrixGroups = computed<PermissionMatrixGroup[]>(() => {
        const catalog = this.catalog();
        return [...(catalog ? catalogMatrixGroups(catalog) : []), ...this.extensionRows.groups()];
    });

    private readonly matrixRows = computed<PermissionMatrixRow[]>(() =>
        this.matrixGroups().flatMap((group) => group.rows)
    );

    /** What the table shows as ticked: catalog permissions and extension cells together. */
    readonly matrixSelection = computed<ReadonlySet<string>>(
        () => new Set([...this.selectedPermissions(), ...this.extensionRows.selected()])
    );

    /** Options for the target-org picker (create-mode only). */
    readonly orgOptions = signal<SelectItem<number>[]>([]);

    readonly isSubmitting = signal(false);

    /** Why the last save of extension rows failed; shown above the matrix until the next submit. */
    readonly extensionError = signal<string | null>(null);

    /** The extension problem to show: a failed save, else rows that could not be loaded. */
    readonly extensionNotice = computed<string | null>(() => {
        const saveError = this.extensionError();
        if (saveError) return saveError;
        const loadFailures = this.extensionRows.loadFailures();
        return loadFailures.length > 0 ? loadFailures.map((failure) => failure.message).join(' ') : null;
    });

    /** One line when loading the target org's extension rows left ticked cells out (the actor can't grant them). */
    readonly leftOutNotice = computed<string | null>(() => {
        const leftOut = this.extensionRows.leftOut();
        if (leftOut.length === 0) return null;
        const counts = leftOut
            .map(({ groupLabel, count }) => `${count} ${groupLabel} permission${count === 1 ? '' : 's'}`)
            .join(', ');
        const source = this.openedAs === 'duplicate' ? 'of the copied role ' : '';
        return `${counts} ${source}left out: you can't grant them in this organization.`;
    });

    private readonly formIsValid = toSignal(this.form.statusChanges.pipe(map(() => this.form.valid)), {
        initialValue: this.form.valid,
    });

    readonly canSubmit = computed(() => {
        if (this.isSubmitting()) return false;
        if (!this.formIsValid()) return false;
        if (!this.isEditMode() && this.targetOrgId() === null) return false;
        // Saving before the extension rows land would drop what is ticked in them.
        if (this.extensionRows.isLoading()) return false;
        return true;
    });

    /** Ceiling set: catalog keys the actor CANNOT grant in the currently-selected target org.
     *  In duplicate-mode the ceiling is removed — actor can preview & submit any subset;
     *  the backend enforces escalation and we surface its error via the toast. */
    private readonly catalogDisabledPermissions = computed<Set<string>>(() => {
        const catalog = this.catalog();
        const orgId = this.targetOrgId();
        if (!catalog || orgId === null || this.permissionsService.isSuperadmin || this.isDuplicateMode()) {
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

    /** Every cell that cannot be ticked: the catalog ceiling, and extension cells outside what the actor may grant
     *  (each extension says so for the target org, also in duplicate-mode). */
    readonly disabledPermissions = computed<ReadonlySet<string>>(
        () => new Set([...this.catalogDisabledPermissions(), ...this.extensionRows.disabledKeys()])
    );

    readonly dialogTitle = computed(() => {
        if (this.isEditMode()) {
            const orgName = this.editedRole()?.org?.name;
            return orgName ? `Edit role in ${orgName}` : 'Edit role';
        }
        if (this.isDuplicateMode()) return 'Duplicate role';
        return 'Create role';
    });

    readonly primaryButtonLabel = computed(() => {
        if (this.isEditMode()) return 'Save';
        if (this.isDuplicateMode()) return 'Duplicate';
        return 'Create';
    });

    private readonly targetOrgChanges = toObservable(this.targetOrgId);

    /** What the dialog reports on close once the role was saved at least once (also when it closes by Cancel). */
    private result: CreateRoleDialogResult = undefined;

    /** Whether a Duplicate button should be shown in the header (edit-mode only, and only if the actor
     *  can create roles somewhere). */
    canDuplicate(): boolean {
        if (!this.isEditMode()) return false;
        if (this.permissionsService.isSuperadmin) return true;
        return this.permissionsService.orgsWith(ResourceCode.Roles, ActionCode.Create).length > 0;
    }

    ngOnInit(): void {
        // disableClose keeps a stray backdrop click from losing the form; Escape is asked for, so it cancels.
        // A dropdown that closed on this Escape has taken it.
        this.dialogRef.keydownEvents
            .pipe(
                filter((event) => event.key === 'Escape' && !hasModifierKey(event) && !event.defaultPrevented),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe((event) => {
                event.preventDefault();
                this.onCancel();
            });

        this.permissionsService.loadCatalog().pipe(takeUntilDestroyed(this.destroyRef)).subscribe();

        const editedRole = this.editedRole();
        if (editedRole) {
            this.extensionRows.loadForRole(editedRole.id);
            return;
        }
        this.extensionRows.seedSelection(this.dialogData?.duplicateSource?.extensionPermissions ?? []);
        this.targetOrgChanges
            .pipe(distinctUntilChanged(), takeUntilDestroyed(this.destroyRef))
            .subscribe((orgId) => this.extensionRows.loadForOrg(orgId));
        this.loadCreatableOrgs();
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
        if (this.isDuplicateMode()) return;
        // If the newly-selected org lowers the ceiling, prune ungrantable keys from selection.
        // (Extension rows are reloaded for the new org and prune their own cells when they land.)
        this.selectedPermissions.update((set) => {
            const disabled = this.catalogDisabledPermissions();
            if (disabled.size === 0) return set;
            const next = new Set<string>();
            for (const k of set) if (!disabled.has(k)) next.add(k);
            return next;
        });
    }

    onPermissionToggle(event: { resourceType: string; action: ActionCode }): void {
        const key = permissionKey(event.resourceType, event.action);
        this.setCells([key], !this.matrixSelection().has(key));
    }

    onSelectAll(): void {
        if (!this.catalog()) return;
        const disabled = this.disabledPermissions();
        const grantable = matrixRowKeys(this.matrixRows()).filter((key) => !disabled.has(key));
        this.selectedPermissions.set(new Set(grantable.filter((key) => !this.extensionRows.owns(key))));
        this.extensionRows.replaceSelection(grantable.filter((key) => this.extensionRows.owns(key)));
    }

    onClearAll(): void {
        this.selectedPermissions.set(new Set());
        this.extensionRows.replaceSelection([]);
    }

    onResourceToggle(event: { resourceCode: string; select: boolean }): void {
        const row = this.matrixRows().find((candidate) => candidate.code === event.resourceCode);
        if (!row) return;
        this.setCells(matrixRowKeys([row]), event.select);
    }

    onGroupToggle(event: { groupKey: string; select: boolean }): void {
        this.setCells(matrixRowKeys(this.groupRows(event.groupKey)), event.select);
    }

    onGroupActionToggle(event: { groupKey: string; actionCode: ActionCode; select: boolean }): void {
        const keys = this.groupRows(event.groupKey)
            .filter((row) => row.actions.includes(event.actionCode))
            .map((row) => permissionKey(row.code, event.actionCode));
        this.setCells(keys, event.select);
    }

    onEnableRecommendedForResource(event: { resourceCode: string; keys: string[] }): void {
        this.setCells(event.keys, true);
    }

    onSubmit(): void {
        if (!this.canSubmit()) {
            this.form.markAllAsTouched();
            return;
        }
        const name = this.form.controls.name.value.trim();
        const description = this.form.controls.description.value?.trim() || null;
        const permissions = setToRolePermissions(this.selectedPermissions());
        const editedRole = this.editedRole();

        this.isSubmitting.set(true);
        this.extensionError.set(null);

        const roleSave$ = editedRole
            ? this.rolesService.updateRole(editedRole.id, { name, description, permissions })
            : this.rolesService.createRole({
                  org_id: this.targetOrgId()!,
                  name,
                  description,
                  permissions,
              });

        roleSave$
            .pipe(
                switchMap((role) => {
                    this.result = { action: this.result?.action ?? (editedRole ? 'updated' : 'created'), role };
                    return this.extensionRows.save(role.id).pipe(map((failures) => ({ role, failures })));
                }),
                finalize(() => this.isSubmitting.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: ({ role, failures }) => {
                    if (failures.length > 0) {
                        this.onExtensionSaveFailed(role, failures);
                        return;
                    }
                    this.toast.success(this.successToast());
                    this.dialogRef.close(this.result);
                },
                error: (err: HttpErrorResponse) => this.handleError(err),
            });
    }

    /** By what this dialog did to the role: created it (also when a retry finished the job) or updated it. */
    private successToast(): string {
        if (this.result?.action !== 'created') return 'Role updated';
        return this.openedAs === 'duplicate' ? 'Role duplicated' : 'Role created';
    }

    /** The role is saved, its extension rows are not: stay open on the saved role so Save can try them again. */
    private onExtensionSaveFailed(role: GetRoleResponse, failures: PermissionExtensionFailure[]): void {
        const wasCreated = !this.isEditMode();
        this.editedRole.set(role);
        this.mode.set('edit');
        const groups = failures.map((failure) => failure.groupLabel).join(', ');
        const reasons = failures.map((failure) => failure.message).join(' ');
        this.extensionError.set(
            `${wasCreated ? 'The role was created' : 'The role was saved'}, but its ${groups} permissions were not. ` +
                `${reasons} Fix them and save again.`
        );
    }

    /** Opens a new instance of this dialog in duplicate-mode, seeded with the currently-displayed state. */
    onDuplicate(): void {
        // The copy carries the extension cells, so it waits for them.
        if (!this.canDuplicate() || this.extensionRows.isLoading()) return;
        const source: DuplicateRoleSource = {
            name: this.form.controls.name.value,
            description: this.form.controls.description.value || null,
            permissions: Array.from(this.selectedPermissions()),
            extensionPermissions: Array.from(this.extensionRows.selected()),
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
        this.dialogRef.close(this.result);
    }

    /** Ticks or clears cells, skipping disabled ones; extension cells go to their extension, the rest to the catalog. */
    private setCells(keys: readonly string[], select: boolean): void {
        const disabled = this.disabledPermissions();
        const grantable = keys.filter((key) => !disabled.has(key));
        const extensionKeys = grantable.filter((key) => this.extensionRows.owns(key));
        const catalogKeys = grantable.filter((key) => !this.extensionRows.owns(key));
        if (extensionKeys.length > 0) this.extensionRows.setSelected(extensionKeys, select);
        if (catalogKeys.length === 0) return;
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const key of catalogKeys) {
                if (select) next.add(key);
                else next.delete(key);
            }
            return next;
        });
    }

    private groupRows(groupKey: string): PermissionMatrixRow[] {
        return this.matrixGroups().find((group) => group.key === groupKey)?.rows ?? [];
    }
}
