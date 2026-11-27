import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { FlowEditorPreferences, GetMeResponse, UserPreferences } from '@shared/models';
import { firstValueFrom } from 'rxjs';

import { ConfigService } from '../config';
import { ToastService } from '../notifications';
import { ProfileService } from './profile.service';
import { API_URL, memberOf, ORGANIZATION_A, PROFILE_URL } from './testing/current-user-fixtures';
import { PREFERENCES_SAVE_DEBOUNCE_MS, UserPreferencesService } from './user-preferences.service';

const FLOW_EDITOR_URL = '/api/profile/preferences/flow_editor/';
const GENERAL_URL = '/api/profile/preferences/general/';

const STORED_FLOW_EDITOR: FlowEditorPreferences = {
    arrow_colors: false,
    show_inputs_outputs: true,
    edge_style: 'orthogonal',
    always_show_node_numbers: false,
    highlight_unused_nodes: false,
    show_minimap: true,
    on_open: 'restore',
};

describe('UserPreferencesService', () => {
    let service: UserPreferencesService;
    let profileService: ProfileService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        vi.useFakeTimers();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(UserPreferencesService);
        profileService = TestBed.inject(ProfileService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        httpMock.verify();
        vi.useRealTimers();
    });

    function userWith(preferences: Partial<UserPreferences>, id = 7): GetMeResponse {
        const user = memberOf(ORGANIZATION_A);
        return { ...user, id, preferences: { ...user.preferences, ...preferences } };
    }

    function loadUser(user: GetMeResponse): void {
        profileService.getCurrentUser().subscribe();
        httpMock.expectOne({ method: 'GET', url: PROFILE_URL }).flush(user);
    }

    function waitOutDebounce(): void {
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS);
    }

    async function errorToasts(): Promise<string[]> {
        const toasts = await firstValueFrom(TestBed.inject(ToastService).toasts$);
        return toasts.filter((toast) => toast.type === 'error').map((toast) => toast.message);
    }

    it('merges server values over defaults', () => {
        const flowEditor = service.section('flow_editor');
        expect(flowEditor().on_open).toBe('fit');

        // A server that does not send `on_open` yet: the default fills the gap.
        const withoutOnOpen: Omit<FlowEditorPreferences, 'on_open'> = {
            arrow_colors: false,
            show_inputs_outputs: true,
            edge_style: 'adaptive-curve',
            always_show_node_numbers: false,
            highlight_unused_nodes: false,
            show_minimap: false,
        };
        loadUser(userWith({ flow_editor: withoutOnOpen as FlowEditorPreferences }));

        expect(flowEditor()).toEqual({ ...withoutOnOpen, on_open: 'fit' });
        expect(service.section('general')()).toEqual({ display_timezone: null, default_timezone: null });
    });

    it('takes the defaults for a profile without preferences', () => {
        const withoutPreferences: Partial<GetMeResponse> = userWith({});
        delete withoutPreferences.preferences;
        loadUser(withoutPreferences as GetMeResponse);

        expect(service.section('general')()).toEqual({ display_timezone: null, default_timezone: null });
        expect(service.section('flow_editor')().on_open).toBe('fit');
    });

    it('applies a change immediately and PATCHes /api/profile/preferences/flow_editor/', () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        const flowEditor = service.section('flow_editor');

        service.patchSection('flow_editor', { edge_style: 'adaptive-curve' });

        expect(flowEditor().edge_style).toBe('adaptive-curve');
        waitOutDebounce();
        const request = httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        expect(request.request.body).toEqual({ edge_style: 'adaptive-curve' });

        request.flush({ ...STORED_FLOW_EDITOR, edge_style: 'adaptive-curve' });

        expect(flowEditor().edge_style).toBe('adaptive-curve');
        expect(profileService.currentUserSignal()?.preferences.flow_editor.edge_style).toBe('adaptive-curve');
    });

    it('debounces several changes into one PATCH', () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));

        service.patchSection('flow_editor', { arrow_colors: true });
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS - 1);
        service.patchSection('flow_editor', { show_minimap: false });
        vi.advanceTimersByTime(PREFERENCES_SAVE_DEBOUNCE_MS - 1);
        httpMock.expectNone({ method: 'PATCH', url: FLOW_EDITOR_URL });

        vi.advanceTimersByTime(1);
        const request = httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        expect(request.request.body).toEqual({ arrow_colors: true, show_minimap: false });
        request.flush({ ...STORED_FLOW_EDITOR, arrow_colors: true, show_minimap: false });
    });

    it('saves each section in its own PATCH', () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));

        service.patchSection('flow_editor', { show_minimap: false });
        service.patchSection('general', { display_timezone: 'Europe/Kyiv' });
        waitOutDebounce();

        expect(httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL }).request.body).toEqual({
            show_minimap: false,
        });
        expect(httpMock.expectOne({ method: 'PATCH', url: GENERAL_URL }).request.body).toEqual({
            display_timezone: 'Europe/Kyiv',
        });
    });

    it('rolls back and toasts on error', async () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        const flowEditor = service.section('flow_editor');

        service.patchSection('flow_editor', { edge_style: 'adaptive-curve', show_minimap: false });
        waitOutDebounce();
        httpMock
            .expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL })
            .flush({ edge_style: ['Not a valid choice.'] }, { status: 400, statusText: 'Bad Request' });

        expect(flowEditor()).toEqual(STORED_FLOW_EDITOR);
        expect(await errorToasts()).toEqual(['Could not save the setting: Edge style: Not a valid choice.']);
    });

    it('keeps a pending section value when the profile reloads mid-save', () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        const flowEditor = service.section('flow_editor');

        service.patchSection('flow_editor', { show_minimap: false });
        waitOutDebounce();
        const save: TestRequest = httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });

        // The reload was answered before the save was stored, so it still carries the old value.
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        expect(flowEditor().show_minimap).toBe(false);

        save.flush({ ...STORED_FLOW_EDITOR, show_minimap: false });
        expect(flowEditor().show_minimap).toBe(false);
    });

    it('keeps a value changed again while the previous save was in flight', () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        const flowEditor = service.section('flow_editor');

        service.patchSection('flow_editor', { edge_style: 'adaptive-curve' });
        waitOutDebounce();
        const firstSave = httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        service.patchSection('flow_editor', { edge_style: 'orthogonal' });
        firstSave.flush({ ...STORED_FLOW_EDITOR, edge_style: 'adaptive-curve' });

        expect(flowEditor().edge_style).toBe('orthogonal');
        waitOutDebounce();
        const secondSave = httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        expect(secondSave.request.body).toEqual({ edge_style: 'orthogonal' });
        secondSave.flush(STORED_FLOW_EDITOR);
    });

    it("neither shows nor saves the previous user's change for the next user", () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }, 7));
        service.patchSection('flow_editor', { show_minimap: false });

        profileService.clearCurrentUser();
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }, 8));
        expect(service.section('flow_editor')().show_minimap).toBe(true);

        service.patchSection('flow_editor', { arrow_colors: true });
        waitOutDebounce();
        const request = httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        expect(request.request.body).toEqual({ arrow_colors: true });
        request.flush({ ...STORED_FLOW_EDITOR, arrow_colors: true });
    });

    it('drops a change not sent before sign-out, so the same user signing back in sees the stored value', () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        const flowEditor = service.section('flow_editor');
        service.patchSection('flow_editor', { show_minimap: false });

        profileService.clearCurrentUser();
        TestBed.tick();
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        TestBed.tick();
        waitOutDebounce();

        expect(flowEditor().show_minimap).toBe(true);
        httpMock.expectNone({ method: 'PATCH', url: FLOW_EDITOR_URL });
    });

    it('keeps a value set back while its save fails, since the newer save is still to come', () => {
        loadUser(userWith({ flow_editor: STORED_FLOW_EDITOR }));
        const flowEditor = service.section('flow_editor');

        service.patchSection('flow_editor', { show_minimap: false });
        waitOutDebounce();
        const failingSave = httpMock.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        service.patchSection('flow_editor', { show_minimap: true });
        service.patchSection('flow_editor', { show_minimap: false });
        failingSave.flush(null, { status: 503, statusText: 'Service Unavailable' });

        expect(flowEditor().show_minimap).toBe(false);
        waitOutDebounce();
        httpMock
            .expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL })
            .flush({ ...STORED_FLOW_EDITOR, show_minimap: false });
        expect(flowEditor().show_minimap).toBe(false);
    });
});
