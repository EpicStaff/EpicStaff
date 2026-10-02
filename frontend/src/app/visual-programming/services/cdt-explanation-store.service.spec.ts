import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { CdtExplanation } from '../core/models/classification-decision-table.model';
import { NodeModel } from '../core/models/node.model';
import { CdtExplanationCacheService } from './cdt-explanation-cache.service';
import { CdtExplanationStoreService } from './cdt-explanation-store.service';
import { FlowService } from './flow.service';
import { FlowReadOnlyService } from './flow-readonly.service';
import { SidePanelService } from './side-panel.service';

const STORED: CdtExplanation = { text: 'Stored on the node', fingerprint: 'stored', generatedBy: 'model' };
const CACHED: CdtExplanation = { text: 'Only in the cache', fingerprint: 'cached', generatedBy: 'model' };
const GENERATED: CdtExplanation = { text: 'Freshly generated', fingerprint: 'fresh', generatedBy: 'model' };

function tableNode(): NodeModel {
    return {
        id: 'node-1',
        type: NodeType.CLASSIFICATION_TABLE,
        explanations: { stored: STORED },
    } as unknown as NodeModel;
}

function setUp({ isReadOnly, isPreview }: { isReadOnly: boolean; isPreview: boolean }) {
    const flowService = { nodes: signal<NodeModel[]>([tableNode()]), updateNode: vi.fn() };
    const sidePanelService = { requestNodeAutosave: vi.fn() };
    const cache = {
        get: vi.fn((key: string) => (key === '42|cached' ? CACHED : null)),
        set: vi.fn(),
    };

    TestBed.configureTestingModule({
        providers: [
            CdtExplanationStoreService,
            { provide: FlowService, useValue: flowService },
            { provide: SidePanelService, useValue: sidePanelService },
            { provide: CdtExplanationCacheService, useValue: cache },
            { provide: FlowReadOnlyService, useValue: { isReadOnly: signal(isReadOnly), isPreview } },
        ],
    });

    const scope = TestBed.inject(CdtExplanationStoreService).forNode({
        nodeId: 'node-1',
        backendId: 42,
        liveStepKeys: new Set(['stored', 'cached', 'fresh']),
    });

    return { scope, flowService, sidePanelService, cache };
}

describe('CdtExplanationStoreService', () => {
    it('writes a generated explanation to the node and asks for an autosave in an editable editor', () => {
        const { scope, flowService, sidePanelService, cache } = setUp({ isReadOnly: false, isPreview: false });

        scope.set('fresh', GENERATED);

        expect(cache.set).toHaveBeenCalledWith('42|fresh', GENERATED);
        expect(flowService.updateNode).toHaveBeenCalledTimes(1);
        expect(flowService.updateNode.mock.calls[0][0].explanations).toEqual({ fresh: GENERATED, stored: STORED });
        expect(sidePanelService.requestNodeAutosave).toHaveBeenCalledTimes(1);
    });

    it('writes nothing — node, autosave or cache — in a read-only editor', () => {
        const { scope, flowService, sidePanelService, cache } = setUp({ isReadOnly: true, isPreview: false });

        scope.set('fresh', GENERATED);

        expect(flowService.updateNode).not.toHaveBeenCalled();
        expect(sidePanelService.requestNodeAutosave).not.toHaveBeenCalled();
        expect(cache.set).not.toHaveBeenCalled();
    });

    it('still reads stored and cached explanations for a viewer', () => {
        const { scope } = setUp({ isReadOnly: true, isPreview: false });

        expect(scope.get('stored')).toEqual(STORED);
        expect(scope.get('cached')).toEqual(CACHED);
    });

    it("reads only the version's stored explanations in a preview, never the live editor's cache", () => {
        const { scope, cache } = setUp({ isReadOnly: true, isPreview: true });

        expect(scope.get('stored')).toEqual(STORED);
        expect(scope.get('cached')).toBeNull();
        expect(cache.get).not.toHaveBeenCalled();
    });
});
