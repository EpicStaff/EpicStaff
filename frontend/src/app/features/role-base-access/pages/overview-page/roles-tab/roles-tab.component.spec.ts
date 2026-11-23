import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { DeleteRolePreviewResponse, GetRoleResponse, RolesListResponse } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../../services/config';
import { RolesTabComponent } from './roles-tab.component';

const ROLES_URL = 'http://api/admin/roles/';
/** The search box is debounced before the list loads. */
const SEARCH_DEBOUNCE_MS = 300;

// jsdom has no ResizeObserver; table and button directives only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const CUSTOM_ROLE: GetRoleResponse = {
    id: 7,
    name: 'Auditor',
    description: null,
    is_built_in: false,
    scope: 'org',
    org_id: 1,
    org: { id: 1, name: 'Acme' },
    assigned_count: 1,
    permissions: [],
};

describe('RolesTabComponent delete', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    });
    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    it('shows the emails of the users who lose the role as text, not markup', () => {
        const confirmed: ConfirmationDialogData[] = [];
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: 'http://api/' } },
                {
                    provide: PermissionsService,
                    useValue: { isSuperadmin: false, active: signal(null), orgsWith: () => [], canInOrg: () => true },
                },
                {
                    provide: ConfirmationDialogService,
                    useValue: {
                        confirm: (data: ConfirmationDialogData) => {
                            confirmed.push(data);
                            return of(false);
                        },
                    },
                },
            ],
        });
        const fixture = TestBed.createComponent(RolesTabComponent);
        const http = TestBed.inject(HttpTestingController);
        fixture.detectChanges();
        vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
        const roles: RolesListResponse = {
            built_in_roles: [],
            results: [CUSTOM_ROLE],
            count: 1,
            next: null,
            previous: null,
        };
        http.expectOne((request) => request.method === 'GET' && request.url === ROLES_URL).flush(roles);
        fixture.detectChanges();

        (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('app-delete-button button')!.click();
        const preview: DeleteRolePreviewResponse = {
            role_id: CUSTOM_ROLE.id,
            assigned_count: 1,
            affected_users: [{ user_id: 3, email: '"<b>x</b>"@example.com', display_name: 'X' }],
        };
        http.expectOne({ method: 'DELETE', url: `${ROLES_URL}${CUSTOM_ROLE.id}/?dry_run=true` }).flush(preview);

        const caution = document.createElement('div');
        caution.innerHTML = confirmed.at(-1)!.caution!;
        expect(caution.querySelector('b')).toBeNull();
        expect(caution.textContent).toContain('"<b>x</b>"@example.com');
        http.verify();
    });
});
