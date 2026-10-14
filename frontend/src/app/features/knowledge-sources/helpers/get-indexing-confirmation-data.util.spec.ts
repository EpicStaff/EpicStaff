import { Subject } from 'rxjs';

import { IndexingEstimate } from '../models/base-rag.model';
import { getIndexingConfirmationDataWithEstimate } from './get-indexing-confirmation-data.util';

const DOCUMENTS = [{ configId: 1, fileName: 'a.pdf', wasIndexed: false }];
const ESTIMATE: IndexingEstimate = {
    rag_type: 'naive',
    document_count: 1,
    chunk_count: 2,
    embedding: { tokens: 10, exact: true, cost_usd: 0.1 },
    llm: null,
};

describe('getIndexingConfirmationDataWithEstimate', () => {
    it('opens with a placeholder and replaces it with the estimate', () => {
        const estimate$ = new Subject<IndexingEstimate | null>();
        const data = getIndexingConfirmationDataWithEstimate(DOCUMENTS, estimate$);
        const messages: string[] = [];
        data.messageUpdates?.subscribe((message) => messages.push(message));

        expect(data.message).toContain('Estimating usage');
        estimate$.next(ESTIMATE);
        expect(messages[0]).toContain('Estimated usage');
        expect(messages[0]).not.toContain('Estimating usage');
    });

    it('drops the placeholder when the estimate is missing or fails', () => {
        const missing = new Subject<IndexingEstimate | null>();
        const failing = new Subject<IndexingEstimate | null>();
        const messages: string[] = [];
        getIndexingConfirmationDataWithEstimate(DOCUMENTS, missing).messageUpdates?.subscribe((m) => messages.push(m));
        getIndexingConfirmationDataWithEstimate(DOCUMENTS, failing).messageUpdates?.subscribe((m) => messages.push(m));

        missing.next(null);
        failing.error(new Error('boom'));

        expect(messages).toHaveLength(2);
        messages.forEach((message) => expect(message).not.toContain('Estimating usage'));
    });
});
