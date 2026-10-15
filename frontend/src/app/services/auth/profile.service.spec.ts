import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActivePermissions, GetMeResponse } from '@shared/models';

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
    shortcut_overrides: {},
};

describe('ProfileService shortcut overrides', () => {
    let service: ProfileService;
    let httpMock: HttpTestingController;

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
        expect(service.shortcutOverrides()).toEqual({});
    });

    it('is empty when the user has no overrides', () => {
        loadUser(BASE_USER);
        expect(service.shortcutOverrides()).toEqual({});
    });

    it('exposes the overrides of the loaded user', () => {
        loadUser({ ...BASE_USER, shortcut_overrides: { 'node.agent': 'Alt+KeyG' } });
        expect(service.shortcutOverrides()).toEqual({ 'node.agent': 'Alt+KeyG' });
    });

    it('PATCHes the full map and keeps the rest of the current user as it was', () => {
        loadUser({ ...BASE_USER, shortcut_overrides: { 'node.llm': 'Alt+KeyL' } });
        let saved: Readonly<Record<string, string>> | undefined;

        service.updateShortcutOverrides({ 'node.agent': 'Alt+KeyG' }).subscribe((result) => (saved = result));
        const request = httpMock.expectOne({ method: 'PATCH', url: PROFILE_URL });
        expect(request.request.body).toEqual({ shortcut_overrides: { 'node.agent': 'Alt+KeyG' } });
        request.flush({
            ...BASE_USER,
            display_name: 'Changed elsewhere',
            active_organization_id: null,
            active_permissions: null,
            shortcut_overrides: { 'node.agent': 'Alt+KeyG' },
        });

        expect(saved).toEqual({ 'node.agent': 'Alt+KeyG' });
        expect(service.shortcutOverrides()).toEqual({ 'node.agent': 'Alt+KeyG' });
        const user = service.currentUserSignal();
        expect(user?.display_name).toBe('Jane Doe');
        expect(user?.active_organization_id).toBe(3);
        expect(user?.active_permissions).toEqual(ACTIVE_PERMISSIONS);
    });

    it('keeps the previous overrides and reports the error when the save fails', () => {
        loadUser({ ...BASE_USER, shortcut_overrides: { 'node.llm': 'Alt+KeyL' } });
        let failedWith: HttpErrorResponse | undefined;

        service.updateShortcutOverrides({ 'node.agent': 'Alt+KeyG' }).subscribe({
            error: (error: HttpErrorResponse) => (failedWith = error),
        });
        httpMock
            .expectOne({ method: 'PATCH', url: PROFILE_URL })
            .flush({ shortcut_overrides: ['Invalid'] }, { status: 400, statusText: 'Bad Request' });

        expect(failedWith?.status).toBe(400);
        expect(service.shortcutOverrides()).toEqual({ 'node.llm': 'Alt+KeyL' });
    });
});
