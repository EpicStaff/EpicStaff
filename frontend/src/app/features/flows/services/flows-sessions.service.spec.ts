import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ConfigService } from '../../../services/config';
import { GraphSessionService, SessionRunType } from './flows-sessions.service';

describe('GraphSessionService run type filter', () => {
    let service: GraphSessionService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(GraphSessionService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    const cases: { runType: SessionRunType[] | undefined; expected: string | null }[] = [
        { runType: ['test'], expected: 'true' },
        { runType: ['live'], expected: 'false' },
        { runType: ['test', 'live'], expected: null },
        { runType: [], expected: null },
        { runType: undefined, expected: null },
    ];

    for (const { runType, expected } of cases) {
        it(`sends is_test_run=${expected} for ${JSON.stringify(runType)} on the flow sessions list`, () => {
            service.getSessionsByGraphId(3, false, 10, 0, ['all'], null, false, null, [], null, runType).subscribe();

            const request = httpMock.expectOne((req) => req.url === '/api/sessions/');
            expect(request.request.params.get('is_test_run')).toBe(expected);
            expect(request.request.params.get('graph_id')).toBe('3');
            request.flush({ count: 0, results: [] });
        });

        it(`sends is_test_run=${expected} for ${JSON.stringify(runType)} on the global sessions list`, () => {
            service.getGlobalSessions(10, 0, ['all'], '-created_at', [], [], false, null, null, runType).subscribe();

            const request = httpMock.expectOne((req) => req.url === '/api/sessions/');
            expect(request.request.params.get('is_test_run')).toBe(expected);
            request.flush({ count: 0, results: [] });
        });
    }
});
