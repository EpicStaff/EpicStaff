import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode, WebhookTriggerFlowsResponse } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { ConfigService } from '../../../services/config';
import {
    WebhookTriggerEditDecision,
    WebhookTriggerEditPermissionService,
} from './webhook-trigger-edit-permission.service';

const FLOWS_URL = '/api/webhook-triggers/4/flows/';

describe('WebhookTriggerEditPermissionService', () => {
    let canRunFlows: boolean;
    let httpMock: HttpTestingController;
    let service: WebhookTriggerEditPermissionService;

    beforeEach(() => {
        canRunFlows = false;
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
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

    function decide(): WebhookTriggerEditDecision[] {
        const decisions: WebhookTriggerEditDecision[] = [];
        service.decideEdit(4).subscribe((decision) => decisions.push(decision));
        return decisions;
    }

    it('lets a user who can run flows edit without asking which flows use the trigger', () => {
        canRunFlows = true;

        expect(decide()).toEqual(['edit']);
        httpMock.expectNone(FLOWS_URL);
    });

    it.each<[string, WebhookTriggerFlowsResponse, WebhookTriggerEditDecision]>([
        ['edit a trigger no flow uses', { flow_count: 0, flows: [] }, 'edit'],
        ['only view a trigger a flow uses', { flow_count: 1, flows: [{ id: 1, name: 'Orders' }] }, 'view'],
        ['only view a trigger flows use whose names are hidden', { flow_count: 3, flows: [] }, 'view'],
    ])('lets a user who cannot run flows %s', (_case, usage, decision) => {
        const decisions = decide();
        const request = httpMock.expectOne(FLOWS_URL);
        expect(request.request.method).toBe('GET');
        request.flush(usage);

        expect(decisions).toEqual([decision]);
    });

    it.each<[string, number, WebhookTriggerEditDecision]>([
        ['403, already explained by the forbidden interceptor', 403, 'explained'],
        ['404, since the trigger was deleted', 404, 'gone'],
        ['500', 500, 'edit'],
        ['503', 503, 'edit'],
    ])('decides on a failed check with %s', (_case, status, decision) => {
        const decisions = decide();
        httpMock.expectOne(FLOWS_URL).flush({ detail: 'failed' }, { status, statusText: 'Failed' });

        expect(decisions).toEqual([decision]);
    });

    it('decides to edit when the check fails on the network', () => {
        const decisions = decide();
        httpMock.expectOne(FLOWS_URL).error(new ProgressEvent('error'));

        expect(decisions).toEqual(['edit']);
    });
});
