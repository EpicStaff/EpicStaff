import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ActionCode, GetRoleResponse, UpdateRoleRequest } from '@shared/models';
import { Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { CreateRoleDialogComponent } from './create-role-dialog.component';

const editedRole: GetRoleResponse = {
    id: 4,
    name: 'Auditor',
    description: null,
    is_built_in: false,
    scope: 'org',
    org_id: 2,
    org: { id: 2, name: 'Acme' },
    assigned_count: 0,
    permissions: [
        { resource_type: 'audit', actions: [ActionCode.Export], audit_history_days: 30 },
        { resource_type: 'flows', actions: [ActionCode.Read] },
    ],
};

describe('CreateRoleDialogComponent', () => {
    it('keeps the audit history limit on the audit entry when an edited role is saved', () => {
        const updateRole = vi.fn<(id: number, request: UpdateRoleRequest) => Observable<GetRoleResponse>>(() =>
            of(editedRole)
        );
        TestBed.configureTestingModule({
            providers: [
                { provide: DIALOG_DATA, useValue: { role: editedRole } },
                { provide: DialogRef, useValue: { close: vi.fn() } as unknown as DialogRef },
                { provide: Dialog, useValue: {} as Dialog },
                {
                    provide: PermissionsService,
                    useValue: { isSuperadmin: true, catalog: () => null } as unknown as PermissionsService,
                },
                { provide: RolesService, useValue: { updateRole } as unknown as RolesService },
                { provide: OrganizationsStorageService, useValue: {} as OrganizationsStorageService },
                { provide: ToastService, useValue: { success: vi.fn() } as unknown as ToastService },
            ],
        });
        const component = TestBed.runInInjectionContext(() => new CreateRoleDialogComponent());

        component.onSubmit();

        const [roleId, request] = updateRole.mock.calls[0];
        expect(roleId).toBe(4);
        expect(request.permissions).toContainEqual({
            resource_type: 'audit',
            actions: [ActionCode.Export],
            audit_history_days: 30,
        });
        expect(request).not.toHaveProperty('audit_history_days');
    });
});
