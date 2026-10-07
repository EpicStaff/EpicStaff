import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { FlowsApiService } from './flows-api.service';

describe('FlowsApiService', () => {
    const graphLightUrl = '/api/graph-light/';

    let service: FlowsApiService;
    let httpMock: HttpTestingController;

    const expectFirstPage = (): TestRequest =>
        httpMock.expectOne((request) => request.url === graphLightUrl && !request.params.has('offset'));

    const expectPageAtOffset = (offset: number): TestRequest =>
        httpMock.expectOne((request) => request.params.get('offset') === offset.toString());

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(FlowsApiService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('loads every page of light flows and returns them merged and sorted by id descending', () => {
        let result: unknown;
        service.getGraphsLight({ label_id: 7 }).subscribe((flows) => (result = flows));

        expectFirstPage().flush({
            count: 3,
            next: '/api/graph-light/?label_id=7&limit=2&offset=2',
            previous: null,
            results: [{ id: 10 }, { id: 30 }],
        });

        const secondRequest = expectPageAtOffset(2);
        expect(secondRequest.request.url).toBe(graphLightUrl);
        expect(secondRequest.request.params.get('limit')).toBe('2');
        expect(secondRequest.request.params.get('label_id')).toBe('7');
        secondRequest.flush({ count: 3, next: null, previous: graphLightUrl, results: [{ id: 20 }] });

        expect(result).toEqual([{ id: 30 }, { id: 20 }, { id: 10 }]);
    });

    it('requests the remaining pages concurrently with the right offsets and preserved filters', () => {
        let result: { id: number }[] | undefined;
        service.getGraphsLight({ label_id: 7, no_label: true }).subscribe((flows) => (result = flows));

        expectFirstPage().flush({
            count: 120,
            next: '/api/graph-light/?label_id=7&limit=50&no_label=true&offset=50',
            previous: null,
            results: Array.from({ length: 50 }, (_, index) => ({ id: index + 1 })),
        });

        const secondRequest = expectPageAtOffset(50);
        const thirdRequest = expectPageAtOffset(100);
        for (const pendingRequest of [secondRequest, thirdRequest]) {
            expect(pendingRequest.request.url).toBe(graphLightUrl);
            expect(pendingRequest.request.params.get('limit')).toBe('50');
            expect(pendingRequest.request.params.get('label_id')).toBe('7');
            expect(pendingRequest.request.params.get('no_label')).toBe('true');
        }

        thirdRequest.flush({
            count: 120,
            next: null,
            previous: graphLightUrl,
            results: Array.from({ length: 20 }, (_, index) => ({ id: index + 101 })),
        });
        expect(result).toBeUndefined();
        secondRequest.flush({
            count: 120,
            next: graphLightUrl,
            previous: graphLightUrl,
            results: Array.from({ length: 50 }, (_, index) => ({ id: index + 51 })),
        });

        expect(result?.length).toBe(120);
        expect(result?.[0]).toEqual({ id: 120 });
        expect(result?.[119]).toEqual({ id: 1 });
    });

    it('requests the remaining pages at the relative url when next points at another host and scheme', () => {
        service.getGraphsLight().subscribe();

        expectFirstPage().flush({
            count: 2,
            next: 'http://internal-host:8000/api/graph-light/?limit=1&offset=1',
            previous: null,
            results: [{ id: 1 }],
        });

        const secondRequest = expectPageAtOffset(1);
        expect(secondRequest.request.url).toBe(graphLightUrl);
        expect(secondRequest.request.params.get('limit')).toBe('1');
        secondRequest.flush({ count: 2, next: null, previous: null, results: [{ id: 2 }] });
    });

    it('falls back to the first page size when next has no limit', () => {
        service.getGraphsLight().subscribe();

        expectFirstPage().flush({
            count: 3,
            next: '/api/graph-light/?offset=2',
            previous: null,
            results: [{ id: 1 }, { id: 2 }],
        });

        expectPageAtOffset(2).flush({ count: 3, next: null, previous: null, results: [{ id: 3 }] });
    });

    it('keeps only the first occurrence of a flow that appears on two pages', () => {
        let result: unknown;
        service.getEpicChatEnabledFlows().subscribe((flows) => (result = flows));

        expectFirstPage().flush({
            count: 4,
            next: '/api/graph-light/?epicchat_enabled=true&limit=2&offset=2',
            previous: null,
            results: [
                { id: 1, name: 'first page' },
                { id: 2, name: 'first page' },
            ],
        });
        expectPageAtOffset(2).flush({
            count: 4,
            next: null,
            previous: graphLightUrl,
            results: [
                { id: 2, name: 'second page' },
                { id: 3, name: 'second page' },
            ],
        });

        expect(result).toEqual([
            { id: 1, name: 'first page' },
            { id: 2, name: 'first page' },
            { id: 3, name: 'second page' },
        ]);
    });

    it('errors without emitting partial results when a remaining page fails', () => {
        let result: unknown;
        let error: unknown;
        service.getGraphsLight().subscribe({ next: (flows) => (result = flows), error: (caught) => (error = caught) });

        expectFirstPage().flush({
            count: 3,
            next: '/api/graph-light/?limit=1&offset=1',
            previous: null,
            results: [{ id: 1 }],
        });
        const thirdRequest = expectPageAtOffset(2);
        expectPageAtOffset(1).flush('Server error', { status: 500, statusText: 'Internal Server Error' });

        expect(result).toBeUndefined();
        expect(error).toBeDefined();
        expect(thirdRequest.cancelled).toBe(true);
    });

    it('cancels the pending remaining pages when unsubscribed', () => {
        const subscription = service.getGraphsLight().subscribe();

        expectFirstPage().flush({
            count: 3,
            next: '/api/graph-light/?limit=1&offset=1',
            previous: null,
            results: [{ id: 1 }],
        });
        const secondRequest = expectPageAtOffset(1);
        const thirdRequest = expectPageAtOffset(2);

        subscription.unsubscribe();

        expect(secondRequest.cancelled).toBe(true);
        expect(thirdRequest.cancelled).toBe(true);
    });

    it('makes a single request when the first page has no next page', () => {
        let result: unknown;
        service.getGraphsLight().subscribe((flows) => (result = flows));

        expectFirstPage().flush({ count: 2, next: null, previous: null, results: [{ id: 1 }, { id: 2 }] });

        expect(result).toEqual([{ id: 2 }, { id: 1 }]);
    });

    it('sends the label filter params on the first request', () => {
        service.getGraphsLight({ label_id: 7, no_label: true }).subscribe();

        const request = expectFirstPage();
        expect(request.request.params.get('label_id')).toBe('7');
        expect(request.request.params.get('no_label')).toBe('true');
        request.flush({ count: 0, next: null, previous: null, results: [] });
    });

    it('loads every page of epic chat enabled flows without re-sorting them', () => {
        let result: unknown;
        service.getEpicChatEnabledFlows().subscribe((flows) => (result = flows));

        const firstRequest = expectFirstPage();
        expect(firstRequest.request.params.get('epicchat_enabled')).toBe('true');
        firstRequest.flush({
            count: 3,
            next: 'https://example.com/api/graph-light/?epicchat_enabled=true&limit=2&offset=2',
            previous: null,
            results: [{ id: 1 }, { id: 3 }],
        });

        const secondRequest = expectPageAtOffset(2);
        expect(secondRequest.request.url).toBe(graphLightUrl);
        expect(secondRequest.request.params.get('epicchat_enabled')).toBe('true');
        secondRequest.flush({ count: 3, next: null, previous: graphLightUrl, results: [{ id: 2 }] });

        expect(result).toEqual([{ id: 1 }, { id: 3 }, { id: 2 }]);
    });
});
