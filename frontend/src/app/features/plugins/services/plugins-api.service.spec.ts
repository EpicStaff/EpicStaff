import { HttpEventType, HttpHeaders, HttpResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { PluginDetail, PluginInstallEvent } from '../models/plugin.model';
import { PluginsApiService, toPluginInstallEvent } from './plugins-api.service';

const PLUGIN = { id: 7, name: 'Chat Bot', status: 'preparing' } as PluginDetail;

describe('toPluginInstallEvent', () => {
    it('maps upload progress to a rounded 0–100 percentage', () => {
        expect(toPluginInstallEvent({ type: HttpEventType.UploadProgress, loaded: 1, total: 3 })).toEqual({
            kind: 'progress',
            percent: 33,
        });
        expect(toPluginInstallEvent({ type: HttpEventType.UploadProgress, loaded: 200, total: 200 })).toEqual({
            kind: 'progress',
            percent: 100,
        });
    });

    it('reports 0 when the total size is unknown and never exceeds 100', () => {
        expect(toPluginInstallEvent({ type: HttpEventType.UploadProgress, loaded: 50 })).toEqual({
            kind: 'progress',
            percent: 0,
        });
        expect(toPluginInstallEvent({ type: HttpEventType.UploadProgress, loaded: 300, total: 200 })).toEqual({
            kind: 'progress',
            percent: 100,
        });
    });

    it('maps the final response to the installed plugin', () => {
        expect(toPluginInstallEvent(new HttpResponse({ status: 201, body: PLUGIN }))).toEqual({
            kind: 'done',
            plugin: PLUGIN,
        });
    });

    it('ignores every other event', () => {
        expect(toPluginInstallEvent({ type: HttpEventType.Sent })).toBeNull();
        expect(toPluginInstallEvent({ type: HttpEventType.DownloadProgress, loaded: 10 })).toBeNull();
    });
});

describe('PluginsApiService', () => {
    let service: PluginsApiService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(PluginsApiService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('installs with multipart file + secrets JSON and emits progress, then the plugin', () => {
        const file = new File(['zip-bytes'], 'chat-bot-plugin.zip', { type: 'application/zip' });
        const events: PluginInstallEvent[] = [];

        service.install(file, { OPENAI_API_KEY: 'sk-test' }).subscribe((event) => events.push(event));

        const request = httpMock.expectOne('/api/plugins/install/');
        expect(request.request.method).toBe('POST');
        expect(request.request.reportProgress).toBe(true);
        const body = request.request.body as FormData;
        expect(body.get('file')).toBe(file);
        expect(JSON.parse(body.get('secrets') as string)).toEqual({ OPENAI_API_KEY: 'sk-test' });

        request.event({ type: HttpEventType.Sent });
        request.event({ type: HttpEventType.UploadProgress, loaded: 25, total: 100 });
        request.event({ type: HttpEventType.UploadProgress, loaded: 100, total: 100 });
        request.flush(PLUGIN, { status: 201, statusText: 'Created', headers: new HttpHeaders() });

        expect(events).toEqual([
            { kind: 'progress', percent: 25 },
            { kind: 'progress', percent: 100 },
            { kind: 'done', plugin: PLUGIN },
        ]);
    });

    it('omits secrets when the plugin declares no slots', () => {
        service.install(new File(['zip'], 'plugin.zip'), {}).subscribe();

        const request = httpMock.expectOne('/api/plugins/install/');
        expect((request.request.body as FormData).has('secrets')).toBe(false);
        request.flush(PLUGIN);
    });

    it('inspects with a multipart file only', () => {
        const file = new File(['zip'], 'plugin.zip');
        service.inspect(file).subscribe();

        const request = httpMock.expectOne('/api/plugins/inspect/');
        expect(request.request.method).toBe('POST');
        const body = request.request.body as FormData;
        expect(body.get('file')).toBe(file);
        expect(body.has('secrets')).toBe(false);
        request.flush({});
    });

    it('calls the lifecycle endpoints with the database id', () => {
        service.list().subscribe();
        httpMock.expectOne({ method: 'GET', url: '/api/plugins/' }).flush([]);

        service.get(7).subscribe();
        httpMock.expectOne({ method: 'GET', url: '/api/plugins/7/' }).flush(PLUGIN);

        service.suspend(7).subscribe();
        httpMock.expectOne({ method: 'POST', url: '/api/plugins/7/suspend/' }).flush(PLUGIN);

        service.resume(7).subscribe();
        httpMock.expectOne({ method: 'POST', url: '/api/plugins/7/resume/' }).flush(PLUGIN);

        service.retry(7).subscribe();
        httpMock.expectOne({ method: 'POST', url: '/api/plugins/7/retry/' }).flush(PLUGIN);

        service.updateSecrets(7, { secrets: { OPENAI_API_KEY: 'sk-new' }, retry_indexing: true }).subscribe();
        const secrets = httpMock.expectOne({ method: 'POST', url: '/api/plugins/7/secrets/' });
        expect(secrets.request.body).toEqual({ secrets: { OPENAI_API_KEY: 'sk-new' }, retry_indexing: true });
        secrets.flush(PLUGIN);

        service.getDeletePreview(7).subscribe();
        httpMock.expectOne({ method: 'GET', url: '/api/plugins/7/delete-preview/' }).flush({});

        service.delete(7).subscribe();
        httpMock.expectOne({ method: 'DELETE', url: '/api/plugins/7/' }).flush(null, { status: 204, statusText: '' });

        service.createUiSession(7).subscribe();
        httpMock.expectOne({ method: 'POST', url: '/api/plugins/7/ui-session/' }).flush({});
    });
});
