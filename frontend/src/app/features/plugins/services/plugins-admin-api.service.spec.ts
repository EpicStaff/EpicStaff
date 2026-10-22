import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import {
    PluginBackupList,
    PluginDetail,
    PluginGrant,
    PluginOrgRemovedJob,
    PluginRestore,
} from '../models/plugin-admin.model';
import { PluginGrantPurgePreview, PluginPurgePreview } from '../models/plugin-purge-preview.model';
import { PluginSuspendPreview } from '../models/plugin-suspend-preview.model';
import {
    buildGrantPurgePreview,
    buildOrgRemovedJob,
    buildPluginBackupList,
    buildPluginDetail,
    buildPluginGrant,
    buildPluginPurgePreview,
    buildPluginRestore,
    buildPluginUpgrade,
    buildSuspendPreview,
} from '../testing/plugin-fixtures';
import { PluginsAdminApiService } from './plugins-admin-api.service';

describe('PluginsAdminApiService', () => {
    let http: HttpTestingController;
    let api: PluginsAdminApiService;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        http = TestBed.inject(HttpTestingController);
        api = TestBed.inject(PluginsAdminApiService);
    });

    afterEach(() => http.verify());

    it('asks to run a failed install hook again and answers with the grant installing', () => {
        const body = buildPluginGrant({ state: 'granting' });
        let answer: PluginGrant | undefined;

        api.retryHook('weather', 5).subscribe((grant) => (answer = grant));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/retry-hook/');
        request.flush(body, { status: 202, statusText: 'Accepted' });

        expect(request.request.method).toBe('POST');
        expect(answer).toEqual(body);
    });

    it('approves a first install with the untrusted acknowledgement only', () => {
        api.approvePackage(11, { untrusted_acknowledged: true }).subscribe();
        const request = http.expectOne('/api/admin/plugins/packages/11/approve/');
        request.flush(buildPluginDetail());

        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ untrusted_acknowledged: true });
    });

    it('starts an upgrade with the acknowledgements, the reviewed baseline and the needed settings', () => {
        const body = buildPluginDetail({ open_upgrade: buildPluginUpgrade() });
        let answer: PluginDetail | undefined;

        api.approvePackage(12, {
            access_growth_acknowledged: true,
            reviewed_against_package_id: 10,
            settings: { units: 'metric', api_key: 's3cret' },
        }).subscribe((plugin) => (answer = plugin));
        const request = http.expectOne('/api/admin/plugins/packages/12/approve/');
        request.flush(body, { status: 202, statusText: 'Accepted' });

        expect(request.request.body).toEqual({
            access_growth_acknowledged: true,
            reviewed_against_package_id: 10,
            settings: { units: 'metric', api_key: 's3cret' },
        });
        expect(answer).toEqual(body);
    });

    it('cancels and retries the open upgrade with an empty body', () => {
        const cancelled = buildPluginDetail();
        const retried = buildPluginDetail({ open_upgrade: buildPluginUpgrade() });
        const answers: PluginDetail[] = [];

        api.cancelUpgrade('weather').subscribe((plugin) => answers.push(plugin));
        const cancel = http.expectOne('/api/admin/plugins/weather/upgrade/cancel/');
        cancel.flush(cancelled);
        api.retryUpgrade('weather').subscribe((plugin) => answers.push(plugin));
        const retry = http.expectOne('/api/admin/plugins/weather/upgrade/retry/');
        retry.flush(retried, { status: 202, statusText: 'Accepted' });

        expect([cancel.request.method, retry.request.method]).toEqual(['POST', 'POST']);
        expect([cancel.request.body, retry.request.body]).toEqual([null, null]);
        expect(answers).toEqual([cancelled, retried]);
    });

    it('lists the backups of the plugin’s database', () => {
        const body = buildPluginBackupList();
        let answer: PluginBackupList | undefined;

        api.listBackups('weather').subscribe((list) => (answer = list));
        const request = http.expectOne('/api/admin/plugins/weather/backups/');
        request.flush(body);

        expect(request.request.method).toBe('GET');
        expect(answer).toEqual(body);
    });

    it('asks for a restore with the phrase exactly as typed', () => {
        const body = buildPluginRestore({ state: 'pending', step: null });
        let answer: PluginRestore | undefined;

        api.restoreBackup('weather', 62, ' restore-weather').subscribe((restore) => (answer = restore));
        const request = http.expectOne('/api/admin/plugins/weather/backups/62/restore/');
        request.flush(body, { status: 202, statusText: 'Accepted' });

        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ verification_phrase: ' restore-weather' });
        expect(answer).toEqual(body);
    });

    it('reads what suspending a grant would stop', () => {
        const body = buildSuspendPreview();
        let answer: PluginSuspendPreview | undefined;

        api.getSuspendPreview('weather', 5).subscribe((preview) => (answer = preview));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/suspend-preview/');
        request.flush(body);

        expect(request.request.method).toBe('GET');
        expect(answer).toEqual(body);
    });

    it('suspends a grant with an empty body and answers with the grant suspended', () => {
        const body = buildPluginGrant({
            state: 'suspended',
            allowed_actions: ['resume'],
            suspended_at: '2026-10-21T09:00:00Z',
            purge_after: '2026-11-20T09:00:00Z',
        });
        let answer: PluginGrant | undefined;

        api.suspendGrant('weather', 5).subscribe((grant) => (answer = grant));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/suspend/');
        request.flush(body);

        expect(request.request.method).toBe('POST');
        expect(request.request.body).toBeNull();
        expect(answer).toEqual(body);
    });

    it('resumes a grant with an empty body and answers with the grant as it is now', () => {
        const body = buildPluginGrant();
        let answer: PluginGrant | undefined;

        api.resumeGrant('weather', 5).subscribe((grant) => (answer = grant));
        const request = http.expectOne('/api/admin/plugins/weather/grants/5/resume/');
        request.flush(body);

        expect(request.request.method).toBe('POST');
        expect(request.request.body).toBeNull();
        expect(answer).toEqual(body);
    });

    it('encodes the plugin identifier in grant paths', () => {
        api.suspendGrant('my plugin', 5).subscribe();

        http.expectOne('/api/admin/plugins/my%20plugin/grants/5/suspend/').flush(buildPluginGrant());
    });
    it('uninstalls and reinstalls a plugin with empty bodies', () => {
        const uninstalled = buildPluginDetail({ state: 'uninstalling', allowed_actions: ['reinstall', 'purge'] });
        let answer: PluginDetail | undefined;

        api.uninstallPlugin('weather').subscribe((plugin) => (answer = plugin));
        const uninstall = http.expectOne('/api/admin/plugins/weather/uninstall/');
        uninstall.flush(uninstalled);
        expect(uninstall.request.method).toBe('POST');
        expect(uninstall.request.body).toBeNull();
        expect(answer).toEqual(uninstalled);

        api.reinstallPlugin('weather').subscribe();
        const reinstall = http.expectOne('/api/admin/plugins/weather/reinstall/');
        reinstall.flush(buildPluginDetail({ state: 'provisioning' }));
        expect(reinstall.request.method).toBe('POST');
        expect(reinstall.request.body).toBeNull();
    });

    it('reads what uninstalling or deleting a plugin affects', () => {
        const body = buildPluginPurgePreview();
        let answer: PluginPurgePreview | undefined;

        api.getPluginPurgePreview('weather').subscribe((preview) => (answer = preview));
        const request = http.expectOne('/api/admin/plugins/weather/purge-preview/');
        request.flush(body);

        expect(request.request.method).toBe('GET');
        expect(answer).toEqual(body);
    });

    it('deletes a plugin with the phrase exactly as typed in the body', () => {
        const deleting = buildPluginDetail({ state: 'purging', allowed_actions: [] });
        let answer: PluginDetail | undefined;

        api.purgePlugin('weather', ' purge-weather ').subscribe((plugin) => (answer = plugin));
        const request = http.expectOne('/api/admin/plugins/weather/');
        request.flush(deleting, { status: 202, statusText: 'Accepted' });

        expect(request.request.method).toBe('DELETE');
        expect(request.request.body).toEqual({ verification_phrase: ' purge-weather ' });
        expect(answer).toEqual(deleting);
    });

    it('asks the node again to remove a plugin whose removal failed', () => {
        api.retryRemoval('weather').subscribe();
        const request = http.expectOne('/api/admin/plugins/weather/retry-removal/');
        request.flush(buildPluginDetail({ state: 'purging' }), { status: 202, statusText: 'Accepted' });

        expect(request.request.method).toBe('POST');
        expect(request.request.body).toBeNull();
    });

    it("reads what deleting a grant's data removes, and deletes it with the phrase in the body", () => {
        const preview = buildGrantPurgePreview();
        let previewAnswer: PluginGrantPurgePreview | undefined;
        api.getGrantPurgePreview('weather', 5).subscribe((answer) => (previewAnswer = answer));
        const previewRequest = http.expectOne('/api/admin/plugins/weather/grants/5/purge-preview/');
        previewRequest.flush(preview);
        expect(previewRequest.request.method).toBe('GET');
        expect(previewAnswer).toEqual(preview);

        const deleting = buildPluginGrant({ state: 'purging', allowed_actions: [] });
        let grantAnswer: PluginGrant | undefined;
        api.purgeGrant('weather', 5, 'purge-weather-Acme').subscribe((grant) => (grantAnswer = grant));
        const purgeRequest = http.expectOne('/api/admin/plugins/weather/grants/5/');
        purgeRequest.flush(deleting, { status: 202, statusText: 'Accepted' });
        expect(purgeRequest.request.method).toBe('DELETE');
        expect(purgeRequest.request.body).toEqual({ verification_phrase: 'purge-weather-Acme' });
        expect(grantAnswer).toEqual(deleting);
    });

    it('lists the data removals with their filters and page', () => {
        api.listOrgRemovedJobs('weather', {
            state: 'open',
            deletedOrganizations: true,
            page: 2,
            pageSize: 20,
        }).subscribe();
        const request = http.expectOne((candidate) => candidate.url === '/api/admin/plugins/weather/org-removed-jobs/');
        request.flush({ count: 0, next: null, previous: null, results: [] });

        expect(request.request.method).toBe('GET');
        expect(request.request.params.get('state')).toBe('open');
        expect(request.request.params.get('deleted_organizations')).toBe('true');
        expect(request.request.params.get('page')).toBe('2');
        expect(request.request.params.get('page_size')).toBe('20');
    });

    it('retries and skips a data removal with empty bodies', () => {
        let answer: PluginOrgRemovedJob | undefined;
        api.retryOrgRemovedJob('weather', 31).subscribe((job) => (answer = job));
        const retry = http.expectOne('/api/admin/plugins/weather/org-removed-jobs/31/retry/');
        retry.flush(buildOrgRemovedJob(), { status: 202, statusText: 'Accepted' });
        expect(retry.request.method).toBe('POST');
        expect(retry.request.body).toBeNull();
        expect(answer).toEqual(buildOrgRemovedJob());

        api.skipOrgRemovedJob('weather', 31).subscribe();
        const skip = http.expectOne('/api/admin/plugins/weather/org-removed-jobs/31/skip/');
        skip.flush(buildOrgRemovedJob({ state: 'skipped', allowed_actions: [] }));
        expect(skip.request.method).toBe('POST');
        expect(skip.request.body).toBeNull();
    });
});
