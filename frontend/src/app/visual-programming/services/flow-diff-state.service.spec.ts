import { TestBed } from '@angular/core/testing';

import { FlowDiffCanvasState } from '../utils/diff';
import { FlowDiffStateService } from './flow-diff-state.service';

const DIFF_CANVAS: FlowDiffCanvasState = {
    nodes: new Map([
        ['node-added', { status: 'added' }],
        ['node-unchanged', { status: 'unchanged' }],
    ]),
    connections: new Map([['connection-deleted', 'deleted']]),
    versionOnlyPortIds: new Set(['table_decision-out-yes']),
};

describe('FlowDiffStateService', () => {
    let service: FlowDiffStateService;

    beforeEach(() => {
        service = TestBed.inject(FlowDiffStateService);
    });

    it('has no statuses until a diff canvas is shown, as in the live editor', () => {
        expect(service.isActive()).toBe(false);
        expect(service.nodeStatus('node-added')).toBeNull();
        expect(service.hasMissingReferences('node-unchanged')).toBe(false);
        expect(service.connectionStatus('connection-deleted')).toBeNull();
        expect(service.isVersionOnlyPort('table_decision-out-yes')).toBe(false);
    });

    it('gives the status of each node and connection of the diff canvas shown', () => {
        service.setState(DIFF_CANVAS);

        expect(service.isActive()).toBe(true);
        expect(service.nodeStatus('node-added')).toBe('added');
        expect(service.nodeStatus('node-unchanged')).toBe('unchanged');
        expect(service.connectionStatus('connection-deleted')).toBe('deleted');
        expect(service.isVersionOnlyPort('table_decision-out-yes')).toBe(true);
    });

    it('has no status for an id that is not on the diff canvas', () => {
        service.setState(DIFF_CANVAS);

        expect(service.nodeStatus('other-node')).toBeNull();
        expect(service.connectionStatus('other-connection')).toBeNull();
        expect(service.isVersionOnlyPort('table_decision-out-no')).toBe(false);
    });

    it('marks missing references on a plain canvas too, without turning the diff on', () => {
        service.setMissingReferenceNodeIds(new Set(['plain-node']));

        expect(service.hasMissingReferences('plain-node')).toBe(true);
        expect(service.hasMissingReferences('other-node')).toBe(false);
        expect(service.isActive()).toBe(false);
        expect(service.nodeStatus('plain-node')).toBeNull();
    });

    it('drops the statuses when a plain canvas is shown', () => {
        service.setState(DIFF_CANVAS);
        service.setState(null);

        expect(service.isActive()).toBe(false);
        expect(service.nodeStatus('node-added')).toBeNull();
        expect(service.connectionStatus('connection-deleted')).toBeNull();
        expect(service.isVersionOnlyPort('table_decision-out-yes')).toBe(false);
    });
});
