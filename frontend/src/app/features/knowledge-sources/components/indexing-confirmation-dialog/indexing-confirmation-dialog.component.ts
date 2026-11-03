import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { NgTemplateOutlet } from '@angular/common';
import { Component, computed, inject, Signal, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { MatTooltip } from '@angular/material/tooltip';
import {
    AppIconComponent,
    AppSvgIconComponent,
    ButtonComponent,
    ConfirmationResult,
    IconButtonComponent,
} from '@shared/components';
import { EnterSubmitDirective, TooltipOnOverflowDirective } from '@shared/directives';
import { catchError, map, Observable, of } from 'rxjs';

import {
    ALREADY_INDEXED_MESSAGE,
    IndexingEstimateView,
    toIndexingEstimateView,
} from '../../helpers/format-indexing-estimate.util';
import { IndexingEstimate, RagType } from '../../models/base-rag.model';
import { IndexingDocumentInfo } from '../../models/rag-configuration';

/** Pass as the dialog's `ariaLabelledBy` so screen readers announce the title. */
export const INDEXING_CONFIRMATION_DIALOG_TITLE_ID = 'indexing-confirmation-dialog-title';

export interface IndexingConfirmationDialogData {
    documents: IndexingDocumentInfo[];
    /** Picks the intro: a graph RAG also builds a knowledge graph. */
    ragType: RagType;
    /** The embedding config's custom name; null drops "with {embedder}" from the intro. */
    embedderName: string | null;
    /** The LLM config's custom name (graph RAG); null drops "with {llm}" from the intro. */
    llmName: string | null;
    /** Omitted when the RAG type gives no estimate. Unsubscribed when the dialog closes, so it can be cancelled. */
    estimate$?: Observable<IndexingEstimate | null>;
}

type FileGroupKind = 'index' | 'reindex';

interface FileGroup {
    kind: FileGroupKind;
    title: string;
    files: IndexingDocumentInfo[];
    listId: string;
}

/** A run of intro text; `isName` ones (the embedder, the LLM) are emphasised. */
interface IntroPart {
    text: string;
    isName: boolean;
}

/** `cost` is null when the price is unknown: only the tokens tile is shown. */
interface EstimateTiles {
    tokens: string;
    cost: string | null;
}

let nextDialogId = 0;

/**
 * Asks before indexing starts: how many files, the embedder, the token and cost estimate as it arrives, what
 * indexing costs, and the files to index and re-index. Closes with `true` (confirm), `false` (cancel) or `'close'`.
 */
@Component({
    selector: 'app-indexing-confirmation-dialog',
    imports: [
        NgTemplateOutlet,
        AppIconComponent,
        AppSvgIconComponent,
        ButtonComponent,
        IconButtonComponent,
        MatTooltip,
        EnterSubmitDirective,
        TooltipOnOverflowDirective,
    ],
    templateUrl: './indexing-confirmation-dialog.component.html',
    styleUrl: './indexing-confirmation-dialog.component.scss',
})
export class IndexingConfirmationDialogComponent {
    // `data` must stay above the fields below: they read it in their initializers.
    protected readonly data = inject<IndexingConfirmationDialogData>(DIALOG_DATA);

    protected readonly estimate: Signal<IndexingEstimateView> = this.data.estimate$
        ? toSignal(
              this.data.estimate$.pipe(
                  map(toIndexingEstimateView),
                  catchError(() => of<IndexingEstimateView>({ state: 'unavailable' }))
              ),
              { initialValue: { state: 'loading' } }
          )
        : signal<IndexingEstimateView>({ state: 'unavailable' });
    /**
     * The two tiles' values, null when there are no tiles. While the estimate loads the view draws animated
     * dots in place of the values; the placeholders only keep the cost tile shown.
     */
    protected readonly tiles = computed<EstimateTiles | null>(() => {
        const estimate = this.estimate();
        if (estimate.state === 'loading') return { tokens: '…', cost: '…' };
        if (estimate.state === 'ready') return { tokens: estimate.tokens, cost: estimate.cost };
        return null;
    });
    protected readonly isEstimateLoading = computed(() => this.estimate().state === 'loading');
    protected readonly isAlreadyIndexed = computed(() => this.estimate().state === 'already-indexed');
    protected readonly expandedLists = signal<ReadonlySet<FileGroupKind>>(new Set());

    protected readonly titleId = INDEXING_CONFIRMATION_DIALOG_TITLE_ID;
    protected readonly alreadyIndexedMessage = ALREADY_INDEXED_MESSAGE;
    protected readonly fileGroups: FileGroup[] = buildFileGroups(this.data.documents);
    protected readonly isReindex = this.data.documents.some((document) => document.wasIndexed);
    protected readonly title = this.isReindex ? 'Confirm Re-indexing' : 'Confirm Indexing';
    protected readonly confirmText = this.isReindex ? 'Re-index' : 'Start Indexing';
    protected readonly intro: IntroPart[] = buildIntro(this.data);

    private readonly dialogRef = inject<DialogRef<ConfirmationResult>>(DialogRef);

    protected isExpanded(kind: FileGroupKind): boolean {
        return this.expandedLists().has(kind);
    }

    protected toggleList(kind: FileGroupKind): void {
        this.expandedLists.update((expanded) => {
            const next = new Set(expanded);
            if (next.has(kind)) {
                next.delete(kind);
            } else {
                next.add(kind);
            }
            return next;
        });
    }

    protected onConfirm(): void {
        this.dialogRef.close(true);
    }

    protected onCancel(): void {
        this.dialogRef.close(false);
    }

    protected onClose(): void {
        this.dialogRef.close('close');
    }
}

function buildFileGroups(documents: IndexingDocumentInfo[]): FileGroup[] {
    const dialogId = nextDialogId++;
    const lists: FileGroup[] = [
        {
            kind: 'index',
            title: 'Index files',
            files: documents.filter((document) => !document.wasIndexed),
            listId: `indexing-confirmation-${dialogId}-index`,
        },
        {
            kind: 'reindex',
            title: 'Re-index files',
            files: documents.filter((document) => document.wasIndexed),
            listId: `indexing-confirmation-${dialogId}-reindex`,
        },
    ];
    return lists.filter((list) => list.files.length > 0);
}

/**
 * "{N} files will be parsed, split into chunks and embedded with {embedder}." — a graph RAG instead: "{N} files will
 * be split into chunks, turned into a knowledge graph with {llm} and embedded with {embedder}." A missing name drops
 * its "with …".
 */
function buildIntro({ documents, ragType, embedderName, llmName }: IndexingConfirmationDialogData): IntroPart[] {
    const count = documents.length;
    const parts: IntroPart[] = [text(`${count === 1 ? '1 file' : `${count} files`} will be `)];
    if (ragType === 'graph') {
        parts.push(
            text('split into chunks, turned into a knowledge graph'),
            ...withName(llmName),
            text(' and embedded')
        );
    } else {
        parts.push(text('parsed, split into chunks and embedded'));
    }
    parts.push(...withName(embedderName), text('.'));
    return parts;
}

function withName(name: string | null): IntroPart[] {
    return name ? [text(' with '), { text: name, isName: true }] : [];
}

function text(value: string): IntroPart {
    return { text: value, isName: false };
}
