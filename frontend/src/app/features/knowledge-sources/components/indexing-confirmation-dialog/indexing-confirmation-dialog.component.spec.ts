import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { IndexingEstimate } from '../../models/base-rag.model';
import { IndexingDocumentInfo } from '../../models/rag-configuration';
import {
    IndexingConfirmationDialogComponent,
    IndexingConfirmationDialogData,
} from './indexing-confirmation-dialog.component';

const NEW_FILE: IndexingDocumentInfo = { configId: 1, fileName: 'new.pdf', wasIndexed: false };
const OLD_FILE: IndexingDocumentInfo = { configId: 2, fileName: 'old.pdf', wasIndexed: true };
const OTHER_OLD_FILE: IndexingDocumentInfo = { configId: 4, fileName: 'older.pdf', wasIndexed: true };

function estimate(embedding: IndexingEstimate['embedding'], documentCount: number = 1): IndexingEstimate {
    return { rag_type: 'naive', document_count: documentCount, chunk_count: 3, embedding };
}

/** `app-button` watches its own size; jsdom has no ResizeObserver. */
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

let dialogRef: { close: ReturnType<typeof vi.fn>; keydownEvents: Subject<KeyboardEvent> };

function render(data: Partial<IndexingConfirmationDialogData>): ComponentFixture<IndexingConfirmationDialogComponent> {
    vi.stubGlobal('ResizeObserver', ResizeObserverStub);
    dialogRef = { close: vi.fn(), keydownEvents: new Subject<KeyboardEvent>() };
    TestBed.configureTestingModule({
        imports: [IndexingConfirmationDialogComponent],
        providers: [
            provideHttpClient(),
            provideHttpClientTesting(),
            {
                provide: DIALOG_DATA,
                useValue: {
                    documents: [NEW_FILE],
                    ragType: 'naive',
                    embedderName: 'text-embedding-3-small',
                    llmName: null,
                    ...data,
                },
            },
            { provide: DialogRef, useValue: dialogRef },
        ],
    });
    const fixture = TestBed.createComponent(IndexingConfirmationDialogComponent);
    fixture.detectChanges();
    return fixture;
}

function host(fixture: ComponentFixture<IndexingConfirmationDialogComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function text(fixture: ComponentFixture<IndexingConfirmationDialogComponent>, selector: string): string | null {
    return host(fixture).querySelector(selector)?.textContent?.replace(/\s+/g, ' ').trim() ?? null;
}

function texts(fixture: ComponentFixture<IndexingConfirmationDialogComponent>, selector: string): string[] {
    return Array.from(host(fixture).querySelectorAll(selector)).map(
        (element) => element.textContent?.replace(/\s+/g, ' ').trim() ?? ''
    );
}

/** The tiles as `label: value` pairs, in order. */
function tiles(fixture: ComponentFixture<IndexingConfirmationDialogComponent>): string[] {
    return Array.from(host(fixture).querySelectorAll('.estimate__tile')).map(
        (tile) =>
            `${tile.querySelector('.estimate__label')?.textContent?.trim()}: ${tile.querySelector('.estimate__value')?.textContent?.trim()}`
    );
}

function buttonByText(fixture: ComponentFixture<IndexingConfirmationDialogComponent>, label: string): HTMLElement {
    const button = Array.from(host(fixture).querySelectorAll('app-button button')).find(
        (element) => element.textContent?.trim() === label
    );
    if (!button) throw new Error(`No "${label}" button`);
    return button as HTMLElement;
}

afterEach(() => {
    vi.unstubAllGlobals();
});

describe('IndexingConfirmationDialogComponent texts', () => {
    it.each([
        ['only new files', [NEW_FILE], 'Confirm Indexing', 'Start Indexing'],
        ['re-indexed files', [NEW_FILE, OLD_FILE], 'Confirm Re-indexing', 'Re-index'],
    ])('names the title and confirm button for %s', (_case, documents, title, confirmText) => {
        const fixture = render({ documents });

        expect(text(fixture, '.dialog__title')).toBe(title);
        expect(buttonByText(fixture, confirmText)).toBeTruthy();
        expect(buttonByText(fixture, 'Cancel')).toBeTruthy();
    });

    // Raw text, not whitespace-collapsed: the spaces between the parts are part of what is checked.
    it.each<[string, Partial<IndexingConfirmationDialogData>, string]>([
        [
            'a naive RAG',
            { documents: [NEW_FILE, OLD_FILE] },
            '2 files will be parsed, split into chunks and embedded with text-embedding-3-small.',
        ],
        [
            'a naive RAG without an embedder name',
            { embedderName: null },
            '1 file will be parsed, split into chunks and embedded.',
        ],
        [
            'a graph RAG',
            { ragType: 'graph', llmName: 'gpt-4o config' },
            '1 file will be split into chunks, turned into a knowledge graph with gpt-4o config and embedded with text-embedding-3-small.',
        ],
        [
            'a graph RAG without an LLM name',
            { ragType: 'graph' },
            '1 file will be split into chunks, turned into a knowledge graph and embedded with text-embedding-3-small.',
        ],
        [
            'a graph RAG without any name',
            { ragType: 'graph', embedderName: null },
            '1 file will be split into chunks, turned into a knowledge graph and embedded.',
        ],
    ])('describes the pipeline of %s in the intro', (_case, data, expected) => {
        const fixture = render(data);

        expect(host(fixture).querySelector('.intro')?.textContent?.trim()).toBe(expected);
    });

    it('emphasises the LLM and embedder names', () => {
        const fixture = render({ ragType: 'graph', llmName: 'gpt-4o config' });

        expect(texts(fixture, '.intro strong')).toEqual(['gpt-4o config', 'text-embedding-3-small']);
    });
});

describe('IndexingConfirmationDialogComponent estimate', () => {
    it('shows animated dots in both tiles while the estimate loads, announced as "Estimating"', () => {
        const fixture = render({ estimate$: new Subject<IndexingEstimate | null>() });
        const values = Array.from(host(fixture).querySelectorAll('.estimate__value'));

        expect(tiles(fixture)).toEqual(['Tokens: Estimating', 'Est. cost: Estimating']);
        expect(values.map((value) => value.querySelectorAll('.loading-dots__dot[aria-hidden="true"]').length)).toEqual([
            3, 3,
        ]);
    });

    it.each([
        [
            'an approximate',
            estimate({ tokens: 3547, exact: false, cost_usd: 0.004 }),
            ['Tokens: ≈ 3,547', 'Est. cost: < $0.01'],
        ],
        ['an exact', estimate({ tokens: 10, exact: true, cost_usd: 1 }), ['Tokens: 10', 'Est. cost: $1.00']],
        ['an unpriced', estimate({ tokens: 10, exact: true, cost_usd: null }), ['Tokens: 10']],
    ])('fills the tiles with %s estimate once it arrives', (_case, value, expected) => {
        const estimate$ = new Subject<IndexingEstimate | null>();
        const fixture = render({ estimate$ });

        estimate$.next(value);
        fixture.detectChanges();

        expect(tiles(fixture)).toEqual(expected);
        expect(text(fixture, '.estimate__note')).toBe('Rough estimate. Actual usage may differ.');
    });

    it.each<[string, Observable<IndexingEstimate | null> | undefined]>([
        ['the estimate fails', throwError(() => new Error('boom'))],
        ['there is no estimate', of(null)],
        ['the RAG type gives no estimate', undefined],
    ])('shows no tiles and no note when %s', (_case, estimate$) => {
        const fixture = render({ estimate$ });

        expect(tiles(fixture)).toEqual([]);
        expect(host(fixture).querySelector('.estimate__note')).toBeNull();
        expect(host(fixture).querySelector('.estimate-message')).toBeNull();
    });

    it('says the files are already indexed instead of showing tiles', () => {
        const fixture = render({ estimate$: of(estimate({ tokens: 0, exact: true, cost_usd: 0 }, 0)) });

        expect(tiles(fixture)).toEqual([]);
        expect(text(fixture, '.estimate-message')).toContain('Already indexed with these settings');
    });

    it('announces the estimate through one live region that is there from the first render', () => {
        const estimate$ = new Subject<IndexingEstimate | null>();
        const fixture = render({ estimate$ });
        const region = host(fixture).querySelector('[aria-live="polite"]');

        expect(region?.getAttribute('aria-busy')).toBe('true');

        estimate$.next(estimate({ tokens: 0, exact: true, cost_usd: 0 }, 0));
        fixture.detectChanges();

        expect(host(fixture).querySelector('[aria-live="polite"]')).toBe(region);
        expect(region?.getAttribute('aria-busy')).toBe('false');
        expect(region?.textContent).toContain('Already indexed with these settings');
    });

    it('keeps the live region when there is no estimate to show', () => {
        const fixture = render({});

        expect(host(fixture).querySelector('[aria-live="polite"]')).not.toBeNull();
    });

    it('stops listening for the estimate once the dialog is gone', () => {
        const estimate$ = new Subject<IndexingEstimate | null>();
        const fixture = render({ estimate$ });

        fixture.destroy();

        expect(estimate$.observed).toBe(false);
    });
});

describe('IndexingConfirmationDialogComponent file lists', () => {
    function toggle(fixture: ComponentFixture<IndexingConfirmationDialogComponent>, title: string): HTMLButtonElement {
        const button = Array.from(host(fixture).querySelectorAll<HTMLButtonElement>('.files__toggle')).find(
            (element) => element.querySelector('.files__title')?.textContent?.trim() === title
        );
        if (!button) throw new Error(`No "${title}" toggle`);
        return button;
    }

    it.each([
        ['only new files', [NEW_FILE], ['Index files: 1']],
        ['new and re-indexed files', [NEW_FILE, OLD_FILE, OTHER_OLD_FILE], ['Index files: 1', 'Re-index files: 2']],
    ])('lists only the non-empty groups with their counts for %s', (_case, documents, expected) => {
        const fixture = render({ documents });
        const groups = Array.from(host(fixture).querySelectorAll('.files__toggle')).map(
            (toggle) =>
                `${toggle.querySelector('.files__title')?.textContent?.trim()}: ${toggle.querySelector('.files__count')?.textContent?.trim()}`
        );

        expect(groups).toEqual(expected);
    });

    it('starts collapsed and toggles each list on its own', () => {
        const fixture = render({ documents: [NEW_FILE, OLD_FILE] });
        const indexToggle = toggle(fixture, 'Index files');
        const reindexToggle = toggle(fixture, 'Re-index files');

        expect(indexToggle.getAttribute('aria-expanded')).toBe('false');
        expect(reindexToggle.getAttribute('aria-expanded')).toBe('false');

        reindexToggle.click();
        fixture.detectChanges();

        expect(indexToggle.getAttribute('aria-expanded')).toBe('false');
        expect(reindexToggle.getAttribute('aria-expanded')).toBe('true');
        const reindexList = host(fixture).querySelector(`#${reindexToggle.getAttribute('aria-controls')}`);
        expect(reindexList?.closest('.grid-collapsible')?.classList).toContain('expanded');
        expect(reindexList?.textContent?.trim()).toBe('old.pdf');

        reindexToggle.click();
        fixture.detectChanges();

        expect(reindexToggle.getAttribute('aria-expanded')).toBe('false');
    });

    it('shows file names as text, never as markup', () => {
        const fileName = '<img src=x onerror="alert(1)">.pdf';
        const fixture = render({ documents: [{ configId: 3, fileName, wasIndexed: false }] });

        expect(texts(fixture, '.files__item')).toEqual([fileName]);
        expect(host(fixture).querySelector('.files__list img')).toBeNull();
    });
});

describe('IndexingConfirmationDialogComponent result', () => {
    it.each([
        ['Start Indexing', true],
        ['Cancel', false],
    ])('closes with the answer of the "%s" button', (label, result) => {
        const fixture = render({});

        buttonByText(fixture, label).click();

        expect(dialogRef.close).toHaveBeenCalledWith(result);
    });

    it('confirms on Enter', () => {
        render({});

        dialogRef.keydownEvents.next(new KeyboardEvent('keydown', { key: 'Enter' }));

        expect(dialogRef.close).toHaveBeenCalledWith(true);
    });

    it('closes with "close" from the close button', () => {
        const fixture = render({});

        (host(fixture).querySelector('app-icon-button.dialog__close button') as HTMLButtonElement).click();

        expect(dialogRef.close).toHaveBeenCalledWith('close');
    });
});
