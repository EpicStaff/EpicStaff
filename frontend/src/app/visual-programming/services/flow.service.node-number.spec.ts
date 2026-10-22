import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { FlowModel } from '../core/models/flow.model';
import { NodeModel } from '../core/models/node.model';
import { FlowService } from './flow.service';

function flowNumbered(...nodeNumbers: (number | undefined)[]): FlowModel {
    const nodes = nodeNumbers.map(
        (nodeNumber, index) => ({ id: `node-${index}`, type: NodeType.PYTHON, nodeNumber }) as NodeModel
    );
    return { nodes, connections: [] };
}

describe('FlowService node numbers', () => {
    let flowService: FlowService;

    beforeEach(() => {
        flowService = TestBed.inject(FlowService);
    });

    it('continues after the graph counter when it is above every number on the canvas', () => {
        flowService.setFlow(flowNumbered(1, 5));
        flowService.setNodeNumberFloor(12);

        expect(flowService.getNextNodeNumber()).toBe(13);
        expect(flowService.getNextNodeNumber()).toBe(14);
    });

    it('continues after the highest number on the canvas when it is above the graph counter', () => {
        flowService.setFlow(flowNumbered(3, 20));
        flowService.setNodeNumberFloor(12);

        expect(flowService.getNextNodeNumber()).toBe(21);
    });

    it('starts at 1 on an empty canvas of a graph that never issued a number', () => {
        flowService.setFlow(flowNumbered());
        flowService.setNodeNumberFloor(0);

        expect(flowService.getNextNodeNumber()).toBe(1);
    });

    it('keeps the graph counter when the canvas is replaced (undo, save, reload)', () => {
        flowService.setNodeNumberFloor(12);
        flowService.setFlow(flowNumbered(2));

        expect(flowService.getNextNodeNumber()).toBe(13);
    });

    it('takes a lower counter from the next loaded graph', () => {
        flowService.setNodeNumberFloor(12);
        flowService.setFlow(flowNumbered(1));
        flowService.setNodeNumberFloor(3);

        expect(flowService.getNextNodeNumber()).toBe(4);
    });

    it('ignores nodes without a number', () => {
        flowService.setFlow(flowNumbered(undefined, 4, undefined));

        expect(flowService.getNextNodeNumber()).toBe(5);
    });
});
