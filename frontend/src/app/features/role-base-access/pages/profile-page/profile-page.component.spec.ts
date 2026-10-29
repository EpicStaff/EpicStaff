import { Dialog } from '@angular/cdk/dialog';
import { signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { ApiKeyStatus, FullMembership, GetMeResponse, GetMyApiKeyResponse } from '@shared/models';
import { of } from 'rxjs';

import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { AuthService } from '../../../../services/auth/auth.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { ProfileApiKeysStorageService } from '../../services/profile-api-keys-storage.service';
import { ProfileApiKeysTabComponent } from './api-keys-tab/profile-api-keys-tab.component';
import { ProfilePageComponent } from './profile-page.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

function apiKey(id: number, status: ApiKeyStatus, org = { id: 1, name: 'Acme' }): GetMyApiKeyResponse {
    return {
        id,
        name: 'CI key',
        prefix: 'es_abc',
        created_at: '2026-01-01T00:00:00Z',
        expires_at: null,
        last_used_at: null,
        revoked_at: status === ApiKeyStatus.REVOKED ? '2026-02-01T00:00:00Z' : null,
        status,
        org_id: org.id,
        org_name: org.name,
    };
}

describe('ProfilePageComponent password change', () => {
    let fixture: ComponentFixture<ProfilePageComponent>;
    let getMyApiKeys: ReturnType<typeof vi.fn>;
    let openDialog: ReturnType<typeof vi.fn>;

    afterEach(() => vi.unstubAllGlobals());

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        getMyApiKeys = vi.fn();
        openDialog = vi.fn();
        TestBed.configureTestingModule({
            imports: [ProfilePageComponent],
            providers: [
                { provide: Dialog, useValue: { open: openDialog } as unknown as Dialog },
                {
                    provide: ProfileService,
                    useValue: {
                        currentUserSignal: signal<GetMeResponse | null>(null),
                        getCurrentUser: () => of(null),
                        getMyApiKeys,
                    } as unknown as ProfileService,
                },
                { provide: AuthService, useValue: {} as AuthService },
                { provide: ToastService, useValue: { error: vi.fn() } as unknown as ToastService },
            ],
        });
        fixture = TestBed.createComponent(ProfilePageComponent);
        fixture.detectChanges();
    });

    function apiKeysStorage(): ProfileApiKeysStorageService {
        return fixture.debugElement.injector.get(ProfileApiKeysStorageService);
    }

    function changePasswordClosingWith(result: boolean | undefined): void {
        openDialog.mockReturnValue({ closed: of(result) });
        fixture.componentInstance.onPasswordChange();
    }

    it('reloads the API keys after a password change, since the server revokes them all', () => {
        getMyApiKeys.mockReturnValueOnce(of([apiKey(1, ApiKeyStatus.ACTIVE)]));
        apiKeysStorage().refresh().subscribe();
        getMyApiKeys.mockReturnValueOnce(of([apiKey(1, ApiKeyStatus.REVOKED)]));

        changePasswordClosingWith(true);

        expect(getMyApiKeys).toHaveBeenCalledTimes(2);
        expect(
            apiKeysStorage()
                .keys()
                .map((key) => key.status)
        ).toEqual([ApiKeyStatus.REVOKED]);
    });

    it.each([false, undefined])('leaves the API keys alone when the dialog closes with %s', (result) => {
        changePasswordClosingWith(result);

        expect(getMyApiKeys).not.toHaveBeenCalled();
    });
});

describe('ProfilePageComponent with the API keys tab open', () => {
    let getMyApiKeys: ReturnType<typeof vi.fn>;
    let openDialog: ReturnType<typeof vi.fn>;
    let currentUser: WritableSignal<GetMeResponse | null>;

    afterEach(() => {
        TestBed.inject(ActiveOrgService).clear();
        vi.unstubAllGlobals();
    });

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        getMyApiKeys = vi.fn();
        openDialog = vi.fn();
        const user = {
            id: 1,
            email: 'user@example.com',
            display_name: 'Test User',
            avatar_url: null,
            is_superadmin: false,
            memberships: [],
        } as unknown as GetMeResponse;
        currentUser = signal<GetMeResponse | null>(user);
        TestBed.configureTestingModule({
            providers: [
                provideRouter([
                    {
                        path: 'profile',
                        component: ProfilePageComponent,
                        children: [{ path: 'api-keys', component: ProfileApiKeysTabComponent }],
                    },
                ]),
                { provide: Dialog, useValue: { open: openDialog } as unknown as Dialog },
                {
                    provide: ProfileService,
                    useValue: {
                        currentUserSignal: currentUser,
                        getMyApiKeys,
                    } as unknown as ProfileService,
                },
                { provide: AuthService, useValue: {} as AuthService },
                { provide: ToastService, useValue: { error: vi.fn() } as unknown as ToastService },
            ],
        });
    });

    function renderedStatuses(harness: RouterTestingHarness): string[] {
        const element: HTMLElement = harness.fixture.nativeElement;
        return Array.from(element.querySelectorAll('app-profile-api-keys-tab app-status-badge')).map(
            (badge) => badge.textContent?.trim() ?? ''
        );
    }

    function texts(harness: RouterTestingHarness, selector: string): string[] {
        const element: HTMLElement = harness.fixture.nativeElement;
        return Array.from(element.querySelectorAll(selector)).map((node) => node.textContent?.trim() ?? '');
    }

    async function openApiKeysTab(): Promise<RouterTestingHarness> {
        const harness = await RouterTestingHarness.create();
        await harness.navigateByUrl('/profile/api-keys', ProfilePageComponent);
        return harness;
    }

    function clickChangePassword(harness: RouterTestingHarness): void {
        const element: HTMLElement = harness.fixture.nativeElement;
        const changePasswordButton = Array.from(element.querySelectorAll<HTMLElement>('app-button')).find(
            (button) => button.textContent?.trim() === 'Change password'
        )!;
        changePasswordButton.querySelector('button')!.click();
    }

    it('shows the keys as revoked in the tab once the password change dialog closes', async () => {
        getMyApiKeys.mockReturnValueOnce(of([apiKey(1, ApiKeyStatus.ACTIVE)]));
        const harness = await RouterTestingHarness.create();
        // The harness checks the component in its own outlet: the profile page, which hosts the tab.
        await harness.navigateByUrl('/profile/api-keys', ProfilePageComponent);
        expect(renderedStatuses(harness)).toEqual(['Active']);

        getMyApiKeys.mockReturnValueOnce(of([apiKey(1, ApiKeyStatus.REVOKED)]));
        openDialog.mockReturnValue({ closed: of(true) });
        clickChangePassword(harness);
        harness.detectChanges();

        expect(getMyApiKeys).toHaveBeenCalledTimes(2);
        expect(renderedStatuses(harness)).toEqual(['Revoked']);
    });

    it('shows the organization each key belongs to', async () => {
        getMyApiKeys.mockReturnValueOnce(
            of([
                apiKey(1, ApiKeyStatus.ACTIVE, { id: 1, name: 'Acme' }),
                apiKey(2, ApiKeyStatus.ACTIVE, { id: 2, name: 'Globex' }),
            ])
        );

        const harness = await openApiKeysTab();

        expect(texts(harness, 'app-profile-api-keys-tab .cell-text')).toEqual(
            expect.arrayContaining(['Acme', 'Globex'])
        );
    });

    function memberOf(org: { id: number; name: string }): void {
        currentUser.update((user) => ({
            ...user!,
            memberships: [{ organization: org } as FullMembership],
        }));
    }

    function createButton(harness: RouterTestingHarness): HTMLButtonElement {
        const element: HTMLElement = harness.fixture.nativeElement;
        const host = Array.from(element.querySelectorAll<HTMLElement>('app-profile-api-keys-tab app-button')).find(
            (button) => button.textContent?.trim() === 'Create API Key'
        )!;
        return host.querySelector('button')!;
    }

    it('counts only the active organization keys towards the per-organization limit', async () => {
        memberOf({ id: 1, name: 'Acme' });
        TestBed.inject(ActiveOrgService).set(1);
        getMyApiKeys.mockReturnValueOnce(
            of([
                apiKey(1, ApiKeyStatus.ACTIVE, { id: 1, name: 'Acme' }),
                apiKey(2, ApiKeyStatus.ACTIVE, { id: 2, name: 'Globex' }),
                apiKey(3, ApiKeyStatus.ACTIVE, { id: 3, name: 'Initech' }),
            ])
        );

        const harness = await openApiKeysTab();

        expect(texts(harness, 'app-profile-api-keys-tab .count')).toEqual(['1/5 active in Acme']);
    });

    it('names no organization in the count when the user is not a member of the active one', async () => {
        TestBed.inject(ActiveOrgService).set(5);
        getMyApiKeys.mockReturnValueOnce(of([]));

        const harness = await openApiKeysTab();

        expect(texts(harness, 'app-profile-api-keys-tab .count')).toEqual(['0/5 active in this organization']);
    });

    it.each([
        {
            situation: 'without an active organization',
            activeOrgId: null,
            activeKeys: 0,
            reason: 'Select an organization to create a key',
        },
        {
            situation: 'at the active key limit',
            activeOrgId: 1,
            activeKeys: 5,
            reason: 'Maximum active keys reached in this organization',
        },
    ])('keeps Create focusable but inert $situation, and says why', async ({ activeOrgId, activeKeys, reason }) => {
        TestBed.inject(ActiveOrgService).set(activeOrgId);
        getMyApiKeys.mockReturnValueOnce(
            of(Array.from({ length: activeKeys }, (_, index) => apiKey(index + 1, ApiKeyStatus.ACTIVE)))
        );

        const harness = await openApiKeysTab();
        const button = createButton(harness);
        button.click();

        expect(button.disabled).toBe(false);
        expect(button.getAttribute('aria-disabled')).toBe('true');
        const description = harness.fixture.nativeElement.querySelector(`#${button.getAttribute('aria-describedby')}`);
        expect(description?.textContent?.trim()).toBe(reason);
        expect(openDialog).not.toHaveBeenCalled();
    });
});
