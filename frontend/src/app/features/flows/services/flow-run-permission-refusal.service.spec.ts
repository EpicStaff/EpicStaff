import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, of, throwError } from 'rxjs';

import {
    FLOW_WITH_TRIGGER_NODES_REQUIRES_RUN_PERMISSION,
    FlowRunPermissionRefusalService,
    RUN_PERMISSION_REQUIRED_TITLE,
    RunPermissionRefusalOperation,
} from './flow-run-permission-refusal.service';

const REFUSAL = new HttpErrorResponse({
    status: 403,
    statusText: 'Forbidden',
    error: {
        status_code: 403,
        code: FLOW_WITH_TRIGGER_NODES_REQUIRES_RUN_PERMISSION,
        message: 'This flow contains trigger nodes (webhook, Telegram, schedule).',
    },
});

interface Outcome {
    values: unknown[];
    error: unknown;
    completed: boolean;
}

describe('FlowRunPermissionRefusalService', () => {
    let confirm: ReturnType<typeof vi.fn>;
    let service: FlowRunPermissionRefusalService;

    beforeEach(() => {
        confirm = vi.fn();
        TestBed.configureTestingModule({
            providers: [{ provide: ConfirmationDialogService, useValue: { confirm } }],
        });
        service = TestBed.inject(FlowRunPermissionRefusalService);
    });

    function run(source: Observable<unknown>): Outcome {
        const outcome: Outcome = { values: [], error: undefined, completed: false };
        source.pipe(service.catchRefusal('copy')).subscribe({
            next: (value) => outcome.values.push(value),
            error: (error: unknown) => (outcome.error = error),
            complete: () => (outcome.completed = true),
        });
        return outcome;
    }

    it.each<[RunPermissionRefusalOperation, string, string]>([
        ['copy', 'This flow', '<strong>Copying</strong> it'],
        ['import', 'This file', '<strong>Importing</strong> it'],
        ['partialImport', 'This file', '<strong>Importing</strong> it'],
        ['restore', 'This version', '<strong>Restoring</strong> it'],
        ['createFromVersion', 'This version', '<strong>Creating a flow</strong> from it'],
        ['unpack', 'This subflow', '<strong>Unpacking</strong> it'],
    ])(
        'explains a refused %s in an OK-only warning with its consequence as the caution',
        (operation, source, action) => {
            service.showRefusal(operation);

            expect(confirm).toHaveBeenCalledExactlyOnceWith({
                title: RUN_PERMISSION_REQUIRED_TITLE,
                message: `${source} contains trigger nodes (Webhook, Telegram, Schedule).`,
                caution: `${action} requires the <strong>Run</strong> permission on flows.`,
                type: 'warning',
                hideConfirm: true,
                cancelText: 'OK',
            });
        }
    );

    it("explains the backend's refusal for the given operation and completes without emitting or erroring", () => {
        const outcome = run(throwError(() => REFUSAL));

        expect(confirm).toHaveBeenCalledExactlyOnceWith(
            expect.objectContaining({
                message: 'This flow contains trigger nodes (Webhook, Telegram, Schedule).',
                caution: '<strong>Copying</strong> it requires the <strong>Run</strong> permission on flows.',
            })
        );
        expect(outcome).toEqual({ values: [], error: undefined, completed: true });
    });

    it.each([
        [
            'the bulk-save trigger node 403',
            new HttpErrorResponse({ status: 403, error: { code: 'trigger_nodes_require_run_permission' } }),
        ],
        ['another 403', new HttpErrorResponse({ status: 403, error: { code: 'permission_denied' } })],
        ['the refusal code on another status', new HttpErrorResponse({ status: 400, error: REFUSAL.error })],
        ['a server error', new HttpErrorResponse({ status: 500 })],
    ])('passes %s through unchanged, without a dialog', (_case, failure) => {
        const outcome = run(throwError(() => failure));

        expect(confirm).not.toHaveBeenCalled();
        expect(outcome.error).toBe(failure);
    });

    it('lets a successful result through', () => {
        expect(run(of('copied')).values).toEqual(['copied']);
        expect(confirm).not.toHaveBeenCalled();
    });
});
