import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { FlowEditorPreferences, GeneralPreferences, GetMeResponse } from '@shared/models';
import { browserTimeZone } from '@shared/utils';

import { ProfileService } from '../../services/auth/profile.service';
import { API_URL, memberOf, ORGANIZATION_A, PROFILE_URL } from '../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../services/config';
import { FlowSettingsService } from './flow-settings.service';
import { FlowViewOverrideService } from './flow-view-override.service';
import { FlowViewOverride } from './flow-view-settings-api.service';

const GRAPH_ID = 5;
const OTHER_GRAPH_ID = 6;
const VIEW_SETTINGS_URL = `/api/graphs/${GRAPH_ID}/my-view-settings/`;
const OTHER_VIEW_SETTINGS_URL = `/api/graphs/${OTHER_GRAPH_ID}/my-view-settings/`;

describe('FlowSettingsService', () => {
    let settings: FlowSettingsService;
    let overrides: FlowViewOverrideService;
    let http: HttpTestingController;

    beforeEach(() => {
        localStorage.clear();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            ],
        });
        settings = TestBed.inject(FlowSettingsService);
        overrides = TestBed.inject(FlowViewOverrideService);
        http = TestBed.inject(HttpTestingController);
        signIn({ edge_style: 'orthogonal', arrow_colors: true, show_minimap: true });
    });

    afterEach(() => http.verify());

    function signIn(flowEditor: Partial<FlowEditorPreferences>, general: Partial<GeneralPreferences> = {}): void {
        const user: GetMeResponse = memberOf(ORGANIZATION_A);
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        http.expectOne({ method: 'GET', url: PROFILE_URL }).flush({
            ...user,
            preferences: {
                general: { ...user.preferences.general, ...general },
                flow_editor: { ...user.preferences.flow_editor, ...flowEditor },
            },
        });
    }

    function openFlow(stored: FlowViewOverride, graphId = GRAPH_ID): void {
        overrides.load(graphId);
        http.expectOne({ method: 'GET', url: `/api/graphs/${graphId}/my-view-settings/` }).flush({
            settings: stored,
        });
    }

    it('shows the account values while no flow is open', () => {
        expect(settings.edgeStyle()).toBe('orthogonal');
        expect(settings.showMinimap()).toBe(true);
        expect(settings.hasFlowOverride()).toBe(false);
    });

    it('override wins over account and reset drops it', () => {
        openFlow({ edge_style: 'adaptive-curve' });
        expect(settings.edgeStyle()).toBe('adaptive-curve');
        expect(settings.arrowColorsEnabled()).toBe(true);

        settings.setForCurrentFlow({ arrow_colors: false });
        expect(settings.arrowColorsEnabled()).toBe(false);
        const put = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
        expect(put.request.body).toEqual({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
        put.flush({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });

        settings.resetCurrentFlow();
        expect(settings.edgeStyle()).toBe('orthogonal');
        expect(settings.arrowColorsEnabled()).toBe(true);
        expect(settings.hasFlowOverride()).toBe(false);
        http.expectOne({ method: 'DELETE', url: VIEW_SETTINGS_URL }).flush(null, { status: 204, statusText: '' });
    });

    it("drops a value set back to the account's, so the flow follows the account for it again", () => {
        openFlow({ edge_style: 'adaptive-curve' });

        settings.setForCurrentFlow({ edge_style: 'orthogonal' });

        expect(settings.hasFlowOverride()).toBe(false);
        http.expectOne({ method: 'DELETE', url: VIEW_SETTINGS_URL }).flush(null, { status: 204, statusText: '' });
    });

    it("does not show the previous flow's override on the next one", () => {
        openFlow({ edge_style: 'adaptive-curve' });

        overrides.load(OTHER_GRAPH_ID);
        expect(settings.edgeStyle()).toBe('orthogonal');
        http.expectOne({ method: 'GET', url: OTHER_VIEW_SETTINGS_URL }).flush({ settings: {} });

        expect(settings.edgeStyle()).toBe('orthogonal');
    });

    it("opens with the account's values when the override cannot be loaded", () => {
        overrides.load(GRAPH_ID);
        http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL }).flush(
            { detail: 'Not found.' },
            { status: 404, statusText: 'Not Found' }
        );

        expect(settings.edgeStyle()).toBe('orthogonal');
    });

    it('sends the saves of quick changes in order, each with the whole override', () => {
        openFlow({});

        settings.setForCurrentFlow({ show_minimap: false });
        settings.setForCurrentFlow({ arrow_colors: false });

        const first = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
        expect(first.request.body).toEqual({ settings: { show_minimap: false } });
        first.flush({ settings: { show_minimap: false } });
        const second = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
        expect(second.request.body).toEqual({ settings: { show_minimap: false, arrow_colors: false } });
        second.flush({ settings: { show_minimap: false, arrow_colors: false } });

        expect(settings.showMinimap()).toBe(false);
        expect(settings.arrowColorsEnabled()).toBe(false);
    });

    it('changes nothing while no flow is open', () => {
        settings.setForCurrentFlow({ show_minimap: false });

        expect(settings.showMinimap()).toBe(true);
    });

    describe('the zone new schedule triggers open with', () => {
        it.each([
            ['the flow has its own zone', 'America/New_York', 'Asia/Tokyo', 'America/New_York'],
            ["the flow follows the account's default", undefined, 'Asia/Tokyo', 'Asia/Tokyo'],
            ['neither sets one, the browser zone', undefined, null, browserTimeZone()],
        ] as const)('is the right one when %s', (_case, flowZone, accountZone, expected) => {
            signIn({}, { default_timezone: accountZone });
            openFlow(flowZone ? { default_timezone: flowZone } : {});

            expect(settings.newScheduleZone()).toBe(expected);
        });

        it('stops using the flow zone once the flow is left, so it never reaches another flow', () => {
            signIn({}, { default_timezone: 'Asia/Tokyo' });
            openFlow({ default_timezone: 'America/New_York' });

            overrides.clear();

            expect(settings.newScheduleZone()).toBe('Asia/Tokyo');
            expect(settings.flowScheduleZone()).toBeNull();
        });

        it('keeps a zone picked for the flow while the account follows the browser, even if it is the same zone', () => {
            openFlow({});

            settings.setForCurrentFlow({ default_timezone: browserTimeZone() });

            const save = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(save.request.body).toEqual({ settings: { default_timezone: browserTimeZone() } });
        });
    });
});
