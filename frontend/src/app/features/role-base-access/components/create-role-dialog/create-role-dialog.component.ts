import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { ButtonComponent, CustomInputComponent, ValidationErrorsComponent } from '@shared/components';
import { CatalogResponse, GetRoleResponse } from '@shared/models';
import { rolePermissionsToSet } from '@shared/utils';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { PermissionsTableComponent } from '../permissions-table/permissions-table.component';

export interface CreateRoleDialogData {
    role?: GetRoleResponse;
}

@Component({
    selector: 'app-create-role-dialog',
    templateUrl: './create-role-dialog.component.html',
    styleUrls: ['./create-role-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ButtonComponent,
        ReactiveFormsModule,
        CustomInputComponent,
        ValidationErrorsComponent,
        PermissionsTableComponent,
    ],
})
export class CreateRoleDialogComponent {
    private dialogRef = inject(DialogRef);
    private dialogData = inject<CreateRoleDialogData>(DIALOG_DATA, { optional: true });
    private rolesCatalogService = inject(PermissionsService);

    readonly isEditMode = !!this.dialogData?.role;

    form = new FormGroup({
        name: new FormControl(this.dialogData?.role?.name ?? '', {
            nonNullable: true,
            validators: [Validators.required, Validators.minLength(3), Validators.maxLength(30)],
        }),
        description: new FormControl(this.dialogData?.role?.description ?? ''),
    });

    selectedPermissions = signal<Set<string>>(
        this.dialogData?.role ? rolePermissionsToSet(this.dialogData.role.permissions) : new Set()
    );

    readonly catalog = computed<CatalogResponse | null>(() => this.rolesCatalogService.catalog());

    onPermissionToggle(event: { resourceType: string; action: string }): void {
        const key = `${event.resourceType}:${event.action}`;
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            next.has(key) ? next.delete(key) : next.add(key);
            return next;
        });
    }

    onSelectAll(): void {
        const catalog = this.rolesCatalogService.catalog();
        if (!catalog) return;
        const all = new Set<string>();
        for (const rt of catalog.resource_types) {
            for (const action of rt.applicable_actions) {
                all.add(`${rt.code}:${action}`);
            }
        }
        this.selectedPermissions.set(all);
    }

    onClearAll(): void {
        this.selectedPermissions.set(new Set());
    }

    onGroupSelectAll(groupKey: string): void {
        const catalog = this.rolesCatalogService.catalog();
        if (!catalog) return;
        const resources = catalog.resource_types.filter((rt) => rt.group === groupKey);
        this.selectedPermissions.update((set) => {
            const next = new Set(set);
            for (const rt of resources) {
                for (const action of rt.applicable_actions) {
                    next.add(`${rt.code}:${action}`);
                }
            }
            return next;
        });
    }

    onGroupClear(groupKey: string): void {
        const catalog = this.rolesCatalogService.catalog();
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

    onCancel(): void {
        this.dialogRef.close();
    }

    // TODO: connect to backend when custom role CRUD endpoints are available
    // onSubmit(): void { ... }
}
