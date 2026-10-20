import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable } from 'rxjs';

import { ImportFlowRequestOptions, ImportResult } from '../../../core/models/import-result.model';
import { ConfigService } from '../../../services/config';
import { GraphDto } from '../models/graph.model';
import { FlowCopyImportFacadeService } from './flow-copy-import-facade.service';
import { FlowsStorageService } from './flows-storage.service';

const COPY = { id: 12, name: 'Orders #2' } as GraphDto;
const IMPORT_RESULT: ImportResult = {
    Flow: { total: 1, created: { count: 1, items: [] }, reused: { count: 0, items: [] } },
};
const SETTINGS: ImportFlowRequestOptions = { preserveUuids: false, replaceExisting: true, importLabels: true };
const FILE = new File(['{}'], 'flow.json', { type: 'application/json' });
const REFUSAL_BODY = {
    status_code: 403,
    code: 'flow_with_trigger_nodes_requires_use_permission',
    message: 'This flow contains trigger nodes.',
};

interface Outcome {
    values: unknown[];
    error: unknown;
    completed: boolean;
}

function collect(source: Observable<unknown>): Outcome {
    const outcome: Outcome = { values: [], error: undefined, completed: false };
    source.subscribe({
        next: (value) => outcome.values.push(value),
        error: (error: unknown) => (outcome.error = error),
        complete: () => (outcome.completed = true),
    });
    return outcome;
}

describe('FlowCopyImportFacadeService', () => {
    let confirm: ReturnType<typeof vi.fn>;
    let httpMock: HttpTestingController;
    let service: FlowCopyImportFacadeService;

    beforeEach(() => {
        confirm = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: ConfirmationDialogService, useValue: { confirm } },
            ],
        });
        service = TestBed.inject(FlowCopyImportFacadeService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    it('copies the flow under the given name and adds the copy to the flows list', () => {
        const outcome = collect(service.copyFlow(7, 'Orders'));

        const request = httpMock.expectOne('/api/graphs/7/copy/');
        expect(request.request.method).toBe('POST');
        expect(request.request.body).toEqual({ name: 'Orders' });
        request.flush(COPY);

        expect(outcome.values).toEqual([COPY]);
        expect(TestBed.inject(FlowsStorageService).flows()).toEqual([COPY]);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('uploads the file with the import settings and returns the import summary', () => {
        const outcome = collect(service.importFlow(FILE, SETTINGS));

        const request = httpMock.expectOne('/api/graphs/import/');
        expect(request.request.method).toBe('POST');
        const body = request.request.body as FormData;
        expect(body.get('file')).toBe(FILE);
        expect(body.get('preserve_uuids')).toBe('false');
        expect(body.get('replace_existing')).toBe('true');
        expect(body.get('import_labels')).toBe('true');
        request.flush(IMPORT_RESULT);

        expect(outcome.values).toEqual([IMPORT_RESULT]);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('uploads the file into the open flow for a partial import', () => {
        const outcome = collect(service.partialImport(5, FILE));

        const request = httpMock.expectOne('/api/graphs/5/partial-import/');
        expect(request.request.method).toBe('POST');
        expect((request.request.body as FormData).get('file')).toBe(FILE);
        request.flush({ created: 2 });

        expect(outcome.values).toEqual([{ created: 2 }]);
        expect(confirm).not.toHaveBeenCalled();
    });

    const operations: [string, (facade: FlowCopyImportFacadeService) => Observable<unknown>, string, string, string][] =
        [
            [
                'copy',
                (facade) => facade.copyFlow(7, 'Orders'),
                '/api/graphs/7/copy/',
                'This flow contains trigger nodes (Webhook, Telegram, Schedule).',
                '<strong>Copying</strong> it requires the <strong>Use</strong> permission on flows.',
            ],
            [
                'import',
                (facade) => facade.importFlow(FILE, SETTINGS),
                '/api/graphs/import/',
                'This file contains trigger nodes (Webhook, Telegram, Schedule).',
                '<strong>Importing</strong> it requires the <strong>Use</strong> permission on flows.',
            ],
            [
                'partial import',
                (facade) => facade.partialImport(5, FILE),
                '/api/graphs/5/partial-import/',
                'This file contains trigger nodes (Webhook, Telegram, Schedule).',
                '<strong>Importing</strong> it requires the <strong>Use</strong> permission on flows.',
            ],
        ];

    it.each(operations)(
        'explains a %s refused over trigger nodes and completes without a value or an error',
        (_name, call, url, message, caution) => {
            const outcome = collect(call(service));

            httpMock.expectOne(url).flush(REFUSAL_BODY, { status: 403, statusText: 'Forbidden' });

            expect(confirm).toHaveBeenCalledExactlyOnceWith({
                title: 'Use permission required',
                message,
                caution,
                type: 'warning',
                hideConfirm: true,
                cancelText: 'OK',
            });
            expect(outcome).toEqual({ values: [], error: undefined, completed: true });
        }
    );

    it.each(operations)('passes any other %s failure to the caller, without a dialog', (_name, call, url) => {
        const outcome = collect(call(service));

        httpMock.expectOne(url).flush({ detail: 'boom' }, { status: 500, statusText: 'Server Error' });

        expect(outcome.error).toBeInstanceOf(HttpErrorResponse);
        expect((outcome.error as HttpErrorResponse).status).toBe(500);
        expect(confirm).not.toHaveBeenCalled();
    });
});
