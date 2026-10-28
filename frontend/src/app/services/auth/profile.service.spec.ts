import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivePermissions, GetMeResponse, ShortcutSettings } from '@shared/models';

import { ConfigService } from '../config';
import { ProfileService } from './profile.service';

const PROFILE_URL = '/api/profile/';

const ACTIVE_PERMISSIONS: ActivePermissions = {
    org_id: 3,
    is_superadmin: false,
    role: { id: 2, name: 'Admin' },
    permissions: '*',
};

const BASE_USER: GetMeResponse = {
    id: 7,
    email: 'jane@example.com',
    display_name: 'Jane Doe',
    is_superadmin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    memberships: [],
    active_organization_id: 3,
    active_permissions: ACTIVE_PERMISSIONS,
    avatar_url: null,
    completed_tours: [],
    custom_shortcuts: { custom: [], overrides: {} },
};

describe('ProfileService shortcut settings', () => {
    let service: ProfileService;
    let httpMock: HttpTestingController;

    const SAVED: ShortcutSettings = {
        custom: [{ action: 'editing.save', keys: 'Alt+KeyS' }],
        overrides: {},
    };

    const EDITED: ShortcutSettings = {
        overrides: { 'node.python': 'Alt+KeyP' },
        custom: [
            { action: 'editing.save', keys: 'Alt+KeyS' },
            { action: 'node.task', keys: 'Shift+KeyP' },
            { action: 'node.agent', keys: null },
        ],
    };

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(ProfileService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function loadUser(user: GetMeResponse): void {
        service.getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush(user);
    }

    it('is empty when no user is loaded', () => {
        expect(service.shortcutSettings()).toEqual({ custom: [], overrides: {} });
    });

    it('exposes the settings of the loaded user', () => {
        loadUser({ ...BASE_USER, custom_shortcuts: SAVED });

        expect(service.shortcutSettings()).toEqual(SAVED);
    });

    it('PATCHes the whole value and keeps the rest of the current user as it was', () => {
        loadUser({ ...BASE_USER, custom_shortcuts: SAVED });
        let saved: ShortcutSettings | undefined;

        service.updateShortcutSettings(EDITED).subscribe((result) => (saved = result));
        const request = httpMock.expectOne({ method: 'PATCH', url: PROFILE_URL });
        expect(request.request.body).toEqual({ custom_shortcuts: EDITED });
        request.flush({
            ...BASE_USER,
            display_name: 'Changed elsewhere',
            active_organization_id: null,
            active_permissions: null,
            custom_shortcuts: EDITED,
        });

        expect(saved).toEqual(EDITED);
        expect(service.shortcutSettings()).toEqual(EDITED);
        const user = service.currentUserSignal();
        expect(user?.display_name).toBe('Jane Doe');
        expect(user?.active_organization_id).toBe(3);
        expect(user?.active_permissions).toEqual(ACTIVE_PERMISSIONS);
    });

    it('keeps the previous settings and reports the error when the save fails', () => {
        loadUser({ ...BASE_USER, custom_shortcuts: SAVED });
        let failedWith: HttpErrorResponse | undefined;

        service.updateShortcutSettings(EDITED).subscribe({
            error: (error: HttpErrorResponse) => (failedWith = error),
        });
        httpMock
            .expectOne({ method: 'PATCH', url: PROFILE_URL })
            .flush({ custom_shortcuts: ['Invalid'] }, { status: 400, statusText: 'Bad Request' });

        expect(failedWith?.status).toBe(400);
        expect(service.shortcutSettings()).toEqual(SAVED);
    });
});

describe('ProfileService tour progress', () => {
    let service: ProfileService;
    let httpMock: HttpTestingController;

    const OTHER_USER: GetMeResponse = { ...BASE_USER, id: 8, email: 'john@example.com', display_name: 'John Roe' };

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(ProfileService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function loadUser(user: GetMeResponse): void {
        service.getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush(user);
    }

    function expectTourSave(tourKey: string): TestRequest {
        return httpMock.expectOne({ method: 'POST', url: `${PROFILE_URL}tours/${tourKey}/complete/` });
    }

    it('saves the tour with an empty POST, emits the completed tours, and the signed-in user then lists it', () => {
        loadUser({ ...BASE_USER, completed_tours: ['release-notes'] });
        let completedTours: readonly string[] | undefined;

        service.markTourCompleted('quick-start').subscribe((tours) => (completedTours = tours));
        const request = expectTourSave('quick-start');
        expect(request.request.body).toBeNull();
        request.flush({ ...BASE_USER, completed_tours: ['quick-start', 'release-notes'] });

        expect(completedTours).toEqual(['quick-start', 'release-notes']);
        expect(service.currentUserSignal()?.completed_tours).toEqual(['quick-start', 'release-notes']);
    });

    it('sends the tour key as a single encoded path segment', () => {
        loadUser(BASE_USER);

        service.markTourCompleted('a b/c').subscribe({ error: () => undefined });

        expectTourSave('a%20b%2Fc').flush(
            { status_code: 400, code: 'invalid', message: 'Invalid tour key.' },
            { status: 400, statusText: 'Bad Request' }
        );
    });

    it('keeps a profile change that landed while the save was on its way', () => {
        loadUser(BASE_USER);

        service.markTourCompleted('quick-start').subscribe();
        service.updateCurrentUser({ display_name: 'Jane Smith' }).subscribe();
        httpMock
            .expectOne({ method: 'PATCH', url: PROFILE_URL })
            .flush({ ...BASE_USER, display_name: 'Jane Smith', completed_tours: ['quick-start'] });
        // The backend read this profile before the rename.
        expectTourSave('quick-start').flush({ ...BASE_USER, completed_tours: ['quick-start'] });

        expect(service.currentUserSignal()?.display_name).toBe('Jane Smith');
        expect(service.currentUserSignal()?.completed_tours).toEqual(['quick-start']);
    });

    it('does not bring the user back when the save lands after sign-out', () => {
        loadUser(BASE_USER);

        service.markTourCompleted('quick-start').subscribe();
        service.clearCurrentUser();
        expectTourSave('quick-start').flush({ ...BASE_USER, completed_tours: ['quick-start'] });

        expect(service.currentUserSignal()).toBeNull();
    });

    it('does not change another user who signed in while the save was on its way', () => {
        loadUser(BASE_USER);

        service.markTourCompleted('quick-start').subscribe();
        service.clearCurrentUser();
        loadUser(OTHER_USER);
        expectTourSave('quick-start').flush({ ...BASE_USER, completed_tours: ['quick-start'] });

        expect(service.currentUserSignal()).toEqual(OTHER_USER);
    });
});
