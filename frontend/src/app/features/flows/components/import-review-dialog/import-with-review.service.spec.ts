import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom, Observable, of, throwError, toArray } from 'rxjs';

import {
    ImportReviewDialogCloseResult,
    ImportReviewDialogData,
    InspectResult,
    ReviewItem,
} from '../../../../core/models/review-item.model';
import { TransferJob } from '../../../../core/models/transfer-job.model';
import { TransferJobFailedError } from '../../../../core/services/transfer-jobs.service';
import { ToastMessage, ToastService } from '../../../../services/notifications';
import { storedZip } from '../../../../shared/utils/read-export-envelope.testing';
import { ImportWithReviewConfig, ImportWithReviewService } from './import-with-review.service';

const ENVELOPE = JSON.stringify({ main_entity: 'AgentDefinition', version: 1 });
const CODE_TO_REVIEW: ReviewItem = { kind: 'mcp_tool', name: 'Search', transport: 'stdio' };

const jsonExport = (): File => new File([ENVELOPE], 'agents.json', { type: 'application/json' });
const archiveExport = (): File => storedZip('agents.zip', { 'export.json': ENVELOPE });

/** Stands in for the review dialog: the user presses Import, and the dialog closes with what the import emitted. */
class ReviewDialogThatImports {
    opened = 0;

    open(
        _component: unknown,
        config: { data: ImportReviewDialogData }
    ): { closed: Observable<ImportReviewDialogCloseResult> } {
        this.opened++;
        return {
            closed: new Observable((subscriber) => {
                config.data.importFn().subscribe((result) => {
                    subscriber.next({ action: 'imported', result });
                    subscriber.complete();
                });
            }),
        };
    }
}

describe('ImportWithReviewService', () => {
    let service: ImportWithReviewService;
    let reviewDialog: ReviewDialogThatImports;
    let toasts: ToastMessage[];

    beforeEach(() => {
        reviewDialog = new ReviewDialogThatImports();
        TestBed.configureTestingModule({ providers: [{ provide: Dialog, useValue: reviewDialog }] });
        service = TestBed.inject(ImportWithReviewService);
        TestBed.inject(ToastService).toasts$.subscribe((current) => (toasts = current));
    });

    /** A config whose importers answer with their own name, so the result tells which one imported the file. */
    function config(options: { archive: boolean; reviewItems?: ReviewItem[] }): ImportWithReviewConfig {
        const inspection: InspectResult = { review_items: options.reviewItems ?? [] };
        return {
            entityLabel: 'agent',
            entityLabelPlural: 'agents',
            inspect: () => of(inspection),
            importFile: () => of('import'),
            importArchive: options.archive ? () => of('import job') : undefined,
            accept: '.json,.zip',
        };
    }

    const importedBy = (file: File, importConfig: ImportWithReviewConfig): Promise<unknown[]> =>
        firstValueFrom(service.importFile(file, importConfig).pipe(toArray()));

    it.each([
        { file: 'a .zip archive', make: archiveExport, archive: true, expected: 'import job' },
        { file: 'a plain .json export', make: jsonExport, archive: true, expected: 'import' },
        { file: 'a .zip archive, with no archive importer', make: archiveExport, archive: false, expected: 'import' },
    ])('imports $file through "$expected"', async ({ make, archive, expected }) => {
        expect(await importedBy(make(), config({ archive }))).toEqual([expected]);
        expect(reviewDialog.opened).toBe(0);
    });

    it('imports a reviewed .zip archive through the archive importer too', async () => {
        const result = await importedBy(archiveExport(), config({ archive: true, reviewItems: [CODE_TO_REVIEW] }));

        expect(reviewDialog.opened).toBe(1);
        expect(result).toEqual(['import job']);
    });

    it("shows the failed import job's reason and emits nothing", async () => {
        const importConfig: ImportWithReviewConfig = {
            ...config({ archive: true }),
            importArchive: () =>
                throwError(
                    () =>
                        new TransferJobFailedError({
                            kind: 'import',
                            status: 'failed',
                            error: { code: 'invalid_archive', message: 'The archive is missing an agent.' },
                        } as TransferJob)
                ),
        };

        expect(await importedBy(archiveExport(), importConfig)).toEqual([]);
        expect(toasts.map((toast) => [toast.type, toast.message])).toEqual([
            ['error', 'The archive is missing an agent.'],
        ]);
    });
});
