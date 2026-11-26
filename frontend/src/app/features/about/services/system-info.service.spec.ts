import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { SystemInfo } from '../models/system-info.model';
import { SystemInfoService } from './system-info.service';

const INFO: SystemInfo = {
    version: 'v1.6.0',
    git_ref: 'main',
    git_sha: '3f9c2a1e8b7d4c5a6e9f0123456789abcdef0123',
    commit_date: '2026-11-24T08:00:00Z',
    import_version: 6,
    features: { chats: true, plugins: false, session_audit: true, user_audit: false },
};

describe('SystemInfoService', () => {
    let service: SystemInfoService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        service = TestBed.inject(SystemInfoService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => http.verify());

    it('asks the backend once and keeps what it answers', () => {
        service.load();
        service.load();

        http.expectOne('/api/system-info/').flush(INFO);
        http.expectOne('/version.json').flush({ git_sha: INFO.git_sha, commit_date: INFO.commit_date });

        expect(service.systemInfo()).toEqual(INFO);
        expect(service.frontendBuild()).toEqual({ gitSha: INFO.git_sha, commitDate: INFO.commit_date });
    });

    it('keeps no system info when the request fails', () => {
        service.load();

        http.expectOne('/api/system-info/').flush('boom', { status: 500, statusText: 'Server Error' });
        http.expectOne('/version.json').flush({ git_sha: '', commit_date: '' });

        expect(service.systemInfo()).toBeNull();
    });

    it('knows no frontend commit when version.json is missing', () => {
        service.load();

        http.expectOne('/api/system-info/').flush(INFO);
        http.expectOne('/version.json').flush('', { status: 404, statusText: 'Not Found' });

        expect(service.frontendBuild()).toEqual({ gitSha: null, commitDate: null });
    });

    it('knows no frontend commit when version.json holds empty strings', () => {
        service.load();

        http.expectOne('/api/system-info/').flush(INFO);
        http.expectOne('/version.json').flush({ git_sha: '', commit_date: '' });

        expect(service.frontendBuild()).toEqual({ gitSha: null, commitDate: null });
    });
});
