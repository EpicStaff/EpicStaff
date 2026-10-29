import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
    ActionCode,
    ApiKeyStatus,
    GetApiKeyWithOwnerResponse,
    MyOrgPermissionsResponse,
    ResourceCode,
} from '@shared/models';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../../services/config';
import { ApiKeysTabComponent } from './api-keys-tab.component';

// jsdom has no ResizeObserver; table and button directives only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const ACME = { id: 1, name: 'Acme' };
const GLOBEX = { id: 2, name: 'Globex' };

function apiKey(id: number, name: string, org: { id: number; name: string }): GetApiKeyWithOwnerResponse {
    return {
        id,
        name,
        prefix: 'es_abc',
        created_at: '2026-01-01T00:00:00Z',
        expires_at: null,
        last_used_at: null,
        revoked_at: null,
        status: ApiKeyStatus.ACTIVE,
        org_id: org.id,
        org_name: org.name,
        owner: { id: 9, email: 'owner@example.com', display_name: 'Owner', avatar_url: null },
    };
}

/** Like the backend: every resource is listed, `[]` where the role grants nothing. */
function permissionsWith(apiKeyActions: ActionCode[]): Record<ResourceCode, ActionCode[]> {
    const permissions = Object.fromEntries(
        Object.values(ResourceCode).map((resource) => [resource, [] as ActionCode[]])
    ) as Record<ResourceCode, ActionCode[]>;
    permissions[ResourceCode.ApiKeys] = apiKeyActions;
    return permissions;
}

/** The caller reads keys in both orgs but may delete them only in Acme. */
const CAPABILITIES: MyOrgPermissionsResponse = {
    is_superadmin: false,
    orgs: [
        {
            org: ACME,
            role: { id: 3, name: 'Org Admin' },
            permissions: permissionsWith([ActionCode.Read, ActionCode.Delete]),
        },
        {
            org: GLOBEX,
            role: { id: 4, name: 'Viewer' },
            permissions: permissionsWith([ActionCode.Read]),
        },
    ],
};

describe('ApiKeysTabComponent', () => {
    let fixture: ComponentFixture<ApiKeysTabComponent>;
    let httpTesting: HttpTestingController;

    afterEach(() => {
        httpTesting.verify();
        vi.useRealTimers();
        vi.unstubAllGlobals();
    });

    beforeEach(() => {
        vi.useFakeTimers();
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({
            imports: [ApiKeysTabComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        httpTesting = TestBed.inject(HttpTestingController);
        TestBed.inject(PermissionsService).loadOrgPermissions().subscribe();
        httpTesting.expectOne('/api/permissions/me/orgs/').flush(CAPABILITIES);
    });

    function renderKeys(keys: GetApiKeyWithOwnerResponse[]): void {
        fixture = TestBed.createComponent(ApiKeysTabComponent);
        fixture.detectChanges();
        // The list waits for the debounced search term before its first request.
        vi.runOnlyPendingTimers();
        httpTesting
            .expectOne((request) => request.url === '/api/admin/api-keys/')
            .flush({ count: keys.length, next: null, previous: null, results: keys });
        fixture.detectChanges();
    }

    function deletableKeyNames(): string[] {
        return Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.key-name'))
            .filter((name) => name.closest('.table-row')!.querySelector('app-delete-button'))
            .map((name) => name.textContent!.trim());
    }

    it('offers delete only on keys of an organization where the caller may delete them', () => {
        renderKeys([apiKey(1, 'Acme key', ACME), apiKey(2, 'Globex key', GLOBEX)]);

        expect(deletableKeyNames()).toEqual(['Acme key']);
    });

    it('shows the organization of each key', () => {
        renderKeys([apiKey(1, 'Acme key', ACME), apiKey(2, 'Globex key', GLOBEX)]);

        const cellTexts = Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.cell-text')).map((cell) =>
            cell.textContent!.trim()
        );
        expect(cellTexts).toEqual(expect.arrayContaining(['Acme', 'Globex']));
    });
});
