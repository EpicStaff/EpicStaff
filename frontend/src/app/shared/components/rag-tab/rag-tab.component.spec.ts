import { TestBed } from '@angular/core/testing';
import { FormControl, FormGroup } from '@angular/forms';
import { RAG_MAX_TOKENS } from '@shared/constants';
import { SuggestResponse } from '@shared/models';
import { RAG_SUGGEST_API } from '@shared/services';
import { of } from 'rxjs';

import { RagTabComponent } from './rag-tab.component';

const CONTEXT_WINDOW = 8000;
const SAFE_BUDGET = 6000;

const SUGGEST_RESPONSE: SuggestResponse = {
    metrics: { total_documents: 1, total_chunks: 1, avg_chunk_size: 1 } as SuggestResponse['metrics'],
    resolved_llm_name: null,
    llm_resolution_warning: null,
    effective_llm_context_window: CONTEXT_WINDOW,
    safe_token_budget: SAFE_BUDGET,
    clamped_fields: [],
    suggested_params: {},
};

function render(): RagTabComponent {
    TestBed.configureTestingModule({
        providers: [
            {
                provide: RAG_SUGGEST_API,
                useValue: {
                    suggestGraphSearchParams: () => of(SUGGEST_RESPONSE),
                    suggestNaiveSearchParams: () => of(SUGGEST_RESPONSE),
                },
            },
        ],
    });
    TestBed.overrideComponent(RagTabComponent, { set: { template: '', imports: [] } });
    const fixture = TestBed.createComponent(RagTabComponent);
    fixture.componentRef.setInput(
        'form',
        new FormGroup({
            knowledge_collection: new FormControl(7),
            rag: new FormControl({ rag_id: null, rag_type: 'graph' }),
        })
    );
    fixture.componentRef.setInput('allKnowledgeSources', []);
    fixture.componentRef.setInput('agentRags', []);
    fixture.componentRef.setInput('searchConfigs', null);
    fixture.detectChanges();
    return fixture.componentInstance;
}

describe('RagTabComponent validation', () => {
    it('rejects local proportions that add up to more than 1', () => {
        const local = render().localGroup!;

        local.patchValue({ text_unit_prop: 0.6, community_prop: 0.5 });
        expect(local.hasError('proportionSum')).toBe(true);

        local.patchValue({ text_unit_prop: 0.5, community_prop: 0.5 });
        expect(local.hasError('proportionSum')).toBe(false);
    });

    it('rejects drift local-search proportions above 1 and tolerates float noise at exactly 1', () => {
        const drift = render().driftGroup!;

        drift.patchValue({ local_search_text_unit_prop: 0.6, local_search_community_prop: 0.5 });
        expect(drift.hasError('proportionSum')).toBe(true);

        drift.patchValue({ local_search_text_unit_prop: 0.7, local_search_community_prop: 0.3 });
        expect(drift.hasError('proportionSum')).toBe(false);
    });

    it('treats a value above the LLM context window as a warning, not an error', () => {
        const component = render();
        const maxContextTokens = component.basicGroup!.get('max_context_tokens')!;

        maxContextTokens.setValue(CONTEXT_WINDOW + 1);

        expect(component.effectiveLlmContextWindow()).toBe(CONTEXT_WINDOW);
        expect(maxContextTokens.valid).toBe(true);
        expect(component.tokenWarning().max).toBe(SAFE_BUDGET);
    });

    it('keeps the static token bound as the only hard limit', () => {
        const maxContextTokens = render().basicGroup!.get('max_context_tokens')!;

        maxContextTokens.setValue(RAG_MAX_TOKENS);
        expect(maxContextTokens.valid).toBe(true);

        maxContextTokens.setValue(RAG_MAX_TOKENS + 1);
        expect(maxContextTokens.hasError('max')).toBe(true);
    });

    it('warns on drift token caps above Data Max Tokens without making them invalid', () => {
        const component = render();
        const drift = component.driftGroup!;
        drift.patchValue({ data_max_tokens: 4000, reduce_max_tokens: 5000 });

        expect(drift.get('reduce_max_tokens')!.valid).toBe(true);
        expect(component.driftTokenCapWarning.max).toBe(4000);
    });
});
