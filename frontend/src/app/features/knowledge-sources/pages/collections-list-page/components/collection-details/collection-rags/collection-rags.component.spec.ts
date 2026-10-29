import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { ToastService } from '../../../../../../../services/notifications';
import { IndexingUsage } from '../../../../../models/base-rag.model';
import { CollectionStatus, CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { CollectionDetailsGraphRag } from '../../../../../models/graph-rag.model';
import { CollectionDetailsNaiveRag } from '../../../../../models/naive-rag.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { GraphRagDocumentsStorageService } from '../../../../../services/graph-rag-documents-storage.service';
import { NaiveRagDocumentsStorageService } from '../../../../../services/naive-rag-documents-storage.service';
import { RagDeleteRegistryService } from '../../../../../services/rag-delete-registry.service';
import { CollectionRagsComponent } from './collection-rags.component';

const TOTALS = { embedding_tokens: 1000, llm_input_tokens: null, llm_output_tokens: null, cost_usd: 0.5 };

const USED = { last_run: { ...TOTALS, completed_at: '2026-01-01T00:00:00Z' }, total: TOTALS };

function naiveRag(indexingUsage: IndexingUsage): CollectionDetailsNaiveRag {
    return {
        chunks_count: 0,
        document_configs_count: 0,
        embedder_id: 1,
        embedder_name: 'embedder',
        embeddings_count: 0,
        indexing_document_config_ids: [],
        is_ready_for_indexing: true,
        message: null,
        rag_id: 1,
        rag_type: 'naive',
        status: 'completed',
        indexing_usage: indexingUsage,
        created_at: '2026-03-12T13:28:23Z',
        updated_at: '2026-03-12T13:28:23Z',
    };
}

function graphRag(indexingUsage: IndexingUsage): CollectionDetailsGraphRag {
    return {
        embedder_id: '2',
        embedder_name: 'embedder',
        llm_name: 'llm',
        is_ready_for_indexing: true,
        message: null,
        rag_id: 2,
        rag_type: 'graph',
        require_reindexing: false,
        reindex_reason: {},
        status: 'completed',
        processing_document_ids: [],
        indexing_usage: indexingUsage,
        created_at: '2026-03-12T13:28:23Z',
        updated_at: '2026-03-12T13:28:23Z',
    };
}

function collectionWith(
    configurations: (CollectionDetailsNaiveRag | CollectionDetailsGraphRag)[]
): CreateCollectionDtoResponse {
    return {
        collection_id: 1,
        collection_name: 'Docs',
        description: '',
        status: CollectionStatus.COMPLETED,
        document_count: 0,
        rag_configurations: configurations,
        created_at: '2026-03-12T13:28:23Z',
        updated_at: '2026-03-12T13:28:23Z',
        created_by: null,
        last_edited_by: null,
        last_edited_at: null,
    };
}

function render(configurations: (CollectionDetailsNaiveRag | CollectionDetailsGraphRag)[]) {
    const openDialog = vi.fn(() => ({ closed: of(undefined) }));
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can: () => false } },
            { provide: Dialog, useValue: { open: openDialog } },
            { provide: ToastService, useValue: {} },
            { provide: CollectionsStorageService, useValue: { getFullCollection: () => of(null) } },
            { provide: ConfirmationDialogService, useValue: {} },
            { provide: RagDeleteRegistryService, useValue: {} },
            { provide: NaiveRagDocumentsStorageService, useValue: {} },
            { provide: GraphRagDocumentsStorageService, useValue: {} },
        ],
    });
    const fixture = TestBed.createComponent(CollectionRagsComponent);
    fixture.componentRef.setInput('collection', collectionWith(configurations));
    fixture.detectChanges();
    const host = fixture.nativeElement as HTMLElement;
    const rows = Array.from(host.querySelectorAll<HTMLElement>('li.item'));
    const toggleOf = (row: HTMLElement) => row.querySelector<HTMLButtonElement>('button.usage-toggle');
    const isExpanded = (row: HTMLElement) => toggleOf(row)?.getAttribute('aria-expanded') === 'true';
    const click = (element: HTMLElement) => {
        element.click();
        fixture.detectChanges();
    };
    return { host, rows, toggleOf, isExpanded, click, openDialog };
}

describe('CollectionRagsComponent usage details', () => {
    it('shows no toggle and no details for a RAG without usage', () => {
        const { rows, toggleOf, host } = render([naiveRag({})]);

        expect(toggleOf(rows[0])).toBeNull();
        expect(host.querySelector('.usage-details')).toBeNull();
    });

    it('renders the last indexing and total as label/value pairs', () => {
        const { host } = render([naiveRag(USED)]);
        const pairs = Array.from(host.querySelectorAll('.usage-details__row')).map((row) => [
            row.querySelector('dt')?.textContent?.trim(),
            row.querySelector('dd')?.textContent?.trim(),
        ]);

        expect(pairs).toEqual([
            ['Last indexing', '1,000 embedding tokens · $0.50'],
            ['Total', '1,000 embedding tokens · $0.50'],
        ]);
    });

    it('draws the dot between value parts as its own faded separator', () => {
        const { host } = render([naiveRag(USED)]);
        const separators = Array.from(host.querySelectorAll('.usage-details__value .usage-details__separator'));

        expect(separators.map((separator) => separator.textContent)).toEqual([' · ', ' · ']);
    });

    it('starts collapsed and opens and closes on the toggle', () => {
        const { rows, toggleOf, isExpanded, click } = render([naiveRag(USED)]);
        const details = rows[0].querySelector('.usage');

        expect(isExpanded(rows[0])).toBe(false);
        expect(details?.classList).not.toContain('expanded');

        click(toggleOf(rows[0])!);
        expect(isExpanded(rows[0])).toBe(true);
        expect(details?.classList).toContain('expanded');

        click(toggleOf(rows[0])!);
        expect(isExpanded(rows[0])).toBe(false);
    });

    it('opens only the toggled row', () => {
        const { rows, toggleOf, isExpanded, click } = render([naiveRag(USED), graphRag(USED)]);

        click(toggleOf(rows[1])!);

        expect(isExpanded(rows[0])).toBe(false);
        expect(isExpanded(rows[1])).toBe(true);
    });

    it('does not open the RAG configuration from the toggle, while the row still does', () => {
        const { rows, toggleOf, click, openDialog } = render([naiveRag(USED)]);

        click(toggleOf(rows[0])!);
        expect(openDialog).not.toHaveBeenCalled();

        click(rows[0]);
        expect(openDialog).toHaveBeenCalledTimes(1);
    });
});
