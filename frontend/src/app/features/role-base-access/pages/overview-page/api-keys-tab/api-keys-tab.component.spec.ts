import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { ApiKeyStatus, GetApiKeyWithOwnerResponse } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../services/notifications';
import { AdminApiKeysService } from '../../../services/admin/api-keys.service';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { ApiKeysTabComponent } from './api-keys-tab.component';

function apiKey(id: number, owner: GetApiKeyWithOwnerResponse['owner']): GetApiKeyWithOwnerResponse {
    return {
        id,
        name: `key-${id}`,
        prefix: 'abc',
        created_at: '2026-01-01T00:00:00Z',
        expires_at: null,
        last_used_at: '2026-01-02T00:00:00Z',
        revoked_at: null,
        status: ApiKeyStatus.ACTIVE,
        owner,
        org_ids: [1],
    };
}

function hasOwnerFilter(host: HTMLElement): boolean {
    return Array.from(host.querySelectorAll('.col-label--filter')).some((button) =>
        button.textContent?.includes('OWNER')
    );
}

describe('ApiKeysTabComponent with hidden owners', () => {
    let fixture: ComponentFixture<ApiKeysTabComponent>;

    function render(keys: GetApiKeyWithOwnerResponse[]): HTMLElement {
        TestBed.configureTestingModule({
            providers: [
                {
                    provide: AdminApiKeysService,
                    useValue: { getApiKeys: vi.fn(() => of({ count: keys.length, results: keys })) },
                },
                {
                    provide: PermissionsService,
                    useValue: { isSuperadmin: false, orgsWith: () => [], canInOrg: () => false },
                },
                { provide: OrganizationsStorageService, useValue: {} },
                { provide: ConfirmationDialogService, useValue: {} },
                { provide: ToastService, useValue: { error: vi.fn() } },
            ],
        });
        fixture = TestBed.createComponent(ApiKeysTabComponent);
        fixture.detectChanges();
        vi.advanceTimersByTime(300);
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    it('renders a placeholder owner cell and hides the owner filter when every owner is hidden', () => {
        const host = render([apiKey(1, null)]);

        const ownerCell = host.querySelector('.table-body .table-row .table-cell:not(.checkbox)');
        expect(ownerCell?.querySelector('.empty-value')?.textContent?.trim()).toBe('—');
        expect(host.querySelector('.owner-cell')).toBeNull();
        expect(host.textContent).toContain('key-1');
        expect(host.querySelector('app-user-avatar')).toBeNull();
        expect(hasOwnerFilter(host)).toBe(false);
    });

    it('keeps the owner filter when at least one owner is known', () => {
        const host = render([
            apiKey(1, null),
            apiKey(2, { id: 5, email: 'owner@example.com', display_name: 'Owner', avatar_url: null }),
        ]);

        expect(host.querySelectorAll('.owner-cell').length).toBe(1);
        expect(hasOwnerFilter(host)).toBe(true);
    });
});
