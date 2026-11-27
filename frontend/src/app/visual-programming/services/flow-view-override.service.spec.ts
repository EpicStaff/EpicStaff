import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';

import { ProfileService } from '../../services/auth/profile.service';
import { API_URL, memberOf, ORGANIZATION_A, PROFILE_URL } from '../../services/auth/testing/current-user-fixtures';
import { ConfigService } from '../../services/config';
import { ToastService } from '../../services/notifications';
import { FlowViewOverrideService } from './flow-view-override.service';
import { FlowViewOverride } from './flow-view-settings-api.service';

const USER_ID = 7;
const NEXT_USER_ID = 8;
const GRAPH_ID = 5;
const OTHER_GRAPH_ID = 6;
const VIEW_SETTINGS_URL = `/api/graphs/${GRAPH_ID}/my-view-settings/`;
const OTHER_VIEW_SETTINGS_URL = `/api/graphs/${OTHER_GRAPH_ID}/my-view-settings/`;

describe('FlowViewOverrideService', () => {
    let overrides: FlowViewOverrideService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: API_URL } as unknown as ConfigService },
            ],
        });
        overrides = TestBed.inject(FlowViewOverrideService);
        http = TestBed.inject(HttpTestingController);
        signIn(USER_ID);
    });

    afterEach(() => {
        // Reset even when a request is left open, so one failing test does not fail the ones after it.
        try {
            http.verify();
        } finally {
            TestBed.resetTestingModule();
        }
    });

    function signIn(userId: number): void {
        TestBed.inject(ProfileService).getCurrentUser().subscribe();
        http.expectOne({ method: 'GET', url: PROFILE_URL }).flush({ ...memberOf(ORGANIZATION_A), id: userId });
    }

    function openFlow(stored: FlowViewOverride, graphId = GRAPH_ID): void {
        overrides.load(graphId);
        http.expectOne({ method: 'GET', url: `/api/graphs/${graphId}/my-view-settings/` }).flush({ settings: stored });
    }

    function failRequest(request: TestRequest): void {
        request.flush({ detail: 'Server error' }, { status: 500, statusText: 'Server Error' });
    }

    function failLoad(): void {
        failRequest(http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL }));
    }

    async function errorToasts(): Promise<string[]> {
        const toasts = await firstValueFrom(TestBed.inject(ToastService).toasts$);
        return toasts.filter((toast) => toast.type === 'error').map((toast) => toast.message);
    }

    describe('a change made while the override loads', () => {
        it('keeps the stored keys', () => {
            overrides.load(GRAPH_ID);
            const load = http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL });

            overrides.save({ arrow_colors: false });
            expect(overrides.override()).toEqual({ arrow_colors: false });
            http.expectNone({ method: 'PUT', url: VIEW_SETTINGS_URL });
            load.flush({ settings: { edge_style: 'adaptive-curve' } });

            const put = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(put.request.body).toEqual({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
            expect(overrides.override()).toEqual({ edge_style: 'adaptive-curve', arrow_colors: false });
        });

        it('wins over the stored value of the same key, and a key it drops goes', () => {
            overrides.load(GRAPH_ID);
            const load = http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL });

            overrides.save({ show_minimap: false, arrow_colors: false });
            overrides.save({ show_minimap: false });
            load.flush({ settings: { edge_style: 'adaptive-curve', show_minimap: true, arrow_colors: false } });

            const put = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(put.request.body).toEqual({ settings: { edge_style: 'adaptive-curve', show_minimap: false } });
        });

        it('sends nothing when it leaves the stored override as it is', () => {
            overrides.load(GRAPH_ID);
            const load = http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL });

            overrides.save({ show_minimap: false });
            load.flush({ settings: { show_minimap: false } });

            http.expectNone(VIEW_SETTINGS_URL);
            expect(overrides.override()).toEqual({ show_minimap: false });
        });

        it('drops the stored keys too when it is a reset', () => {
            overrides.load(GRAPH_ID);
            const load = http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL });

            overrides.save({ arrow_colors: false });
            overrides.reset();
            load.flush({ settings: { edge_style: 'adaptive-curve' } });

            http.expectOne({ method: 'DELETE', url: VIEW_SETTINGS_URL }).flush(null, { status: 204, statusText: '' });
            expect(overrides.override()).toEqual({});
        });
    });

    describe('after a failed load', () => {
        it('an edit does not wipe the stored override', () => {
            overrides.load(GRAPH_ID);
            failLoad();

            overrides.save({ arrow_colors: false });

            http.expectNone({ method: 'PUT', url: VIEW_SETTINGS_URL });
            http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL }).flush({
                settings: { edge_style: 'adaptive-curve' },
            });
            const put = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(put.request.body).toEqual({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
        });

        it('takes the edit back and says so when the override still cannot be loaded', async () => {
            overrides.load(GRAPH_ID);
            failLoad();

            overrides.save({ arrow_colors: false });
            failLoad();

            expect(overrides.override()).toEqual({});
            expect(await errorToasts()).toEqual([expect.stringContaining('Could not save the flow setting')]);
        });

        it('takes back an edit made while the failing load was on its way', async () => {
            overrides.load(GRAPH_ID);
            overrides.save({ arrow_colors: false });
            failLoad();

            http.expectNone({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(overrides.override()).toEqual({});
            expect(await errorToasts()).toEqual([expect.stringContaining('Could not save the flow setting')]);
        });

        it('opens quietly with no override while nothing was changed', async () => {
            overrides.load(GRAPH_ID);
            failLoad();

            expect(overrides.override()).toEqual({});
            expect(await errorToasts()).toEqual([]);
        });
    });

    it('a save still in flight when the flow is reopened is not lost', () => {
        openFlow({ edge_style: 'adaptive-curve' });
        overrides.save({ edge_style: 'adaptive-curve', arrow_colors: false });
        const save = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });

        overrides.clear();
        overrides.load(GRAPH_ID);
        // A load sent now could be answered before the save lands, with the override from before it.
        for (const early of http.match({ method: 'GET', url: VIEW_SETTINGS_URL })) {
            early.flush({ settings: { edge_style: 'adaptive-curve' } });
        }
        save.flush({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
        for (const late of http.match({ method: 'GET', url: VIEW_SETTINGS_URL })) {
            late.flush({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
        }

        expect(overrides.override()).toEqual({ edge_style: 'adaptive-curve', arrow_colors: false });
        overrides.save({ ...overrides.override(), show_minimap: false });
        expect(http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL }).request.body).toEqual({
            settings: { edge_style: 'adaptive-curve', arrow_colors: false, show_minimap: false },
        });
    });

    describe('an edit made while a flow loads, then another flow is opened', () => {
        it('is still saved, without touching the flow now open', () => {
            overrides.load(GRAPH_ID);
            const load = http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL });
            overrides.save({ arrow_colors: false });

            openFlow({ show_minimap: false }, OTHER_GRAPH_ID);
            load.flush({ settings: { edge_style: 'adaptive-curve' } });

            const save = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(save.request.body).toEqual({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
            save.flush({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
            expect(overrides.override()).toEqual({ show_minimap: false });
            http.expectNone(OTHER_VIEW_SETTINGS_URL);
        });

        it('is reported when the flow it was made in cannot be loaded', async () => {
            overrides.load(GRAPH_ID);
            const load = http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL });
            overrides.save({ arrow_colors: false });

            openFlow({ show_minimap: false }, OTHER_GRAPH_ID);
            failRequest(load);

            http.expectNone({ method: 'PUT', url: VIEW_SETTINGS_URL });
            expect(overrides.override()).toEqual({ show_minimap: false });
            expect(await errorToasts()).toEqual([expect.stringContaining('Could not save the flow setting')]);
        });

        it('shows up when its flow is opened again before it is saved', () => {
            overrides.load(GRAPH_ID);
            const firstLoad = http.expectOne({ method: 'GET', url: VIEW_SETTINGS_URL });
            overrides.save({ arrow_colors: false });
            openFlow({}, OTHER_GRAPH_ID);

            overrides.load(GRAPH_ID);
            // A second load sent now would be answered with the override from before the edit.
            const early = http.match({ method: 'GET', url: VIEW_SETTINGS_URL });
            firstLoad.flush({ settings: { edge_style: 'adaptive-curve' } });
            early.forEach((request) => request.flush({ settings: { edge_style: 'adaptive-curve' } }));
            http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL }).flush({
                settings: { edge_style: 'adaptive-curve', arrow_colors: false },
            });
            for (const late of http.match({ method: 'GET', url: VIEW_SETTINGS_URL })) {
                late.flush({ settings: { edge_style: 'adaptive-curve', arrow_colors: false } });
            }

            expect(overrides.override()).toEqual({ edge_style: 'adaptive-curve', arrow_colors: false });
        });
    });

    it('a failed PUT rolls back to the stored value, with a newer write queued', async () => {
        openFlow({ edge_style: 'adaptive-curve' });
        overrides.save({ edge_style: 'adaptive-curve', arrow_colors: false });
        overrides.save({ edge_style: 'adaptive-curve', arrow_colors: false, show_minimap: false });

        failRequest(http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL }));
        // The newer change is still on its way, so it stays.
        expect(overrides.override()).toEqual({
            edge_style: 'adaptive-curve',
            arrow_colors: false,
            show_minimap: false,
        });
        failRequest(http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL }));

        expect(overrides.override()).toEqual({ edge_style: 'adaptive-curve' });
        expect(await errorToasts()).toEqual([
            expect.stringContaining('Could not save the flow setting'),
            expect.stringContaining('Could not save the flow setting'),
        ]);
    });

    it('queued writes of a signed-out user are not sent for the next user', () => {
        openFlow({});
        overrides.save({ arrow_colors: false });
        overrides.save({ arrow_colors: false, show_minimap: false });
        const inFlight = http.expectOne({ method: 'PUT', url: VIEW_SETTINGS_URL });

        TestBed.inject(ProfileService).clearCurrentUser();
        signIn(NEXT_USER_ID);
        inFlight.flush({ settings: { arrow_colors: false } });

        http.expectNone({ method: 'PUT', url: VIEW_SETTINGS_URL });
    });
});
