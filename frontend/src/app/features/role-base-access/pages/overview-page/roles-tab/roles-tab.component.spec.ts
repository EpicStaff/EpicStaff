import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { DeleteRolePreviewResponse } from '@shared/models';
import { of } from 'rxjs';

import { ActiveOrgService } from '../../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../services/notifications';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { RolesService } from '../../../services/admin/roles.service';
import { RolesTabComponent } from './roles-tab.component';

describe('RolesTabComponent.onDeleteRole', () => {
    let confirm: ReturnType<typeof vi.fn>;

    function openDeleteDialog(preview: DeleteRolePreviewResponse): string {
        TestBed.configureTestingModule({
            providers: [
                { provide: Dialog, useValue: {} },
                { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                { provide: PermissionsService, useValue: {} },
                { provide: OrganizationsStorageService, useValue: {} },
                { provide: ActiveOrgService, useValue: {} },
                { provide: RolesService, useValue: { previewDeleteRole: vi.fn(() => of(preview)) } },
            ],
        });
        TestBed.overrideTemplate(RolesTabComponent, '');
        const component = TestBed.createComponent(RolesTabComponent).componentInstance;
        component.onDeleteRole({ id: 3, name: 'Editors' });
        return confirm.mock.calls[0][0].caution as string;
    }

    beforeEach(() => {
        confirm = vi.fn(() => of(false));
    });

    it('falls back to the count-only caution when affected users are omitted', () => {
        const caution = openDeleteDialog({ role_id: 3, assigned_count: 4 });

        expect(caution).toBe('4 users will be reassigned to the Viewer role.');
    });

    it('lists affected emails when they are present', () => {
        const caution = openDeleteDialog({
            role_id: 3,
            assigned_count: 1,
            affected_users: [{ user_id: 9, email: 'a@example.com', display_name: 'A' }],
        });

        expect(caution).toBe('1 user will be reassigned to the Viewer role: a@example.com.');
    });

    it('escapes affected emails because the caution is rendered as HTML', () => {
        const caution = openDeleteDialog({
            role_id: 3,
            assigned_count: 1,
            affected_users: [{ user_id: 9, email: '<b>x</b>@example.com', display_name: 'X' }],
        });

        expect(caution).toContain('&lt;b&gt;x&lt;/b&gt;@example.com');
        expect(caution).not.toContain('<b>');
    });
});
