import { Subject } from 'rxjs';

import { IndexingEstimate } from '../models/base-rag.model';
import {
    getIndexingConfirmationData,
    getIndexingConfirmationDataWithEstimate,
} from './get-indexing-confirmation-data.util';

const DOCUMENTS = [{ configId: 1, fileName: 'a.pdf', wasIndexed: false }];
const ESTIMATE: IndexingEstimate = {
    rag_type: 'naive',
    document_count: 1,
    chunk_count: 2,
    embedding: { tokens: 10, exact: true, cost_usd: 0.1 },
};

describe('getIndexingConfirmationDataWithEstimate', () => {
    it('opens with a placeholder and replaces it with the estimate', () => {
        const estimate$ = new Subject<IndexingEstimate | null>();
        const data = getIndexingConfirmationDataWithEstimate(DOCUMENTS, estimate$);
        const footers: string[] = [];
        data.footerMessageUpdates?.subscribe((footer) => footers.push(footer));

        expect(data.message).toContain('Initializing indexing');
        expect(data.caution).toContain('consumes <strong>tokens</strong>');
        expect(data.footerMessage).toContain('Estimating usage');
        expect(data.footerMessage).toContain('class="dialog-callout dialog-callout--pending"');
        estimate$.next(ESTIMATE);
        expect(footers[0]).toContain('Estimated usage');
        expect(footers[0]).not.toContain('Estimating usage');
        expect(data.message).toBe(getIndexingConfirmationData(DOCUMENTS).message);
    });

    it('drops the placeholder when the estimate is missing or fails', () => {
        const missing = new Subject<IndexingEstimate | null>();
        const failing = new Subject<IndexingEstimate | null>();
        const messages: string[] = [];
        getIndexingConfirmationDataWithEstimate(DOCUMENTS, missing).footerMessageUpdates?.subscribe((m) =>
            messages.push(m)
        );
        getIndexingConfirmationDataWithEstimate(DOCUMENTS, failing).footerMessageUpdates?.subscribe((m) =>
            messages.push(m)
        );

        missing.next(null);
        failing.error(new Error('boom'));

        expect(messages).toHaveLength(2);
        messages.forEach((message) => expect(message).not.toContain('Estimating usage'));
    });
});

describe('getIndexingConfirmationDataWithEstimate for re-indexed files', () => {
    it('keeps the file lists in the caution and puts the estimate in the footer', () => {
        const estimate$ = new Subject<IndexingEstimate | null>();
        const data = getIndexingConfirmationDataWithEstimate(
            [{ configId: 2, fileName: 'old.pdf', wasIndexed: true }],
            estimate$
        );
        const footers: string[] = [];
        data.footerMessageUpdates?.subscribe((footer) => footers.push(footer));

        expect(data.message).toContain('consumes <strong>tokens</strong>');
        expect(data.message).not.toContain('Estimat');
        expect(data.caution).toContain('old.pdf');
        expect(data.footerMessage).toContain('Estimating usage');
        estimate$.next(ESTIMATE);
        expect(footers[0]).toContain('Estimated usage');
    });
});

describe('getIndexingConfirmationData without an estimate', () => {
    it('keeps the warning in the caution block, after the intro message', () => {
        const data = getIndexingConfirmationData(DOCUMENTS);

        expect(data.message).toContain('Initializing indexing');
        expect(data.message).not.toContain('consumes');
        expect(data.footerMessage).toBeUndefined();
        expect(data.caution).toContain('consumes <strong>tokens</strong>');
    });
});
