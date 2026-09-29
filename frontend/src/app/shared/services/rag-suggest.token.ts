import { InjectionToken } from '@angular/core';
import { GraphSuggestRequest, NaiveSuggestRequest, SuggestResponse } from '@shared/models';
import { Observable } from 'rxjs';

/**
 * Feature-agnostic contract for the RAG parameter suggestion endpoints used by
 * the shared RagTabComponent. Features provide their own implementation via the
 * RAG_SUGGEST_API token so the tab stays independent of any one feature's API
 * service.
 */
export interface RagSuggestApi {
    suggestNaiveSearchParams(body: NaiveSuggestRequest): Observable<SuggestResponse>;
    suggestGraphSearchParams(body: GraphSuggestRequest): Observable<SuggestResponse>;
}

export const RAG_SUGGEST_API = new InjectionToken<RagSuggestApi>('RAG_SUGGEST_API');
