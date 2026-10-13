import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NodeType } from '@shared/models';

import { CDT_EXPLANATION_LIMITS } from '../core/constants/cdt-explanation-limits';
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
    const sidePanelService = { requestCdtExplanationsSave: vi.fn() };
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
        retainedStepKeys: new Set(['stored', 'cached', 'fresh']),
    });

    return { scope, flowService, sidePanelService, cache };
}

describe('CdtExplanationStoreService', () => {
    it('writes a generated explanation to the node and asks for its explanations to be persisted in an editable editor', () => {
        const { scope, flowService, sidePanelService, cache } = setUp({ isReadOnly: false, isPreview: false });

        expect(scope.set('fresh', GENERATED)).toBe(true);

        expect(cache.set).toHaveBeenCalledWith('42|fresh', GENERATED);
        expect(flowService.updateNode).toHaveBeenCalledTimes(1);
        expect(flowService.updateNode.mock.calls[0][0].explanations).toEqual({ fresh: GENERATED, stored: STORED });
        expect(sidePanelService.requestCdtExplanationsSave).toHaveBeenCalledExactlyOnceWith('node-1');
    });

    it('says so and keeps an explanation too long to store nowhere — node, persist or cache', () => {
        const { scope, flowService, sidePanelService, cache } = setUp({ isReadOnly: false, isPreview: false });

        const kept = scope.set('fresh', { ...GENERATED, text: 't'.repeat(CDT_EXPLANATION_LIMITS.maxTextLength + 1) });

        expect(kept).toBe(false);
        expect(flowService.updateNode).not.toHaveBeenCalled();
        expect(sidePanelService.requestCdtExplanationsSave).not.toHaveBeenCalled();
        expect(cache.set).not.toHaveBeenCalled();
    });

    it('refuses one that would push an explanation already kept out of the stored map', () => {
        const { flowService } = setUp({ isReadOnly: false, isPreview: false });
        const big = { ...GENERATED, text: 't'.repeat(CDT_EXPLANATION_LIMITS.maxTextLength) };
        const crowded = Object.fromEntries(
            Array.from({ length: 52 }, (_, index) => [`stored-${String(index).padStart(2, '0')}`, big])
        );
        flowService.nodes.set([{ ...tableNode(), explanations: crowded } as NodeModel]);
        const retained = new Set([...Object.keys(crowded), 'aaa-new']);
        const crowdedScope = TestBed.inject(CdtExplanationStoreService).forNode({
            nodeId: 'node-1',
            backendId: 42,
            retainedStepKeys: retained,
        });

        // Sorts first, so the stored map's size limit would cut the last kept one to fit it.
        expect(crowdedScope.set('aaa-new', big)).toBe(false);
        expect(flowService.updateNode).not.toHaveBeenCalled();
    });

    it('writes nothing — node, persist or cache — in a read-only editor', () => {
        const { scope, flowService, sidePanelService, cache } = setUp({ isReadOnly: true, isPreview: false });

        scope.set('fresh', GENERATED);

        expect(flowService.updateNode).not.toHaveBeenCalled();
        expect(sidePanelService.requestCdtExplanationsSave).not.toHaveBeenCalled();
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

    describe('move', () => {
        const TABLE = { nodeId: 'node-1', backendId: 42 };
        const OLD_PROMPT: CdtExplanation = { text: 'Old prompt', fingerprint: 'old-prompt', generatedBy: 'model' };
        const ORPHAN: CdtExplanation = { text: 'Left by a deleted rule', fingerprint: 'orphan', generatedBy: 'model' };

        function withExplanations(flowService: ReturnType<typeof setUp>['flowService'], explanations: object): void {
            flowService.nodes.set([{ ...tableNode(), explanations } as NodeModel]);
        }

        function storeService(): CdtExplanationStoreService {
            return TestBed.inject(CdtExplanationStoreService);
        }

        it('re-files what is under each old key under the new one, over whatever was there, and leaves the rest', () => {
            const { flowService } = setUp({ isReadOnly: false, isPreview: false });
            withExplanations(flowService, {
                'rule:route:a:decision': STORED,
                'rule:route:a:prompt': OLD_PROMPT,
                'rule:route:b:decision': ORPHAN,
                'rule:route:c:decision': GENERATED,
            });

            storeService().move(TABLE, [
                { from: 'rule:route:a:decision', to: 'rule:route:b:decision' },
                { from: 'rule:route:a:prompt', to: 'rule:route:b:prompt' },
                { from: 'rule:route:a:manipulation', to: 'rule:route:b:manipulation' },
            ]);

            expect(flowService.updateNode).toHaveBeenCalledTimes(1);
            const [updated, options] = flowService.updateNode.mock.calls[0];
            expect(updated.explanations).toEqual({
                'rule:route:b:decision': STORED,
                'rule:route:b:prompt': OLD_PROMPT,
                'rule:route:c:decision': GENERATED,
            });
            // Sorted, as `set` writes them, so the canvas and the saved copy stringify alike.
            expect(Object.keys(updated.explanations)).toEqual([
                'rule:route:b:decision',
                'rule:route:b:prompt',
                'rule:route:c:decision',
            ]);
            expect(options).toEqual({ skipDecisionTableReset: true });
        });

        it('writes the new keys through to the cache, and asks for no persist', () => {
            const { flowService, sidePanelService, cache } = setUp({ isReadOnly: false, isPreview: false });
            withExplanations(flowService, { 'rule:route:a:decision': STORED });

            storeService().move(TABLE, [
                { from: 'rule:route:a:decision', to: 'rule:route:b:decision' },
                { from: 'rule:route:a:prompt', to: 'rule:route:b:prompt' },
            ]);

            expect(cache.set).toHaveBeenCalledExactlyOnceWith('42|rule:route:b:decision', STORED);
            expect(sidePanelService.requestCdtExplanationsSave).not.toHaveBeenCalled();
        });

        it('changes nothing when no old key has an entry', () => {
            const { flowService, cache } = setUp({ isReadOnly: false, isPreview: false });

            storeService().move(TABLE, [{ from: 'rule:route:a:decision', to: 'stored' }]);

            expect(flowService.updateNode).not.toHaveBeenCalled();
            expect(cache.set).not.toHaveBeenCalled();
        });

        it('writes nothing — node, persist or cache — in a read-only editor', () => {
            const { flowService, sidePanelService, cache } = setUp({ isReadOnly: true, isPreview: false });

            storeService().move(TABLE, [{ from: 'stored', to: 'rule:route:b:decision' }]);

            expect(flowService.updateNode).not.toHaveBeenCalled();
            expect(sidePanelService.requestCdtExplanationsSave).not.toHaveBeenCalled();
            expect(cache.set).not.toHaveBeenCalled();
        });

        it('refuses a move whose longer key would push an explanation already kept out of the stored map', () => {
            const { flowService, cache } = setUp({ isReadOnly: false, isPreview: false });
            const big = { ...GENERATED, text: 't'.repeat(CDT_EXPLANATION_LIMITS.maxTextLength) };
            const crowded: Record<string, CdtExplanation> = Object.fromEntries(
                Array.from({ length: 52 }, (_, index) => [`stored-${String(index).padStart(2, '0')}`, big])
            );
            // Filled to five bytes short of the limit, with the entry that sorts last.
            const bytes = (map: object): number => new TextEncoder().encode(JSON.stringify(map)).length;
            const withEmptyFiller = { ...crowded, 'zzz-filler': { ...GENERATED, text: '' } };
            const fillerText = 'f'.repeat(CDT_EXPLANATION_LIMITS.maxTotalBytes - 5 - bytes(withEmptyFiller));
            withExplanations(flowService, { ...crowded, 'zzz-filler': { ...GENERATED, text: fillerText } });

            storeService().move(TABLE, [{ from: 'stored-00', to: 'stored-00-under-a-much-longer-key' }]);

            expect(flowService.updateNode).not.toHaveBeenCalled();
            expect(cache.set).not.toHaveBeenCalled();
        });
    });
});
