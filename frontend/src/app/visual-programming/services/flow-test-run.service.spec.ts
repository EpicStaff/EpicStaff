import { TestBed } from '@angular/core/testing';

import { FlowTestRunRequest, FlowTestRunService } from './flow-test-run.service';

describe('FlowTestRunService', () => {
    let service: FlowTestRunService;

    beforeEach(() => {
        service = TestBed.inject(FlowTestRunService);
    });

    it('forwards a run request to subscribers', () => {
        const requests: FlowTestRunRequest[] = [];
        service.requests$.subscribe((request) => requests.push(request));

        service.request('webhook-trigger', 'node-1', { id: '104' });

        expect(requests).toEqual([{ nodeType: 'webhook-trigger', nodeId: 'node-1', payload: { id: '104' } }]);
    });

    it('tracks a starting run and the node it starts from', () => {
        service.markRunStarting('node-1');
        expect(service.isRunStarting()).toBe(true);
        expect(service.runningNodeId()).toBe('node-1');

        service.clearRunStarting();
        expect(service.isRunStarting()).toBe(false);
        expect(service.runningNodeId()).toBeNull();

        service.markRunStarting();
        expect(service.isRunStarting()).toBe(true);
        expect(service.runningNodeId()).toBeNull();
    });

    it('keeps server errors per node and clears them one node at a time', () => {
        service.setServerErrors('node-1', ['first']);
        service.setServerErrors('node-2', ['second']);

        service.clearServerErrors('node-1');

        expect(service.serverErrors().has('node-1')).toBe(false);
        expect(service.serverErrors().get('node-2')).toEqual(['second']);
    });

    it('does not replace the error map when a node has no errors to clear', () => {
        const before = service.serverErrors();

        service.clearServerErrors('unknown');

        expect(service.serverErrors()).toBe(before);
    });

    it('drops the errors of the node a test run starts from, not of other nodes', () => {
        service.setServerErrors('node-1', ['first']);
        service.setServerErrors('node-2', ['second']);

        service.markRunStarting('node-1');

        expect(service.serverErrors().has('node-1')).toBe(false);
        expect(service.serverErrors().get('node-2')).toEqual(['second']);
    });

    it('keeps server errors when the run lock is cleared (a rejected run sets them before the lock clears)', () => {
        service.markRunStarting('node-1');
        service.setServerErrors('node-1', ['rejected']);

        service.clearRunStarting();

        expect(service.serverErrors().get('node-1')).toEqual(['rejected']);
    });

    it('clears the errors of every node', () => {
        service.setServerErrors('node-1', ['first']);
        service.setServerErrors('node-2', ['second']);

        service.clearAllServerErrors();

        expect(service.serverErrors().size).toBe(0);
    });
});
