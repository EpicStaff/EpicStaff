import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode, WebhookTriggerFlowReference, WebhookTriggerFlowsResponse } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import {
    WebhookTriggerEditDecision,
    WebhookTriggerEditPermissionService,
} from './webhook-trigger-edit-permission.service';

const FLOWS_URL = '/api/webhook-triggers/4/flows/';
const CAUTION =
    "You can't <strong>edit</strong> it because you don't have the <strong>Use</strong> permission on flows.";

function flows(...names: string[]): WebhookTriggerFlowReference[] {
    return names.map((name, index) => ({ id: index + 1, name }));
}

interface Outcome {
    decisions: WebhookTriggerEditDecision[];
    error: unknown;
}

describe('WebhookTriggerEditPermissionService', () => {
    let canRunFlows: boolean;
    let confirm: ReturnType<typeof vi.fn>;
    let httpMock: HttpTestingController;
    let service: WebhookTriggerEditPermissionService;

    beforeEach(() => {
        canRunFlows = false;
        confirm = vi.fn();
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                { provide: ConfirmationDialogService, useValue: { confirm } },
                {
                    provide: PermissionsService,
                    useValue: {
                        can: (resource: ResourceCode, action: ActionCode) =>
                            resource === ResourceCode.Flows && action === ActionCode.Use && canRunFlows,
                    },
                },
            ],
        });
        service = TestBed.inject(WebhookTriggerEditPermissionService);
        httpMock = TestBed.inject(HttpTestingController);
    });

    afterEach(() => httpMock.verify());

    function decide(): Outcome {
        const outcome: Outcome = { decisions: [], error: undefined };
        service.decideEdit(4).subscribe({
            next: (decision) => outcome.decisions.push(decision),
            error: (error: unknown) => (outcome.error = error),
        });
        return outcome;
    }

    function decideWithUsage(usage: WebhookTriggerFlowsResponse): Outcome {
        const outcome = decide();
        const request = httpMock.expectOne(FLOWS_URL);
        expect(request.request.method).toBe('GET');
        request.flush(usage);
        return outcome;
    }

    it('lets a user who can run flows edit without asking which flows use the trigger', () => {
        canRunFlows = true;

        expect(decide().decisions).toEqual(['edit']);
        httpMock.expectNone(FLOWS_URL);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('lets a user who cannot run flows edit a trigger no flow uses', () => {
        expect(decideWithUsage({ flow_count: 0, flows: [] }).decisions).toEqual(['edit']);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('blocks a user who cannot run flows from editing a trigger a flow uses, in an OK-only warning', () => {
        expect(decideWithUsage({ flow_count: 1, flows: flows('Orders') }).decisions).toEqual(['blocked']);
        expect(confirm).toHaveBeenCalledExactlyOnceWith({
            title: 'Use permission required',
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
            'at most 5 flows and counts the rest',
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
        decideWithUsage(usage);

        expect(confirm).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ message, caution: CAUTION }));
    });

    it('puts the flow count into the markup only as a number, whatever the server sent', () => {
        decideWithUsage({ flow_count: '<img src=x onerror=1>' as unknown as number, flows: [] });

        expect(confirm).toHaveBeenCalledExactlyOnceWith(
            expect.objectContaining({ message: 'This webhook is part of NaN flows.' })
        );
    });

    it.each<[string, number, WebhookTriggerEditDecision]>([
        ['403, already explained by the forbidden interceptor', 403, 'blocked'],
        ['404, since the trigger was deleted', 404, 'gone'],
        ['500', 500, 'edit'],
        ['503', 503, 'edit'],
    ])('decides on a failed check with %s, without a warning', (_case, status, decision) => {
        const outcome = decide();
        httpMock.expectOne(FLOWS_URL).flush({ detail: 'failed' }, { status, statusText: 'Failed' });

        expect(outcome.decisions).toEqual([decision]);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('decides to edit when the check fails on the network, without a warning', () => {
        const outcome = decide();
        httpMock.expectOne(FLOWS_URL).error(new ProgressEvent('error'));

        expect(outcome.decisions).toEqual(['edit']);
        expect(confirm).not.toHaveBeenCalled();
    });

    it('lets an error while showing the warning through instead of turning it into a decision', () => {
        const failure = new Error('dialog failed');
        confirm.mockImplementation(() => {
            throw failure;
        });

        const outcome = decideWithUsage({ flow_count: 1, flows: flows('Orders') });

        expect(outcome).toEqual({ decisions: [], error: failure });
    });
});
