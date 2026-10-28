import { Dialog } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { BulkDeleteGroup, BulkDeleteOutcome, BulkDeleteResponse, BulkDeleteTarget } from '@shared/models';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { ToastService } from '../../../services/notifications';
import { BulkDeleteService } from './bulk-delete.service';

interface MockTarget {
    previewBulkDelete: ReturnType<typeof vi.fn>;
    bulkDelete: ReturnType<typeof vi.fn>;
    removeFromCache: ReturnType<typeof vi.fn>;
}

function createTarget(): MockTarget {
    return {
        previewBulkDelete: vi.fn(),
        bulkDelete: vi.fn(),
        removeFromCache: vi.fn(),
    };
}

function asTarget(mock: MockTarget): BulkDeleteTarget {
    return mock as unknown as BulkDeleteTarget;
}

function buildGroup(
    mock: MockTarget,
    items: { id: number; name: string }[],
    label = { singular: 'flow', plural: 'flows' }
): BulkDeleteGroup {
    return { target: asTarget(mock), label, items };
}

function buildResponse(overrides: Partial<BulkDeleteResponse> = {}): BulkDeleteResponse {
    return {
        dry_run: true,
        deleted_count: 0,
        deleted_ids: [],
        deletable_ids: [],
        not_found_ids: [],
        skipped: [],
        usage: {},
        ...overrides,
    };
}

describe('BulkDeleteService', () => {
    let dialog: { open: ReturnType<typeof vi.fn> };
    let toast: {
        success: ReturnType<typeof vi.fn>;
        error: ReturnType<typeof vi.fn>;
        warning: ReturnType<typeof vi.fn>;
    };
    let service: BulkDeleteService;

    function configure(): void {
        TestBed.configureTestingModule({
            providers: [
                { provide: Dialog, useValue: dialog as unknown as Dialog },
                { provide: ToastService, useValue: toast as unknown as ToastService },
            ],
        });
        service = TestBed.inject(BulkDeleteService);
    }

    function mockDialogResult(result: boolean): void {
        dialog.open.mockReturnValue({ closed: of(result) });
    }

    beforeEach(() => {
        dialog = { open: vi.fn() };
        toast = { success: vi.fn(), error: vi.fn(), warning: vi.fn() };
    });

    it('aborts with a warning and runs no preview when a group has more than 500 items', () => {
        configure();
        const target = createTarget();
        const items = Array.from({ length: 501 }, (_, i) => ({ id: i + 1, name: `item-${i + 1}` }));

        const emissions: BulkDeleteOutcome[][] = [];
        service.run([buildGroup(target, items)]).subscribe((outcomes) => emissions.push(outcomes));

        expect(toast.warning).toHaveBeenCalledWith('You can delete up to 500 items at once.');
        expect(target.previewBulkDelete).not.toHaveBeenCalled();
        expect(dialog.open).not.toHaveBeenCalled();
        expect(emissions).toEqual([]);
    });

    it('does not call bulkDelete when the dialog is cancelled', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
        mockDialogResult(false);

        const emissions: BulkDeleteOutcome[][] = [];
        service.run([buildGroup(target, [{ id: 1, name: 'Alpha' }])]).subscribe((outcomes) => emissions.push(outcomes));

        expect(dialog.open).toHaveBeenCalled();
        expect(target.bulkDelete).not.toHaveBeenCalled();
        expect(emissions).toEqual([]);
    });

    it('calls bulkDelete with deletable_ids only when confirmed', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(
            of(buildResponse({ deletable_ids: [1, 2], skipped: [{ id: 3, reason: 'in_use_restricted' }] }))
        );
        target.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [1, 2], deleted_count: 2 })));
        mockDialogResult(true);

        const items = [
            { id: 1, name: 'Alpha' },
            { id: 2, name: 'Beta' },
            { id: 3, name: 'Gamma' },
        ];
        service.run([buildGroup(target, items)]).subscribe();

        expect(target.bulkDelete).toHaveBeenCalledWith([1, 2]);
    });

    it('shows the dialog but never calls bulkDelete when nothing is deletable', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(
            of(buildResponse({ deletable_ids: [], skipped: [{ id: 1, reason: 'protected' }] }))
        );
        // Even if something downstream returned true, the D === 0 guard must still apply.
        mockDialogResult(true);

        service.run([buildGroup(target, [{ id: 1, name: 'Alpha' }])]).subscribe();

        expect(dialog.open).toHaveBeenCalled();
        expect(target.bulkDelete).not.toHaveBeenCalled();
    });

    it('removes not_found_ids from the cache after the preview resolves', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1], not_found_ids: [9] })));
        mockDialogResult(false);

        const items = [
            { id: 1, name: 'Alpha' },
            { id: 9, name: 'Stale' },
        ];
        service.run([buildGroup(target, items)]).subscribe();

        expect(target.removeFromCache).toHaveBeenCalledWith([9]);
    });

    it('emits both outcomes and shows a warning toast when one group errors and another succeeds', () => {
        configure();
        const targetA = createTarget();
        const targetB = createTarget();
        targetA.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
        targetB.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [2] })));
        targetA.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [1], deleted_count: 1 })));
        const httpError = new HttpErrorResponse({ status: 500 });
        targetB.bulkDelete.mockReturnValue(throwError(() => httpError));
        mockDialogResult(true);

        const groupA = buildGroup(targetA, [{ id: 1, name: 'Alpha' }], { singular: 'flow', plural: 'flows' });
        const groupB = buildGroup(targetB, [{ id: 2, name: 'Beta' }], { singular: 'agent', plural: 'agents' });

        const emissions: BulkDeleteOutcome[][] = [];
        service.run([groupA, groupB]).subscribe((outcomes) => emissions.push(outcomes));

        expect(emissions).toHaveLength(1);
        expect(emissions[0]).toHaveLength(2);
        expect(emissions[0].find((o) => o.group === groupA)?.response?.deleted_count).toBe(1);
        expect(emissions[0].find((o) => o.group === groupB)?.error).toBe(httpError);
        expect(toast.warning).toHaveBeenCalledWith("Deleted 1 of 2 items. 1 couldn't be deleted.");
    });

    describe('recycle bin', () => {
        const recycleBin = { retentionDays: 30 };

        function recycleGroup(mock: MockTarget, ids: number[]): BulkDeleteGroup {
            return {
                ...buildGroup(
                    mock,
                    ids.map((id) => ({ id, name: `Flow ${id}` }))
                ),
                recycleBin,
            };
        }

        it('says the flows moved to the recycle bin when every deleted group is a recycle-bin group', () => {
            configure();
            const target = createTarget();
            target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1, 2] })));
            target.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [1, 2], deleted_count: 2 })));
            mockDialogResult(true);

            service.run([recycleGroup(target, [1, 2])]).subscribe();

            expect(toast.success).toHaveBeenCalledWith('Moved 2 flows to the recycle bin.');
        });

        it('uses the singular noun for one flow', () => {
            configure();
            const target = createTarget();
            target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
            target.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [1], deleted_count: 1 })));
            mockDialogResult(true);

            service.run([recycleGroup(target, [1])]).subscribe();

            expect(toast.success).toHaveBeenCalledWith('Moved 1 flow to the recycle bin.');
        });

        it('pluralizes by the moved count when one of two requested flows was already gone', () => {
            configure();
            const target = createTarget();
            target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1, 2] })));
            target.bulkDelete.mockReturnValue(
                of(buildResponse({ deleted_ids: [1], deleted_count: 1, not_found_ids: [2] }))
            );
            mockDialogResult(true);

            service.run([recycleGroup(target, [1, 2])]).subscribe();

            expect(toast.success).toHaveBeenCalledWith('Moved 1 flow to the recycle bin.');
        });

        it('keeps the partial-success warning consistent with the recycle-bin wording', () => {
            configure();
            const target = createTarget();
            target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1, 2, 3] })));
            target.bulkDelete.mockReturnValue(
                of(
                    buildResponse({
                        deleted_ids: [1],
                        deleted_count: 1,
                        skipped: [
                            { id: 2, reason: 'in_use_restricted' },
                            { id: 3, reason: 'in_use_restricted' },
                        ],
                    })
                )
            );
            mockDialogResult(true);

            service.run([recycleGroup(target, [1, 2, 3])]).subscribe();

            expect(toast.warning).toHaveBeenCalledWith("Moved 1 of 3 flows to the recycle bin. 2 couldn't be moved.");
        });

        it('keeps "Already deleted." when the flow was gone before the real delete', () => {
            configure();
            const target = createTarget();
            target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
            target.bulkDelete.mockReturnValue(of(buildResponse({ not_found_ids: [1] })));
            mockDialogResult(true);

            service.run([recycleGroup(target, [1])]).subscribe();

            expect(toast.success).toHaveBeenCalledWith('Already deleted.');
        });

        it('reports a failed recycle-bin delete without claiming a permanent delete', () => {
            configure();
            const target = createTarget();
            target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
            target.bulkDelete.mockReturnValue(throwError(() => new Error('boom')));
            mockDialogResult(true);

            service.run([recycleGroup(target, [1])]).subscribe();

            expect(toast.error).toHaveBeenCalledWith('Failed to move to the recycle bin.');
        });

        it('says "Deleted" when a deleted group is not a recycle-bin group', () => {
            configure();
            const recycleTarget = createTarget();
            const permanentTarget = createTarget();
            recycleTarget.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
            permanentTarget.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [2] })));
            recycleTarget.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [1], deleted_count: 1 })));
            permanentTarget.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [2], deleted_count: 1 })));
            mockDialogResult(true);

            service
                .run([recycleGroup(recycleTarget, [1]), buildGroup(permanentTarget, [{ id: 2, name: 'Config' }])])
                .subscribe();

            expect(toast.success).toHaveBeenCalledWith('Deleted 2 items.');
        });

        it('ignores a recycle-bin group that had nothing to delete when wording the toast', () => {
            configure();
            const recycleTarget = createTarget();
            const permanentTarget = createTarget();
            recycleTarget.previewBulkDelete.mockReturnValue(
                of(buildResponse({ skipped: [{ id: 1, reason: 'protected' }] }))
            );
            permanentTarget.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [2] })));
            permanentTarget.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [2], deleted_count: 1 })));
            mockDialogResult(true);

            service
                .run([recycleGroup(recycleTarget, [1]), buildGroup(permanentTarget, [{ id: 2, name: 'Config' }])])
                .subscribe();

            expect(toast.success).toHaveBeenCalledWith('Deleted 1 item.');
        });
    });

    it('shows a success toast naming the singular/plural label when everything is deleted', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1, 2] })));
        target.bulkDelete.mockReturnValue(of(buildResponse({ deleted_ids: [1, 2], deleted_count: 2 })));
        mockDialogResult(true);

        const items = [
            { id: 1, name: 'Alpha' },
            { id: 2, name: 'Beta' },
        ];
        service.run([buildGroup(target, items)]).subscribe();

        expect(toast.success).toHaveBeenCalledWith('Deleted 2 flows.');
    });

    it('pluralizes by the deleted count when one of two requested flows was already gone', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1, 2] })));
        target.bulkDelete.mockReturnValue(
            of(buildResponse({ deleted_ids: [1], deleted_count: 1, not_found_ids: [2] }))
        );
        mockDialogResult(true);

        const items = [
            { id: 1, name: 'Alpha' },
            { id: 2, name: 'Beta' },
        ];
        service.run([buildGroup(target, items)]).subscribe();

        expect(toast.success).toHaveBeenCalledWith('Deleted 1 flow.');
    });

    it('shows a success "Already deleted." toast when the real delete reports the item as not_found', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
        target.bulkDelete.mockReturnValue(of(buildResponse({ not_found_ids: [1], deleted_count: 0 })));
        mockDialogResult(true);

        service.run([buildGroup(target, [{ id: 1, name: 'Alpha' }])]).subscribe();

        expect(toast.success).toHaveBeenCalledWith('Already deleted.');
        expect(toast.warning).not.toHaveBeenCalled();
        expect(toast.error).not.toHaveBeenCalled();
    });

    it('shows a partial-success warning toast with the remaining count', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1, 2, 3] })));
        target.bulkDelete.mockReturnValue(
            of(
                buildResponse({
                    deleted_ids: [1],
                    deleted_count: 1,
                    skipped: [
                        { id: 2, reason: 'in_use_restricted' },
                        { id: 3, reason: 'in_use_restricted' },
                    ],
                })
            )
        );
        mockDialogResult(true);

        const items = [
            { id: 1, name: 'Alpha' },
            { id: 2, name: 'Beta' },
            { id: 3, name: 'Gamma' },
        ];
        service.run([buildGroup(target, items)]).subscribe();

        expect(toast.warning).toHaveBeenCalledWith("Deleted 1 of 3 flows. 2 couldn't be deleted.");
    });

    it('shows an error toast with the extracted message when the single delete request fails', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
        const httpError = new HttpErrorResponse({ status: 500, error: { message: 'Database is unavailable' } });
        target.bulkDelete.mockReturnValue(throwError(() => httpError));
        mockDialogResult(true);

        service.run([buildGroup(target, [{ id: 1, name: 'Alpha' }])]).subscribe();

        expect(toast.error).toHaveBeenCalledWith('Database is unavailable');
    });

    it('shows no toast when the only delete error is a 403 (the forbidden interceptor already showed one)', () => {
        configure();
        const target = createTarget();
        target.previewBulkDelete.mockReturnValue(of(buildResponse({ deletable_ids: [1] })));
        const httpError = new HttpErrorResponse({ status: 403 });
        target.bulkDelete.mockReturnValue(throwError(() => httpError));
        mockDialogResult(true);

        service.run([buildGroup(target, [{ id: 1, name: 'Alpha' }])]).subscribe();

        expect(toast.error).not.toHaveBeenCalled();
        expect(toast.warning).not.toHaveBeenCalled();
        expect(toast.success).not.toHaveBeenCalled();
    });

    it('shows no toast when the preview request fails with a 403', () => {
        configure();
        const target = createTarget();
        const httpError = new HttpErrorResponse({ status: 403 });
        target.previewBulkDelete.mockReturnValue(throwError(() => httpError));

        service.run([buildGroup(target, [{ id: 1, name: 'Alpha' }])]).subscribe();

        expect(toast.error).not.toHaveBeenCalled();
        expect(toast.warning).not.toHaveBeenCalled();
        expect(dialog.open).not.toHaveBeenCalled();
    });

    it('shows an error toast when the preview request fails with a non-403 error', () => {
        configure();
        const target = createTarget();
        const httpError = new HttpErrorResponse({ status: 500, error: { message: 'Server exploded' } });
        target.previewBulkDelete.mockReturnValue(throwError(() => httpError));

        service.run([buildGroup(target, [{ id: 1, name: 'Alpha' }])]).subscribe();

        expect(toast.error).toHaveBeenCalledWith('Server exploded');
        expect(dialog.open).not.toHaveBeenCalled();
    });

    it('drops empty groups and emits nothing when none are left', () => {
        configure();
        const target = createTarget();

        const emissions: BulkDeleteOutcome[][] = [];
        service.run([buildGroup(target, [])]).subscribe((outcomes) => emissions.push(outcomes));

        expect(target.previewBulkDelete).not.toHaveBeenCalled();
        expect(dialog.open).not.toHaveBeenCalled();
        expect(emissions).toEqual([]);
    });
});
