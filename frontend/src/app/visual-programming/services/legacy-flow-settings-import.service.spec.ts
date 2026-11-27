import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { FlowEditorPreferences, GeneralPreferences, GetMeResponse } from '@shared/models';

import { ProfileService } from '../../services/auth/profile.service';
import { API_URL, memberOf, ORGANIZATION_A, PROFILE_URL } from '../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../services/config';
import { LEGACY_FLOW_SETTINGS_KEY, LegacyFlowSettingsImportService } from './legacy-flow-settings-import.service';

const FLOW_EDITOR_URL = '/api/profile/preferences/flow_editor/';
const GENERAL_URL = '/api/profile/preferences/general/';
const BROWSER_ZONE = 'Europe/Kiev';

describe('LegacyFlowSettingsImportService', () => {
    let http: HttpTestingController;

    beforeEach(() => {
        localStorage.clear();
        // Faked on the prototype only: `new Intl.DateTimeFormat(…, { timeZone })` still checks zones for real.
        const resolvedOptions = Intl.DateTimeFormat.prototype.resolvedOptions;
        vi.spyOn(Intl.DateTimeFormat.prototype, 'resolvedOptions').mockImplementation(function (
            this: Intl.DateTimeFormat
        ) {
            return { ...resolvedOptions.call(this), timeZone: BROWSER_ZONE };
        });
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            ],
        });
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        http.verify();
        vi.restoreAllMocks();
    });

    function storeLegacy(value: unknown): void {
        localStorage.setItem(LEGACY_FLOW_SETTINGS_KEY, typeof value === 'string' ? value : JSON.stringify(value));
    }

    function signIn(
        {
            flowEditor = {},
            general = {},
        }: { flowEditor?: Partial<FlowEditorPreferences>; general?: Partial<GeneralPreferences> } = {},
        id = 7
    ): void {
        const user: GetMeResponse = memberOf(ORGANIZATION_A);
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        http.expectOne({ method: 'GET', url: PROFILE_URL }).flush({
            ...user,
            id,
            preferences: {
                general: { ...user.preferences.general, ...general },
                flow_editor: { ...user.preferences.flow_editor, ...flowEditor },
            },
        });
        TestBed.tick();
    }

    function startImport(): void {
        TestBed.inject(LegacyFlowSettingsImportService).start();
        TestBed.tick();
    }

    it('imports the legacy flow-settings key once and removes it', () => {
        storeLegacy({
            arrowColors: false,
            showInputsOutputs: false,
            edgeStyle: 'adaptive-curve',
            alwaysShowNodeNumbers: true,
            highlightUnusedNodes: false,
            timezone: BROWSER_ZONE,
        });
        startImport();
        signIn();

        const save = http.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL });
        // Only what differs from the defaults: an untouched value keeps following them.
        expect(save.request.body).toEqual({
            arrow_colors: false,
            edge_style: 'adaptive-curve',
            always_show_node_numbers: true,
        });
        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).not.toBeNull();
        save.flush({});
        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).toBeNull();

        // A reload of the profile, still with default values, moves nothing again.
        signIn();
    });

    it.each(['Europe/Kiev', 'Europe/Kyiv'])(
        'does not import a timezone equal to the browser zone (stored as %s)',
        (storedZone) => {
            storeLegacy({ timezone: storedZone });
            startImport();
            signIn();

            expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).toBeNull();
        }
    );

    it('imports a different legacy timezone as default_timezone', () => {
        storeLegacy({ edgeStyle: 'orthogonal', timezone: 'America/New_York' });
        startImport();
        signIn();

        const save = http.expectOne({ method: 'PATCH', url: GENERAL_URL });
        expect(save.request.body).toEqual({ default_timezone: 'America/New_York' });
        save.flush({ display_timezone: null, default_timezone: 'America/New_York' });

        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).toBeNull();
    });

    it('keeps a default timezone the account already has', () => {
        storeLegacy({ timezone: 'America/New_York' });
        startImport();
        signIn({ general: { default_timezone: 'Asia/Tokyo' } });

        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).toBeNull();
    });

    it('keeps account values when the account already has flow_editor values', () => {
        storeLegacy({ edgeStyle: 'adaptive-curve', timezone: 'America/New_York' });
        startImport();
        signIn({ flowEditor: { show_minimap: false } });

        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).toBeNull();
    });

    it('keeps the key for the next load when the save fails', () => {
        storeLegacy({ arrowColors: false });
        startImport();
        signIn();

        http.expectOne({ method: 'PATCH', url: FLOW_EDITOR_URL }).flush(
            { detail: 'Server error' },
            { status: 500, statusText: 'Server Error' }
        );

        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).not.toBeNull();
    });

    it.each([
        ['a value of the wrong type', { arrowColors: 'false', edgeStyle: 'bezier', timezone: 42 }],
        ['an unknown timezone', { timezone: 'Mars/Olympus_Mons' }],
        ['not JSON', '{oops'],
        ['not an object', '[true]'],
    ])('moves nothing from %s, and removes the key', (_case, stored) => {
        storeLegacy(stored);
        startImport();
        signIn();

        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).toBeNull();
    });

    it('does nothing before it is started', () => {
        storeLegacy({ arrowColors: false });
        TestBed.inject(LegacyFlowSettingsImportService);
        signIn();

        expect(localStorage.getItem(LEGACY_FLOW_SETTINGS_KEY)).not.toBeNull();
    });
});
