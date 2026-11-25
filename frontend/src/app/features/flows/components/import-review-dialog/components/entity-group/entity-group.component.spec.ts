import { ComponentFixture, TestBed } from '@angular/core/testing';
import { buildPreviewImportResult, ImportFileData } from '@shared/utils';

import { FlowNodesByFile, ReviewItem } from '../../../../../../core/models/review-item.model';
import { ReviewSessionStore } from '../../review-session.store';
import { EntityGroupComponent } from './entity-group.component';

function pythonTool(name: string, source: string): ReviewItem {
    return {
        kind: 'python_code_tool',
        name,
        description: null,
        python_code: { code: source, entrypoint: 'main', libraries: '', global_kwargs: {} },
        variables: [],
        use_storage: false,
    };
}

// jsdom has no ResizeObserver; the overflow tooltip directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('EntityGroupComponent', () => {
    let store: ReviewSessionStore;
    let fixture: ComponentFixture<EntityGroupComponent>;

    function render(
        fileData: ImportFileData,
        entityType: string,
        reviewItems: ReviewItem[],
        flowNodes: FlowNodesByFile = {}
    ): void {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({ imports: [EntityGroupComponent], providers: [ReviewSessionStore] });
        store = TestBed.inject(ReviewSessionStore);
        store.init(reviewItems, flowNodes);
        fixture = TestBed.createComponent(EntityGroupComponent);
        fixture.componentRef.setInput('entityType', entityType);
        fixture.componentRef.setInput('result', buildPreviewImportResult(fileData)[entityType]);
        fixture.componentRef.setInput('nodeTypeLabels', {});
        fixture.detectChanges();
    }

    afterEach(() => vi.unstubAllGlobals());

    function row(name: string): HTMLElement {
        const rows = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('.entity-item'));
        return rows.find((element) => element.querySelector('.item-name')?.textContent?.trim() === name)!;
    }

    function currentCode(): string | null {
        const entry = store.currentReviewEntry();
        return entry?.kind === 'code' ? entry.code.code : null;
    }

    it('opens the code of the clicked tool when an id-less tool sits at the position another tool uses as id', () => {
        render({ PythonCodeTool: [{ id: 1, name: 'a' }, { name: 'b' }] }, 'PythonCodeTool', [
            pythonTool('a', 'return "a"'),
            pythonTool('b', 'return "b"'),
        ]);

        row('b').click();
        expect(currentCode()).toBe('return "b"');
        row('a').click();
        expect(currentCode()).toBe('return "a"');
    });

    it('does not give a tool the review state of a flow with the same name', () => {
        render({ PythonCodeTool: [{ id: 1, name: 'Orders' }] }, 'PythonCodeTool', [pythonTool('Orders', 'return 1')], {
            Orders: [{ id: 2, name: 'Fetch', node_type: 'PythonNode' }],
        });

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('app-flow-review-nodes')).toBeNull();
        expect(element.querySelectorAll('app-review-status-badge')).toHaveLength(1);
    });
});
