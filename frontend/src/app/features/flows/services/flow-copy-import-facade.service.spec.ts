import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, of, throwError } from 'rxjs';

import { ImportFlowRequestOptions, ImportResult } from '../../../core/models/import-result.model';
import { ImportExportService } from '../../../core/services/import-export.service';
import { GraphDto } from '../models/graph.model';
import { FlowCopyImportFacadeService } from './flow-copy-import-facade.service';
import { FLOW_WITH_TRIGGER_NODES_REQUIRES_RUN_PERMISSION } from './flow-run-permission-refusal.service';
import { FlowsStorageService } from './flows-storage.service';

const COPY = { id: 12, name: 'Orders #2' } as GraphDto;
const IMPORT_RESULT: ImportResult = {
    Flow: { total: 1, created: { count: 1, items: [] }, reused: { count: 0, items: [] } },
};
const SETTINGS: ImportFlowRequestOptions = { preserveUuids: false, replaceExisting: true, importLabels: true };
const FILE = new File(['{}'], 'flow.json', { type: 'application/json' });
const REFUSAL = new HttpErrorResponse({
    status: 403,
    error: { status_code: 403, code: FLOW_WITH_TRIGGER_NODES_REQUIRES_RUN_PERMISSION, message: 'Refused.' },
});
const FAILURE = new HttpErrorResponse({ status: 500, statusText: 'Server Error' });

interface Outcome {
    values: unknown[];
    error: unknown;
}

function collect(source: Observable<unknown>): Outcome {
    const outcome: Outcome = { values: [], error: undefined };
    source.subscribe({
        next: (value) => outcome.values.push(value),
        error: (error: unknown) => (outcome.error = error),
    });
    return outcome;
}

describe('FlowCopyImportFacadeService', () => {
    let copyFlow: ReturnType<typeof vi.fn>;
    let importFlow: ReturnType<typeof vi.fn>;
    let partialImport: ReturnType<typeof vi.fn>;
    let confirm: ReturnType<typeof vi.fn>;
    let service: FlowCopyImportFacadeService;

    beforeEach(() => {
        copyFlow = vi.fn(() => of(COPY));
        importFlow = vi.fn(() => of(IMPORT_RESULT));
        partialImport = vi.fn(() => of({}));
        confirm = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                { provide: FlowsStorageService, useValue: { copyFlow } },
                { provide: ImportExportService, useValue: { importFlow, partialImport } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
            ],
        });
        service = TestBed.inject(FlowCopyImportFacadeService);
    });

    const operations: [
        string,
        () => ReturnType<typeof vi.fn>,
        (facade: FlowCopyImportFacadeService) => Observable<unknown>,
        string,
    ][] = [
        ['copy', () => copyFlow, (facade) => facade.copyFlow(7, 'Orders'), 'This flow contains'],
        ['import', () => importFlow, (facade) => facade.importFlow(FILE, SETTINGS), 'This file contains'],
        ['partial import', () => partialImport, (facade) => facade.partialImport(5, FILE), 'This file contains'],
    ];

    it('passes the arguments through and returns the result', () => {
        expect(collect(service.copyFlow(7, 'Orders')).values).toEqual([COPY]);
        expect(copyFlow).toHaveBeenCalledExactlyOnceWith(7, 'Orders');
        expect(collect(service.importFlow(FILE, SETTINGS)).values).toEqual([IMPORT_RESULT]);
        expect(importFlow).toHaveBeenCalledExactlyOnceWith(FILE, SETTINGS);
        expect(collect(service.partialImport(5, FILE)).values).toEqual([{}]);
        expect(partialImport).toHaveBeenCalledExactlyOnceWith(5, FILE);
        expect(confirm).not.toHaveBeenCalled();
    });

    it.each(operations)('explains a %s refused over trigger nodes and emits nothing', (_name, request, call, lead) => {
        request().mockReturnValue(throwError(() => REFUSAL));

        const outcome = collect(call(service));

        expect(confirm).toHaveBeenCalledExactlyOnceWith(
            expect.objectContaining({ message: expect.stringContaining(lead) })
        );
        expect(outcome).toEqual({ values: [], error: undefined });
    });

    it.each(operations)('passes any other %s failure to the caller', (_name, request, call) => {
        request().mockReturnValue(throwError(() => FAILURE));

        expect(collect(call(service)).error).toBe(FAILURE);
        expect(confirm).not.toHaveBeenCalled();
    });
});
