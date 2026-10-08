import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { GraphDto } from '../../features/flows/models/graph.model';
import { FlowService } from './flow.service';

const PYTHON_CODE = { id: 5, code: 'def main(**kwargs): pass', entrypoint: 'main', libraries: [] };

function graphWith(...webhookNodes: { id: number; python_code: typeof PYTHON_CODE }[]): GraphDto {
    return { webhook_trigger_node_list: webhookNodes } as unknown as GraphDto;
}

describe('FlowService saved webhook python code', () => {
    let flowService: FlowService;

    beforeEach(() => {
        flowService = TestBed.inject(FlowService);
    });

    it('knows no stored graph while unbound', () => {
        expect(flowService.hasSavedGraph()).toBe(false);
        expect(flowService.savedWebhookPythonCode(21)).toBeNull();
    });

    it('returns the stored code of a webhook node by its backend id', () => {
        flowService.bindSavedGraph(signal(graphWith({ id: 21, python_code: PYTHON_CODE })));

        expect(flowService.hasSavedGraph()).toBe(true);
        expect(flowService.savedWebhookPythonCode(21)).toEqual(PYTHON_CODE);
        expect(flowService.savedWebhookPythonCode(22)).toBeNull();
        expect(flowService.savedWebhookPythonCode(null)).toBeNull();
    });

    it('follows the bound signal instead of copying it', () => {
        const storedGraph = signal<GraphDto | null>(graphWith());
        flowService.bindSavedGraph(storedGraph);
        expect(flowService.savedWebhookPythonCode(21)).toBeNull();

        storedGraph.set(graphWith({ id: 21, python_code: PYTHON_CODE }));
        expect(flowService.savedWebhookPythonCode(21)).toEqual(PYTHON_CODE);

        storedGraph.set(null);
        expect(flowService.hasSavedGraph()).toBe(false);
    });

    it('forgets the graph when unbound', () => {
        flowService.bindSavedGraph(signal(graphWith({ id: 21, python_code: PYTHON_CODE })));

        flowService.bindSavedGraph(null);

        expect(flowService.savedWebhookPythonCode(21)).toBeNull();
    });
});
