import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode, WebhookTriggerFlowReference, WebhookTriggerFlowsResponse } from '@shared/models';
import { WebhookTriggerService } from '@shared/services';
import { Observable, of, throwError } from 'rxjs';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { RUN_PERMISSION_REQUIRED_TITLE } from '../../flows/services/flow-run-permission-refusal.service';
import {
    MAX_LISTED_FLOW_NAMES,
    WebhookTriggerEditDecision,
    WebhookTriggerEditPermissionService,
} from './webhook-trigger-edit-permission.service';

const CAUTION =
    "You can't <strong>edit</strong> it because you don't have the <strong>Run</strong> permission on flows.";

function flows(...names: string[]): WebhookTriggerFlowReference[] {
    return names.map((name, index) => ({ id: index + 1, name }));
}

interface Outcome {
    decisions: WebhookTriggerEditDecision[];
    error: unknown;
}

describe('WebhookTriggerEditPermissionService', () => {
    let canRunFlows: boolean;
    let getFlows: ReturnType<typeof vi.fn>;
    let confirm: ReturnType<typeof vi.fn>;
    let service: WebhookTriggerEditPermissionService;

    beforeEach(() => {
        canRunFlows = false;
        getFlows = vi.fn();
        confirm = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                { provide: WebhookTriggerService, useValue: { getFlows } },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Flows && action === ActionCode.Run && canRunFlows,
                    },
                },
            ],
        });
        service = TestBed.inject(WebhookTriggerEditPermissionService);
    });

    function decide(response$: Observable<WebhookTriggerFlowsResponse>): Outcome {
        getFlows.mockReturnValue(response$);
        const outcome: Outcome = { decisions: [], error: undefined };
        service.decideEdit(4).subscribe({
            next: (decision) => outcome.decisions.push(decision),
            error: (error: unknown) => (outcome.error = error),
        });
        return outcome;
    }

    it('lets a user who can run flows edit without asking which flows use the trigger', () => {
        canRunFlows = true;

        expect(decide(of({ flow_count: 3, flows: [] })).decisions).toEqual(['edit']);
        expect(getFlows).not.toHaveBeenCalled();
        expect(confirm).not.toHaveBeenCalled();
    });

    it('lets a user who cannot run flows edit a trigger no flow uses', () => {
        expect(decide(of({ flow_count: 0, flows: [] })).decisions).toEqual(['edit']);
        expect(getFlows).toHaveBeenCalledExactlyOnceWith(4);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('blocks a user who cannot run flows from editing a trigger a flow uses, in an OK-only warning', () => {
        expect(decide(of({ flow_count: 1, flows: flows('Orders') })).decisions).toEqual(['blocked']);
        expect(confirm).toHaveBeenCalledExactlyOnceWith({
            title: RUN_PERMISSION_REQUIRED_TITLE,
            message: 'This webhook is part of the flow <strong>Orders</strong>.',
            caution: CAUTION,
            type: 'warning',
            hideConfirm: true,
            cancelText: 'OK',
        });
    });

    it.each<[string, WebhookTriggerFlowsResponse, string]>([
        [
            'every flow when there are several',
            { flow_count: 3, flows: flows('Billing', 'Orders', 'Support') },
            'This webhook is part of 3 flows: <strong>Billing</strong>, <strong>Orders</strong>, <strong>Support</strong>.',
        ],
        [
            `at most ${MAX_LISTED_FLOW_NAMES} flows and counts the rest`,
            { flow_count: 8, flows: flows('A', 'B', 'C', 'D', 'E', 'F', 'G', 'H') },
            'This webhook is part of 8 flows: <strong>A</strong>, <strong>B</strong>, <strong>C</strong>, ' +
                '<strong>D</strong>, <strong>E</strong> and 3 more.',
        ],
        [
            'the flows it was given and counts those the response left out',
            { flow_count: 60, flows: flows('A', 'B') },
            'This webhook is part of 60 flows: <strong>A</strong>, <strong>B</strong> and 58 more.',
        ],
        [
            'only the count of one flow whose name is hidden',
            { flow_count: 1, flows: [] },
            'This webhook is part of 1 flow.',
        ],
        [
            'only the count of flows whose names are hidden',
            { flow_count: 4, flows: [] },
            'This webhook is part of 4 flows.',
        ],
        [
            'a lone flow with its name escaped, since the dialog renders it as HTML',
            { flow_count: 1, flows: flows('<img src=x onerror=1>') },
            'This webhook is part of the flow <strong>&lt;img src=x onerror=1&gt;</strong>.',
        ],
        [
            'every listed flow with its name escaped',
            { flow_count: 2, flows: flows('<img src=x onerror=1>', 'Tom & "Jerry"') },
            'This webhook is part of 2 flows: <strong>&lt;img src=x onerror=1&gt;</strong>, ' +
                '<strong>Tom &amp; &quot;Jerry&quot;</strong>.',
        ],
    ])('names %s', (_case, usage, message) => {
        decide(of(usage));

        expect(confirm).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ message, caution: CAUTION }));
    });

    it('puts the flow count into the markup only as a number, whatever the server sent', () => {
        decide(of({ flow_count: '<img src=x onerror=1>' as unknown as number, flows: [] }));

        expect(confirm).toHaveBeenCalledExactlyOnceWith(
            expect.objectContaining({ message: 'This webhook is part of NaN flows.' })
        );
    });

    it.each<[string, unknown, WebhookTriggerEditDecision]>([
        ['403, already explained by the forbidden interceptor', new HttpErrorResponse({ status: 403 }), 'blocked'],
        ['404, since the trigger was deleted', new HttpErrorResponse({ status: 404 }), 'gone'],
        ['a network error', new HttpErrorResponse({ status: 0 }), 'edit'],
        ['500', new HttpErrorResponse({ status: 500 }), 'edit'],
        ['503', new HttpErrorResponse({ status: 503 }), 'edit'],
        ['a non-HTTP error', new Error('boom'), 'edit'],
    ])('decides on a failed check with %s, without a warning', (_case, failure, decision) => {
        expect(decide(throwError(() => failure)).decisions).toEqual([decision]);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('lets an error while showing the warning through instead of turning it into a decision', () => {
        const failure = new Error('dialog failed');
        confirm.mockImplementation(() => {
            throw failure;
        });

        const outcome = decide(of({ flow_count: 1, flows: flows('Orders') }));

        expect(outcome).toEqual({ decisions: [], error: failure });
    });
});
