import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ExtractedChunksMessageData, GraphMessage, MessageType } from '../../../../models/graph-session-message.model';
import { ExtractedChunksMessageComponent } from './extracted-chunks-message.component';

const BASE_DATA: ExtractedChunksMessageData = {
    agent_id: 1,
    collection_id: 1,
    retrieved_chunks: 0,
    knowledge_query: 'what is epicstaff',
    chunks: [],
    message_type: MessageType.EXTRACTED_CHUNKS,
    rag_search_config: {},
};

function render(overrides: Partial<ExtractedChunksMessageData>): HTMLElement {
    TestBed.configureTestingModule({
        imports: [ExtractedChunksMessageComponent],
        providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const fixture = TestBed.createComponent(ExtractedChunksMessageComponent);
    const message: GraphMessage = {
        id: 1,
        session: 1,
        name: 'knowledge',
        execution_order: 1,
        created_at: '2026-10-01T00:00:00Z',
        message_data: { ...BASE_DATA, ...overrides },
        metadata: {},
    };
    fixture.componentRef.setInput('message', message);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

function texts(element: HTMLElement, selector: string): string[] {
    return Array.from(element.querySelectorAll(selector)).map((node) => node.textContent?.trim() ?? '');
}

describe('ExtractedChunksMessageComponent', () => {
    it('renders naive chunks with type label, limit, retrieved, threshold, chip and source', () => {
        const element = render({
            rag_type: 'naive',
            retrieved_chunks: 2,
            chunks: [
                { text: 'first', order: 0, source: 'doc.pdf', similarity: 0.9 },
                { text: 'second', order: 1 },
            ],
            answer: null,
            rag_search_config: { rag_type: 'naive', search_limit: 3, similarity_threshold: 0.5 },
        });

        expect(texts(element, '.stat .label')).toEqual(['Search limit', 'Retrieved', 'Similarity threshold']);
        expect(texts(element, '.chip')).toEqual(['Naive RAG', '2 chunks']);
        expect(texts(element, '.chunk-order')).toEqual(['#0', '#1']);
        expect(texts(element, '.chunk-source')).toEqual(['doc.pdf', 'Unknown source']);
        expect(texts(element, '.chunk-text')).toEqual(['first', 'second']);
    });

    it('renders a new graph message as one answer block', () => {
        const element = render({
            rag_type: 'graph',
            answer: 'EpicStaff is a platform.',
            rag_search_config: {
                rag_type: 'graph',
                search_params: { search_method: 'local', max_context_tokens: 4000 },
            },
        });

        expect(texts(element, '.stat .label')).toEqual(['Search method', 'Max context tokens']);
        expect(texts(element, '.stat .value')).toEqual(['Local', '4000']);
        expect(texts(element, '.chip')).toEqual(['Graph RAG']);
        expect(element.querySelector('.chunk-source')).toBeNull();
        expect(texts(element, '.chunk-order')).toEqual(['Answer']);
        expect(texts(element, '.chunk-text')).toEqual(['EpicStaff is a platform.']);
        expect(element.querySelector('app-copy-button')).not.toBeNull();
    });

    it('renders an old crew-path graph message (string chunk, rag_strategy only) as the answer', () => {
        const element = render({
            retrieved_chunks: 1,
            chunks: ['Old answer'],
            rag_search_config: { rag_strategy: 'graph', method: 'global', max_context_tokens: 2000 },
        });

        expect(texts(element, '.stat .value')).toEqual(['Global', '2000']);
        expect(texts(element, '.chunk-order')).toEqual(['Answer']);
        expect(texts(element, '.chip')).toEqual(['Graph RAG']);
        expect(texts(element, '.chunk-text')).toEqual(['Old answer']);
    });

    it('renders an old agent-path graph message (rag_type only in rag_search_config) as the answer', () => {
        const element = render({
            answer: 'Agent answer',
            rag_search_config: {
                rag_type: 'graph',
                search_params: { search_method: 'local', max_context_tokens: 1000 },
            },
        });

        expect(texts(element, '.stat .value')).toEqual(['Local', '1000']);
        expect(texts(element, '.chunk-order')).toEqual(['Answer']);
        expect(texts(element, '.chip')).toEqual(['Graph RAG']);
        expect(texts(element, '.chunk-text')).toEqual(['Agent answer']);
    });

    it('shows only the answer for a graph message that also has chunks', () => {
        const element = render({
            rag_type: 'graph',
            answer: 'The answer',
            chunks: [{ text: 'stray chunk', order: 0, source: 'doc.pdf' }],
        });

        expect(texts(element, '.chunk-card .chunk-order')).toEqual(['Answer']);
        expect(texts(element, '.chunk-text')).toEqual(['The answer']);
        expect(element.querySelector('.chunk-source')).toBeNull();
    });

    it('shows the no-grounded-answer text for an empty graph answer', () => {
        const element = render({ rag_type: 'graph', answer: '' });

        expect(element.querySelector('.chunk-empty')).not.toBeNull();
        expect(element.querySelector('.chunk-text')).toBeNull();
        expect(element.querySelector('app-copy-button')).toBeNull();
    });

    it('shows chunks with only the retrieved stat and no type label when the type is unknown', () => {
        const element = render({ retrieved_chunks: 1, chunks: [{ text: 'some chunk', order: 0 }] });

        expect(texts(element, '.stat .label')).toEqual(['Retrieved']);
        expect(texts(element, '.chip')).toEqual(['1 chunk']);
        expect(texts(element, '.chunk-text')).toEqual(['some chunk']);
        expect(element.querySelector('.chunk-source')).toBeNull();
    });
});
