import { HttpErrorResponse } from '@angular/common/http';
import {
    afterNextRender,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    Injector,
    input,
    output,
    signal,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { BlobPreviewComponent, ButtonComponent, ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode } from '@shared/models';
import { escapeHtml } from '@shared/utils';
import type { editor as MonacoEditor } from 'monaco-editor';
import { MonacoEditorModule } from 'ngx-monaco-editor-v2';
import { filter, finalize, map, Observable, of, switchMap } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { EDITABLE_FILE_TYPES, MAX_DOCUMENT_SIZE } from '../../constants/constants';
import { DisplayedListDocument, DocumentContentScope, DocumentText } from '../../models/document.model';
import { DocumentsApiService } from '../../services/documents-api.service';

type EditorMode = 'preview' | 'edit';

const MONACO_LANGUAGES: Record<string, string> = { md: 'markdown', json: 'json', html: 'html' };

/** The file's text, or null when its bytes are not UTF-8: guessing an encoding would corrupt it on save. */
async function decodeUtf8(blob: Blob): Promise<string | null> {
    try {
        return new TextDecoder('utf-8', { fatal: true }).decode(await blob.arrayBuffer());
    } catch {
        return null;
    }
}

/** Shows a collection document and, for text documents, lets the user edit and save its content. */
@Component({
    selector: 'app-document-content-editor',
    imports: [FormsModule, MonacoEditorModule, BlobPreviewComponent, ButtonComponent],
    templateUrl: './document-content-editor.component.html',
    styleUrls: ['./document-content-editor.component.scss'],
})
export class DocumentContentEditorComponent {
    readonly document = input<DisplayedListDocument | null>(null);
    readonly blob = input<Blob | null>(null);
    readonly fileName = input<string>('');
    /** The stored content changed (saved here, or by someone else): the parent reloads the preview. */
    readonly contentChanged = output<void>();

    private readonly editButton = viewChild('editButton', { read: ElementRef });

    protected readonly mode = signal<EditorMode>('preview');
    protected readonly draft = signal<string>('');
    protected readonly conflict = signal(false);
    protected readonly isSaving = signal(false);
    /** The previewed file's text; null while it loads and for bytes that are not UTF-8. */
    private readonly previewText = signal<string | null>(null);
    private readonly isDecoded = signal(false);
    /** What the editor opened: the text and its hash, read together. */
    private readonly opened = signal<DocumentText | null>(null);

    private readonly isEditableType = computed(() => EDITABLE_FILE_TYPES.includes(this.document()?.file_type ?? ''));
    protected readonly canEdit = computed(
        () =>
            !!this.document()?.document_id &&
            this.isEditableType() &&
            this.previewText() !== null &&
            this.permissions.can(ResourceCode.KnowledgeSources, ActionCode.Update)
    );
    protected readonly isNotUtf8 = computed(
        () => this.isEditableType() && this.isDecoded() && this.previewText() === null
    );
    private readonly isDirty = computed(() => this.draft() !== this.opened()?.text);
    /** An edit the user has not saved; the parent asks before dropping it. */
    readonly hasUnsavedEdit = computed(() => this.mode() === 'edit' && this.isDirty());
    protected readonly monacoOptions = computed<MonacoEditor.IStandaloneEditorConstructionOptions>(() => ({
        theme: 'vs-dark',
        language: MONACO_LANGUAGES[this.document()?.file_type ?? ''] ?? 'plaintext',
        automaticLayout: true,
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        wordWrap: 'on',
    }));

    private readonly documentsApi = inject(DocumentsApiService);
    private readonly permissions = inject(PermissionsService);
    private readonly toast = inject(ToastService);
    private readonly confirmation = inject(ConfirmationDialogService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly injector = inject(Injector);

    constructor() {
        // A new file (another document, or this one reloaded) leaves edit mode and is decoded afresh.
        effect(() => {
            const blob = this.blob();
            this.mode.set('preview');
            this.conflict.set(false);
            this.previewText.set(null);
            this.isDecoded.set(false);
            if (!blob) return;
            void decodeUtf8(blob).then((text) => {
                if (this.blob() !== blob) return;
                this.previewText.set(text);
                this.isDecoded.set(true);
            });
        });
    }

    /** Resolves true when there is nothing unsaved, or the user agrees to drop it. */
    confirmDiscard(): Observable<boolean> {
        if (!this.hasUnsavedEdit()) return of(true);
        return this.confirmation
            .confirm({
                title: 'Discard changes',
                message: 'Your changes to this document will be lost.',
                confirmText: 'Discard',
                cancelText: 'Keep editing',
                type: 'danger',
            })
            .pipe(map((result) => result === true));
    }

    protected startEdit(): void {
        const documentId = this.document()?.document_id;
        const blob = this.blob();
        if (!documentId || !this.canEdit()) return;
        // The text and its hash come from one read, so a save from an older text is refused.
        this.documentsApi
            .getDocumentText(documentId)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (opened) => {
                    if (this.document()?.document_id !== documentId || this.blob() !== blob) return;
                    this.opened.set(opened);
                    this.draft.set(opened.text);
                    this.conflict.set(false);
                    this.mode.set('edit');
                },
                error: (error: HttpErrorResponse) =>
                    this.toast.error(error.error?.message ?? 'Failed to open the document for editing'),
            });
    }

    protected onEditorInit(editor: MonacoEditor.IStandaloneCodeEditor): void {
        editor.focus();
    }

    protected cancelEdit(): void {
        this.confirmDiscard()
            .pipe(filter(Boolean), takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.leaveEdit());
    }

    protected save(): void {
        const opened = this.opened();
        const documentId = this.document()?.document_id;
        if (!opened?.content_hash || !documentId || this.isSaving()) return;
        if (new TextEncoder().encode(this.draft()).length > MAX_DOCUMENT_SIZE) {
            this.toast.error(`The text is larger than ${MAX_DOCUMENT_SIZE / (1024 * 1024)} MB`);
            return;
        }
        const contentHash = opened.content_hash;

        this.isSaving.set(true);
        this.resolveScope(opened)
            .pipe(
                filter((scope): scope is DocumentContentScope => scope !== undefined),
                switchMap((scope) =>
                    this.documentsApi.updateDocumentContent(
                        documentId,
                        this.fileName(),
                        this.draft(),
                        scope,
                        contentHash
                    )
                ),
                finalize(() => this.isSaving.set(false)),
                takeUntilDestroyed(this.destroyRef)
            )
            .subscribe({
                next: () => {
                    this.toast.success('Document saved');
                    this.leaveEdit();
                    this.contentChanged.emit();
                },
                error: (error: HttpErrorResponse) => this.onSaveError(error),
            });
    }

    /** Drops the draft for the version someone else saved. */
    protected reloadCurrentVersion(): void {
        this.conflict.set(false);
        this.leaveEdit();
        this.contentChanged.emit();
    }

    private leaveEdit(): void {
        this.mode.set('preview');
        // The button that had the focus is gone with edit mode; hand it to Edit.
        afterNextRender(() => this.editButton()?.nativeElement.querySelector('button')?.focus(), {
            injector: this.injector,
        });
    }

    /** Asks whether the edit reaches the other collections that use the file; undefined when the user backs out. */
    private resolveScope(opened: DocumentText): Observable<DocumentContentScope | undefined> {
        const sharedWith = opened.shared_with_collections;
        if (!sharedWith.length) return of('this_collection');
        const names = sharedWith
            .map((collection) => `<strong>${escapeHtml(collection.collection_name)}</strong>`)
            .join(', ');
        return this.confirmation
            .confirm({
                title: 'Change the file everywhere?',
                message: `This file is also used in ${names}. Change it there too, or only in this collection?`,
                confirmText: 'Everywhere',
                cancelText: 'Only this collection',
                // Danger, so Enter on the dialog body does not pick the broadest option.
                type: 'danger',
            })
            .pipe(
                map((result): DocumentContentScope | undefined => {
                    if (result === 'close') return undefined;
                    return result ? 'all_collections' : 'this_collection';
                })
            );
    }

    private onSaveError(error: HttpErrorResponse): void {
        if (error.error?.code === 'content_hash_conflict') {
            this.conflict.set(true);
            return;
        }
        this.toast.error(error.error?.message ?? 'Failed to save the document');
    }
}
