import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { Observable, of, throwError } from 'rxjs';

import {
    FlowUsePermissionRefusalService,
    UsePermissionAction,
    UsePermissionRefusalOperation,
} from './flow-use-permission-refusal.service';

const REFUSAL = new HttpErrorResponse({
    status: 403,
    statusText: 'Forbidden',
    error: {
        status_code: 403,
        code: 'flow_with_trigger_nodes_requires_use_permission',
        message: 'This flow contains trigger nodes (webhook, Telegram, schedule).',
    },
});

interface Outcome {
    values: unknown[];
    error: unknown;
    completed: boolean;
}

describe('FlowUsePermissionRefusalService', () => {
    let confirm: ReturnType<typeof vi.fn>;
    let service: FlowUsePermissionRefusalService;

    beforeEach(() => {
        confirm = vi.fn();
        TestBed.configureTestingModule({
            providers: [{ provide: ConfirmationDialogService, useValue: { confirm } }],
        });
        service = TestBed.inject(FlowUsePermissionRefusalService);
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

    it.each<[UsePermissionRefusalOperation, string, string]>([
        [
            'copy',
            'This flow contains trigger nodes (Webhook, Telegram, Schedule).',
            '<strong>Copying</strong> it requires the <strong>Use</strong> permission on flows.',
        ],
        [
            'import',
            'This file contains trigger nodes (Webhook, Telegram, Schedule).',
            '<strong>Importing</strong> it requires the <strong>Use</strong> permission on flows.',
        ],
        [
            'partialImport',
            'This file contains trigger nodes (Webhook, Telegram, Schedule).',
            '<strong>Importing</strong> it requires the <strong>Use</strong> permission on flows.',
        ],
        [
            'restore',
            'This version contains trigger nodes (Webhook, Telegram, Schedule).',
            '<strong>Restoring</strong> it requires the <strong>Use</strong> permission on flows.',
        ],
        [
            'createFromVersion',
            'This version contains trigger nodes (Webhook, Telegram, Schedule).',
            '<strong>Creating a flow</strong> from it requires the <strong>Use</strong> permission on flows.',
        ],
        [
            'unpack',
            'This subflow contains trigger nodes (Webhook, Telegram, Schedule).',
            '<strong>Unpacking</strong> it requires the <strong>Use</strong> permission on flows.',
        ],
    ])(
        'explains a refused %s in an OK-only warning with its consequence as the caution',
        (operation, message, caution) => {
            service.showRefusal(operation);

            expect(confirm).toHaveBeenCalledExactlyOnceWith({
                title: 'Use permission required',
                message,
                caution,
                type: 'warning',
                hideConfirm: true,
                cancelText: 'OK',
            });
        }
    );

    it.each<[UsePermissionAction, string]>([
        ['run', '<strong>Running</strong> this flow requires the <strong>Use</strong> permission on flows.'],
        [
            'getCurl',
            '<strong>Getting the cURL command</strong> for this flow requires the <strong>Use</strong> permission on flows.',
        ],
        [
            'stopSession',
            '<strong>Stopping</strong> a session of this flow requires the <strong>Use</strong> permission on flows.',
        ],
    ])('says in an OK-only warning that %s needs the Use permission', (action, message) => {
        service.showActionRefusal(action);

        expect(confirm).toHaveBeenCalledExactlyOnceWith({
            title: 'Use permission required',
            message,
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
    });

    it("explains the backend's refusal for the given operation and completes without emitting or erroring", () => {
        const outcome = run(throwError(() => REFUSAL));

        expect(confirm).toHaveBeenCalledExactlyOnceWith(
            expect.objectContaining({
                message: 'This flow contains trigger nodes (Webhook, Telegram, Schedule).',
                caution: '<strong>Copying</strong> it requires the <strong>Use</strong> permission on flows.',
            })
        );
        expect(outcome).toEqual({ values: [], error: undefined, completed: true });
    });

    function secretsRefusal(message: string): HttpErrorResponse {
        return new HttpErrorResponse({
            status: 403,
            error: { status_code: 403, code: 'code_with_secrets_requires_secrets_use_permission', message },
        });
    }

    it.each<[UsePermissionRefusalOperation, string, string]>([
        [
            'copy',
            'This flow contains code that reads secrets.',
            '<strong>Copying</strong> it requires the <strong>Use</strong> permission on secrets.',
        ],
        [
            'restore',
            'This version contains code that reads secrets.',
            '<strong>Restoring</strong> it requires the <strong>Use</strong> permission on secrets.',
        ],
        [
            'createFromVersion',
            'This version contains code that reads secrets.',
            '<strong>Creating a flow</strong> from it requires the <strong>Use</strong> permission on secrets.',
        ],
        [
            'import',
            'This file contains code that reads secrets.',
            '<strong>Importing</strong> it requires the <strong>Use</strong> permission on secrets.',
        ],
    ])('explains a %s refused over code that reads secrets in an OK-only warning', (operation, message, caution) => {
        service.showSecretsRefusal(operation);

        expect(confirm).toHaveBeenCalledExactlyOnceWith({
            title: 'Use permission required',
            message,
            caution,
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
    });

    it("explains the backend's refusal over code that reads secrets for the given operation and completes", () => {
        const outcome = run(throwError(() => secretsRefusal('This contains code that reads secrets.')));

        expect(confirm).toHaveBeenCalledExactlyOnceWith(
            expect.objectContaining({
                message: 'This flow contains code that reads secrets.',
                caution: '<strong>Copying</strong> it requires the <strong>Use</strong> permission on secrets.',
            })
        );
        expect(outcome).toEqual({ values: [], error: undefined, completed: true });
    });

    it.each([
        [
            'the secrets refusal code on another status',
            new HttpErrorResponse({ status: 400, error: secretsRefusal('Refused').error }),
        ],
        [
            'the bulk-save trigger node 403',
            new HttpErrorResponse({ status: 403, error: { code: 'trigger_nodes_require_use_permission' } }),
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
