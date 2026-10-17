import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { CreateRoleRequest, GetRoleResponse } from '@shared/models';
import { Observable, of } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { CopyRoleDialogComponent } from './copy-role-dialog.component';

const sourceRole: GetRoleResponse = {
    id: 4,
    name: 'Auditor',
    description: 'Reads the audit log',
    is_built_in: false,
    scope: 'org',
    org_id: 2,
    org: { id: 2, name: 'Acme' },
    assigned_count: 0,
    permissions: [{ resource_type: 'audit', actions: [] }],
    audit_history_days: 180,
};

describe('CopyRoleDialogComponent', () => {
    it('keeps the source role audit history window on the copy', () => {
        const createRole = vi.fn<(request: CreateRoleRequest) => Observable<GetRoleResponse>>(() => of(sourceRole));
        TestBed.configureTestingModule({
            providers: [
                { provide: DIALOG_DATA, useValue: { source: sourceRole } },
                { provide: DialogRef, useValue: { close: vi.fn() } as unknown as DialogRef },
                {
                    provide: PermissionsService,
                    useValue: {
                        isSuperadmin: false,
                        orgsWith: () => [{ id: 2, name: 'Acme' }],
                    } as unknown as PermissionsService,
                },
                {
                    provide: RolesService,
                    useValue: { getRoleById: () => of(sourceRole), createRole } as unknown as RolesService,
                },
                { provide: OrganizationsStorageService, useValue: {} as OrganizationsStorageService },
                { provide: ToastService, useValue: { success: vi.fn() } as unknown as ToastService },
            ],
        });
        const component = TestBed.runInInjectionContext(() => new CopyRoleDialogComponent());

        component.onCopy();

        expect(createRole).toHaveBeenCalledWith(expect.objectContaining({ org_id: 2, audit_history_days: 180 }));
    });
});
