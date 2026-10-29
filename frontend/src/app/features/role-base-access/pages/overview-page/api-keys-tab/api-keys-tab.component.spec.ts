import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogData, ConfirmationDialogService } from '@shared/components';
import { ApiKeyStatus, GetApiKeyWithOwnerResponse } from '@shared/models';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../../services/config';
import { ToastService } from '../../../../../services/notifications';
import { OrganizationsStorageService } from '../../../services/admin/organizations-storage.service';
import { ApiKeysTabComponent } from './api-keys-tab.component';

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
        org_ids: [1],
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
            { provide: PermissionsService, useValue: { isSuperadmin: true } },
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
