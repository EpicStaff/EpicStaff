import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ExportResult } from '@shared/models';

import { ConfigService } from '../../services/config';
import { ImportExportService, PartialExportRequest } from './import-export.service';

describe('ImportExportService export header', () => {
    let service: ImportExportService;
    let httpMock: HttpTestingController;

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
            ],
        });
        service = TestBed.inject(ImportExportService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function exportWithHeader(header: string | null): { result: ExportResult; blob: Blob } {
        const results: ExportResult[] = [];
        service.partialExport(5, {} as PartialExportRequest).subscribe((result) => results.push(result));
        const headers: Record<string, string> = header === null ? {} : { 'X-Export-Excluded': header };
        const blob = new Blob(['{}']);
        httpMock.expectOne('/api/graphs/5/partial-export/').flush(blob, { headers });
        return { result: results[0], blob };
    }

    it('returns the blob and the excluded entities from the header', () => {
        const header =
            '[{"type":"AgentDefinition","count":3,"names":["A","B","C"]},{"type":"Flow","count":1,"names":[]}]';

        const { result, blob } = exportWithHeader(header);

        expect(result.blob).toBe(blob);
        expect(result.excluded).toEqual([
            { type: 'AgentDefinition', count: 3, names: ['A', 'B', 'C'] },
            { type: 'Flow', count: 1, names: [] },
        ]);
    });

    it.each([
        ['absent', null],
        ['invalid JSON', 'not-json'],
        ['not an array', '{"type":"Flow","count":1,"names":[]}'],
        ['an entry with the wrong shape', '[{"type":"Flow","count":"1","names":[]}]'],
        ['names that are not strings', '[{"type":"Flow","count":1,"names":[1]}]'],
    ])('returns no excluded entities when the header is %s', (_label, header) => {
        expect(exportWithHeader(header).result.excluded).toEqual([]);
    });
});
