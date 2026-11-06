import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { BulkDeleteResponse, SystemOneConfig } from '@shared/models';

import { ConfigService } from '../../../services/config';
import { SystemOneConfigStorageService } from './system-one-config-storage.service';

const NO_AUTHORSHIP = {
    created_by: null,
    created_at: '2026-10-01T10:00:00Z',
    last_edited_by: null,
    last_edited_at: null,
};

function config(id: number, name: string): SystemOneConfig {
    return {
        id,
        custom_name: name,
        provider: 'typesafe',
        model_name: 'jev-1.14.0',
        api_key_secret_id: 5,
        llm_config: null,
        ...NO_AUTHORSHIP,
    };
}

function bulkResponse(overrides: Partial<BulkDeleteResponse>): BulkDeleteResponse {
    return {
        dry_run: false,
        deleted_count: 0,
        deleted_ids: [],
        deletable_ids: [],
        not_found_ids: [],
        skipped: [],
        usage: {},
        ...overrides,
    };
}

describe('SystemOneConfigStorageService', () => {
    let storage: SystemOneConfigStorageService;
    let http: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } },
            ],
        });
        storage = TestBed.inject(SystemOneConfigStorageService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => http.verify());

    function load(configs: SystemOneConfig[]): void {
        storage.getAllConfigs().subscribe();
        http.expectOne((request) => request.url === '/api/system-one-configs/').flush({ results: configs });
    }

    it('sends one request for two loads made before the response', () => {
        storage.getAllConfigs().subscribe();
        storage.getAllConfigs().subscribe();

        http.expectOne((request) => request.url === '/api/system-one-configs/').flush({ results: [config(1, 'a')] });

        expect(storage.configs()).toEqual([config(1, 'a')]);
    });

    it('serves a second load from the cache and refetches when forced', () => {
        load([config(1, 'a')]);

        storage.getAllConfigs().subscribe();
        http.expectNone('/api/system-one-configs/');

        storage.getAllConfigs(true).subscribe();
        http.expectOne((request) => request.url === '/api/system-one-configs/').flush({
            results: [config(1, 'a'), config(2, 'b')],
        });

        expect(storage.configs().map((item) => item.id)).toEqual([1, 2]);
    });

    it('puts a created config first', () => {
        load([config(1, 'a')]);

        storage
            .createConfig({
                custom_name: 'b',
                provider: 'typesafe',
                model_name: 'jev-1.14.0',
                api_key_secret_id: 5,
                llm_config: null,
            })
            .subscribe();
        http.expectOne({ method: 'POST', url: '/api/system-one-configs/' }).flush(config(2, 'b'));

        expect(storage.configs().map((item) => item.id)).toEqual([2, 1]);
    });

    it('patches an updated config in place', () => {
        load([config(1, 'a'), config(2, 'b')]);

        storage.updateConfig(2, { custom_name: 'renamed' }).subscribe();
        const request = http.expectOne({ method: 'PATCH', url: '/api/system-one-configs/2/' });
        request.flush(config(2, 'renamed'));

        expect(request.request.body).toEqual({ custom_name: 'renamed' });
        expect(storage.configs().map((item) => item.custom_name)).toEqual(['a', 'renamed']);
    });

    it('drops deleted and not-found ids after a bulk delete', () => {
        load([config(1, 'a'), config(2, 'b'), config(3, 'c')]);

        storage.bulkDelete([1, 2, 3]).subscribe();
        http.expectOne({ method: 'POST', url: '/api/system-one-configs/bulk-delete/' }).flush(
            bulkResponse({ deleted_count: 1, deleted_ids: [1], not_found_ids: [2] })
        );

        expect(storage.configs().map((item) => item.id)).toEqual([3]);
    });

    it('asks for a dry run when previewing a bulk delete, and keeps the cache', () => {
        load([config(1, 'a')]);

        storage.previewBulkDelete([1]).subscribe();
        const request = http.expectOne((req) => req.url === '/api/system-one-configs/bulk-delete/');
        request.flush(bulkResponse({ dry_run: true, deletable_ids: [1] }));

        expect(request.request.params.get('dry_run')).toBe('true');
        expect(storage.configs()).toHaveLength(1);
    });

    it('empties the cache on clear and loads again afterwards', () => {
        load([config(1, 'a')]);

        storage.clear();
        expect(storage.configs()).toEqual([]);

        storage.getAllConfigs().subscribe();
        http.expectOne((request) => request.url === '/api/system-one-configs/').flush({ results: [] });
    });
});
