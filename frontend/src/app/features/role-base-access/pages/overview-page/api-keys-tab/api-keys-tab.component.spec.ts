import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import {
    ActionCode,
    ApiKeyStatus,
    GetApiKeyWithOwnerResponse,
    MyOrgPermissionsResponse,
    ResourceCode,
} from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../../services/config';
import { ToastService } from '../../../../../services/notifications';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { ApiKeysTabComponent } from './api-keys-tab.component';

// jsdom has no ResizeObserver; table and button directives only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const ACME = { id: 1, name: 'Acme' };
const GLOBEX = { id: 2, name: 'Globex' };

function apiKeyInOrg(id: number, name: string, org: { id: number; name: string }): GetApiKeyWithOwnerResponse {
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
        renderKeys([apiKeyInOrg(1, 'Acme key', ACME), apiKeyInOrg(2, 'Globex key', GLOBEX)]);

        expect(deletableKeyNames()).toEqual(['Acme key']);
    });

    it('shows the organization of each key', () => {
        renderKeys([apiKeyInOrg(1, 'Acme key', ACME), apiKeyInOrg(2, 'Globex key', GLOBEX)]);

        const cellTexts = Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.cell-text')).map((cell) =>
            cell.textContent!.trim()
        );
        expect(cellTexts).toEqual(expect.arrayContaining(['Acme', 'Globex']));
    });
});

const API_URL = 'http://api/';
const KEYS_URL = `${API_URL}admin/api-keys/`;
/** The search box is debounced before the list loads. */
const SEARCH_DEBOUNCE_MS = 300;

function apiKey(id: number, name: string, status: ApiKeyStatus): GetApiKeyWithOwnerResponse {
    return {
        id,
        name,
        prefix: `ek_${id}`,
        created_at: '2026-10-01T10:00:00Z',
        expires_at: null,
        last_used_at: null,
        revoked_at: status === ApiKeyStatus.REVOKED ? '2026-10-28T10:00:00Z' : null,
        status,
        owner: { id: 5, email: 'owner@example.com', display_name: 'Owner', avatar_url: null },
        org_id: 1,
        org_name: 'Acme',
    };
}

const toastStub = { success: () => {}, error: () => {}, info: () => {}, warning: () => {} };

function render(): {
    fixture: ComponentFixture<ApiKeysTabComponent>;
    http: HttpTestingController;
    confirmed: ConfirmationDialogData[];
} {
    const confirmed: ConfirmationDialogData[] = [];
    TestBed.configureTestingModule({
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            { provide: ConfigService, useValue: { apiUrl: API_URL } },
            { provide: PermissionsService, useValue: { isSuperadmin: true, canInOrg: () => true } },
            {
                provide: OrganizationsStorageService,
                useValue: { isOrganizationsLoaded: () => true, organizations: signal([]) },
            },
            {
                provide: ConfirmationDialogService,
                useValue: {
                    confirm: (data: ConfirmationDialogData) => {
                        confirmed.push(data);
                        return of(true);
                    },
                },
            },
            { provide: ToastService, useValue: toastStub },
        ],
    });
    const fixture = TestBed.createComponent(ApiKeysTabComponent);
    return { fixture, http: TestBed.inject(HttpTestingController), confirmed };
}

/** Lets the debounced filters fire, then answers the list request they send. */
function answerListLoad(
    fixture: ComponentFixture<ApiKeysTabComponent>,
    http: HttpTestingController,
    keys: GetApiKeyWithOwnerResponse[]
): void {
    fixture.detectChanges();
    vi.advanceTimersByTime(SEARCH_DEBOUNCE_MS);
    http.expectOne((request) => request.method === 'GET' && request.url === KEYS_URL).flush({
        count: keys.length,
        results: keys,
    });
    fixture.detectChanges();
}

function chooseBulkAction(fixture: ComponentFixture<ApiKeysTabComponent>, action: 'Revoke' | 'Delete'): void {
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[aria-label="Bulk actions"]')!.click();
    fixture.detectChanges();
    const items = TestBed.inject(OverlayContainer)
        .getContainerElement()
        .querySelectorAll<HTMLElement>('.settings-dropdown-item');
    Array.from(items)
        .find((item) => item.textContent!.trim() === action)!
        .click();
    fixture.detectChanges();
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('ApiKeysTabComponent bulk actions', () => {
    it('offers deleting revoked keys right after a bulk revoke, without a page reload', () => {
        const { fixture, http, confirmed } = render();
        const active = [apiKey(1, 'CI key', ApiKeyStatus.ACTIVE), apiKey(2, 'Deploy key', ApiKeyStatus.ACTIVE)];
        answerListLoad(fixture, http, active);
        (fixture.nativeElement as HTMLElement)
            .querySelectorAll<HTMLElement>('.table-row')
            .forEach((row) => row.click());
        fixture.detectChanges();

        chooseBulkAction(fixture, 'Revoke');
        for (const key of active) {
            http.expectOne({ method: 'POST', url: `${KEYS_URL}${key.id}/revoke/` }).flush({
                ...key,
                status: ApiKeyStatus.REVOKED,
            });
        }
        answerListLoad(fixture, http, [
            apiKey(1, 'CI key', ApiKeyStatus.REVOKED),
            apiKey(2, 'Deploy key', ApiKeyStatus.REVOKED),
        ]);

        chooseBulkAction(fixture, 'Delete');

        expect(confirmed.at(-1)?.message).toBe("Deleted keys can't be restored.");
        expect(confirmed.at(-1)?.confirmText).toBe('Delete 2 keys');
        for (const key of active) {
            http.expectOne({ method: 'DELETE', url: `${KEYS_URL}${key.id}/` }).flush(null);
        }
        answerListLoad(fixture, http, []);
        http.verify();
    });
});
