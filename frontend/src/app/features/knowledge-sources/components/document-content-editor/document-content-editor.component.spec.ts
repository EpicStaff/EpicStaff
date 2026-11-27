import { HttpErrorResponse } from '@angular/common/http';
import { DebugElement, NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ConfirmationDialogService, ConfirmationResultWithOptions } from '@shared/components';
import { firstValueFrom, Observable, of, Subject, throwError } from 'rxjs';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { MAX_DOCUMENT_SIZE } from '../../constants/constants';
import { DisplayedListDocument, DocumentDetail, DocumentText } from '../../models/document.model';
import { DocumentsApiService } from '../../services/documents-api.service';
import { DocumentContentEditorComponent } from './document-content-editor.component';

const TEXT_DOCUMENT: DisplayedListDocument = {
    document_id: 5,
    file_name: 'notes.txt',
    file_size: 8,
    file_type: 'txt',
    source_collection: 2,
    isValidType: true,
    isValidSize: true,
};

const OPENED: DocumentText = {
    document_id: 5,
    file_name: 'notes.txt',
    file_size: 8,
    file_type: 'txt',
    source_collection: 2,
    collection_name: 'Docs',
    content_hash: 'a'.repeat(64),
    shared_with_collections: [],
    text: 'old text',
};

interface Setup {
    canUpdate?: boolean;
    opened?: Partial<DocumentText>;
    getText?: () => Observable<DocumentText>;
    update?: () => Observable<DocumentDetail>;
    confirmResult?: boolean | 'close';
    scopeResult?: ConfirmationResultWithOptions | 'close';
    sharedWith?: string[];
}

async function settle(fixture: ComponentFixture<DocumentContentEditorComponent>): Promise<void> {
    fixture.detectChanges();
    // The file is decoded asynchronously; let that finish before asserting.
    await new Promise((resolve) => setTimeout(resolve));
    fixture.detectChanges();
}

async function render(document: DisplayedListDocument, bytes: BlobPart, setup: Setup = {}) {
    const opened: DocumentText = {
        ...OPENED,
        shared_with_collections: (setup.sharedWith ?? []).map((name, index) => ({
            collection_id: 100 + index,
            collection_name: name,
        })),
        ...setup.opened,
    };
    const api = {
        getDocumentText: vi.fn<DocumentsApiService['getDocumentText']>(setup.getText ?? (() => of(opened))),
        updateDocumentContent: vi.fn<DocumentsApiService['updateDocumentContent']>(
            setup.update ?? (() => of<DocumentDetail>(opened))
        ),
    };
    const toast = { success: vi.fn(), error: vi.fn() };
    const confirm = vi.fn<ConfirmationDialogService['confirm']>(() => of(setup.confirmResult ?? true));
    const confirmWithOptions = vi.fn<ConfirmationDialogService['confirmWithOptions']>(() =>
        of(setup.scopeResult ?? { confirmed: true, checked: false })
    );
    TestBed.configureTestingModule({
        providers: [
            { provide: DocumentsApiService, useValue: api },
            { provide: ToastService, useValue: toast },
            { provide: ConfirmationDialogService, useValue: { confirm, confirmWithOptions } },
            { provide: PermissionsService, useValue: { can: () => setup.canUpdate ?? true } },
        ],
    });
    TestBed.overrideComponent(DocumentContentEditorComponent, { set: { imports: [], schemas: [NO_ERRORS_SCHEMA] } });
    const fixture = TestBed.createComponent(DocumentContentEditorComponent);
    fixture.componentRef.setInput('document', document);
    fixture.componentRef.setInput('blob', new Blob([bytes]));
    fixture.componentRef.setInput('fileName', document.file_name);
    await settle(fixture);

    const button = (label: string): DebugElement | undefined =>
        fixture.debugElement
            .queryAll(By.css('app-button'))
            .find((element) => element.nativeElement.textContent.trim() === label);
    const click = (label: string): void => {
        const target = button(label);
        if (!target) throw new Error(`No "${label}" button`);
        target.triggerEventHandler('click');
        fixture.detectChanges();
    };
    const monaco = (): DebugElement | null => fixture.debugElement.query(By.css('ngx-monaco-editor'));
    const type = (text: string): void => {
        monaco()!.triggerEventHandler('ngModelChange', text);
        fixture.detectChanges();
    };
    const text = (): string => fixture.nativeElement.textContent;

    return { fixture, api, toast, confirm, confirmWithOptions, button, click, monaco, type, text };
}

describe('DocumentContentEditorComponent', () => {
    describe('offering the editor', () => {
        it('offers Edit for a UTF-8 text document the user may update', async () => {
            const { button } = await render(TEXT_DOCUMENT, 'old text');

            expect(button('Edit')).toBeDefined();
        });

        it('shows the preview without the view-only badge', async () => {
            const { fixture } = await render(TEXT_DOCUMENT, 'old text');

            const preview = fixture.debugElement.query(By.css('app-blob-preview'));

            expect(preview.properties['showBadge']).toBe(false);
        });

        it('does not offer Edit for a pdf', async () => {
            const { button } = await render({ ...TEXT_DOCUMENT, file_name: 'a.pdf', file_type: 'pdf' }, 'x');

            expect(button('Edit')).toBeUndefined();
        });

        it('explains why a file that is not UTF-8 cannot be edited', async () => {
            const { button, text } = await render(TEXT_DOCUMENT, new Uint8Array([0xc3, 0x28]));

            expect(button('Edit')).toBeUndefined();
            expect(text()).toContain('not UTF-8');
        });

        it('does not offer Edit without update permission', async () => {
            const { button } = await render(TEXT_DOCUMENT, 'old text', { canUpdate: false });

            expect(button('Edit')).toBeUndefined();
        });

        it('does not explain the encoding to a user who may not edit anyway', async () => {
            const { text } = await render(TEXT_DOCUMENT, new Uint8Array([0xc3, 0x28]), { canUpdate: false });

            expect(text()).not.toContain('not UTF-8');
        });

        it('ignores a decoded file once the preview moved on', async () => {
            const { fixture, button } = await render(TEXT_DOCUMENT, 'old text');
            fixture.componentRef.setInput('blob', new Blob(['next text']));
            fixture.detectChanges();
            fixture.componentRef.setInput('blob', null);

            await settle(fixture);

            expect(button('Edit')).toBeUndefined();
        });
    });

    describe('opening the editor', () => {
        it('edits the text the server returned with its hash', async () => {
            const { click, monaco, api } = await render(TEXT_DOCUMENT, 'old text', { opened: { text: 'server text' } });

            click('Edit');

            expect(api.getDocumentText).toHaveBeenCalledWith(5);
            expect(monaco()?.properties['ngModel']).toBe('server text');
        });

        it('stays in preview when the text arrives for a document no longer shown', async () => {
            const response = new Subject<DocumentText>();
            const { fixture, click, monaco } = await render(TEXT_DOCUMENT, 'old text', { getText: () => response });

            click('Edit');
            fixture.componentRef.setInput('document', { ...TEXT_DOCUMENT, document_id: 6 });
            fixture.detectChanges();
            response.next(OPENED);
            fixture.detectChanges();

            expect(monaco()).toBeNull();
        });

        it('leaves edit mode when a new file is shown', async () => {
            const { fixture, click, monaco } = await render(TEXT_DOCUMENT, 'old text');
            click('Edit');

            fixture.componentRef.setInput('blob', new Blob(['reloaded']));
            await settle(fixture);

            expect(monaco()).toBeNull();
        });
    });

    describe('saving', () => {
        it('saves the draft for this collection and asks the parent to reload', async () => {
            const { fixture, click, type, monaco, api } = await render(TEXT_DOCUMENT, 'old text');
            const changed = vi.fn();
            fixture.componentInstance.contentChanged.subscribe(changed);

            click('Edit');
            type('new text');
            click('Save');

            expect(api.updateDocumentContent).toHaveBeenCalledWith(
                5,
                'notes.txt',
                'new text',
                'this_collection',
                OPENED.content_hash
            );
            expect(changed).toHaveBeenCalled();
            expect(monaco()).toBeNull();
        });

        it('sends one request when Save is clicked twice', async () => {
            const pending = new Subject<DocumentDetail>();
            const { click, type, button, api } = await render(TEXT_DOCUMENT, 'old text', { update: () => pending });

            click('Edit');
            type('new text');
            click('Save');
            click('Save');

            expect(api.updateDocumentContent).toHaveBeenCalledTimes(1);
            expect(button('Save')?.properties['disabled']).toBe(true);
        });

        it('refuses a text larger than the upload limit', async () => {
            const { click, type, api, toast } = await render(TEXT_DOCUMENT, 'old text');

            click('Edit');
            type('a'.repeat(MAX_DOCUMENT_SIZE + 1));
            click('Save');

            expect(api.updateDocumentContent).not.toHaveBeenCalled();
            expect(toast.error).toHaveBeenCalled();
        });

        it('keeps the draft and offers the current version when someone else saved first', async () => {
            const conflict = new HttpErrorResponse({ status: 409, error: { code: 'content_hash_conflict' } });
            const { fixture, click, type, monaco, toast, button } = await render(TEXT_DOCUMENT, 'old text', {
                update: () => throwError(() => conflict),
            });

            click('Edit');
            type('my edit');
            click('Save');

            expect(monaco()?.properties['ngModel']).toBe('my edit');
            expect(fixture.debugElement.query(By.css('[role="alert"]')).nativeElement.textContent).toContain(
                'changed after you opened it'
            );
            expect(button('Load current version')).toBeDefined();
            expect(toast.error).not.toHaveBeenCalled();
        });

        it('drops the draft and reloads when the user loads the current version', async () => {
            const conflict = new HttpErrorResponse({ status: 409, error: { code: 'content_hash_conflict' } });
            const { fixture, click, type, monaco } = await render(TEXT_DOCUMENT, 'old text', {
                update: () => throwError(() => conflict),
            });
            const changed = vi.fn();
            fixture.componentInstance.contentChanged.subscribe(changed);

            click('Edit');
            type('my edit');
            click('Save');
            click('Load current version');

            expect(changed).toHaveBeenCalled();
            expect(monaco()).toBeNull();
        });

        it("shows the server's message when the document is being indexed", async () => {
            const indexing = new HttpErrorResponse({
                status: 409,
                error: { code: 'document_indexing_in_progress', message: 'Being indexed in: Docs' },
            });
            const { click, type, monaco, toast } = await render(TEXT_DOCUMENT, 'old text', {
                update: () => throwError(() => indexing),
            });

            click('Edit');
            type('my edit');
            click('Save');

            expect(toast.error).toHaveBeenCalledWith('Being indexed in: Docs');
            expect(monaco()).not.toBeNull();
        });
    });

    describe('choosing where the change goes', () => {
        it('saves for this collection without asking when no other collection uses the file', async () => {
            const { click, type, api, confirmWithOptions } = await render(TEXT_DOCUMENT, 'old text');

            click('Edit');
            type('new text');
            click('Save');

            expect(confirmWithOptions).not.toHaveBeenCalled();
            expect(api.updateDocumentContent.mock.calls[0][3]).toBe('this_collection');
        });

        it('offers to change the other collections too, unchecked by default', async () => {
            const { click, type, confirmWithOptions } = await render(TEXT_DOCUMENT, 'old text', {
                sharedWith: ['Copies'],
            });

            click('Edit');
            type('new text');
            click('Save');

            const options = confirmWithOptions.mock.calls[0]?.[0];
            expect(options?.checkbox?.label).toBeTruthy();
            expect(options?.checkbox?.checked).toBeFalsy();
        });

        it('changes the file everywhere when the user checks the other collections', async () => {
            const { click, type, api } = await render(TEXT_DOCUMENT, 'old text', {
                sharedWith: ['Copies'],
                scopeResult: { confirmed: true, checked: true },
            });

            click('Edit');
            type('new text');
            click('Save');

            expect(api.updateDocumentContent.mock.calls[0][3]).toBe('all_collections');
        });

        it('changes the file only here when the user saves without checking', async () => {
            const { click, type, api } = await render(TEXT_DOCUMENT, 'old text', {
                sharedWith: ['Copies'],
                scopeResult: { confirmed: true, checked: false },
            });

            click('Edit');
            type('new text');
            click('Save');

            expect(api.updateDocumentContent.mock.calls[0][3]).toBe('this_collection');
        });

        it.each<[string, ConfirmationResultWithOptions | 'close']>([
            ['cancelled', { confirmed: false, checked: true }],
            ['closed', 'close'],
        ])('saves nothing and stays editable when the dialog is %s', async (_, scopeResult) => {
            const { click, type, api, monaco, button } = await render(TEXT_DOCUMENT, 'old text', {
                sharedWith: ['Copies'],
                scopeResult,
            });

            click('Edit');
            type('new text');
            click('Save');

            expect(api.updateDocumentContent).not.toHaveBeenCalled();
            expect(monaco()).not.toBeNull();
            expect(button('Save')?.properties['disabled']).toBe(false);
        });

        it('escapes collection names in the dialog', async () => {
            const { click, type, confirmWithOptions } = await render(TEXT_DOCUMENT, 'old text', {
                sharedWith: ['<b>Copies</b>'],
                scopeResult: 'close',
            });

            click('Edit');
            type('new text');
            click('Save');

            const message = confirmWithOptions.mock.calls[0]?.[0].message;
            expect(message).toContain('&lt;b&gt;Copies&lt;/b&gt;');
            expect(message).not.toContain('<b>Copies</b>');
        });
    });

    describe('unsaved changes', () => {
        it('asks before discarding and keeps editing when declined', async () => {
            const { click, type, monaco, confirm } = await render(TEXT_DOCUMENT, 'old text', { confirmResult: false });

            click('Edit');
            type('my edit');
            click('Cancel');

            expect(confirm).toHaveBeenCalled();
            expect(monaco()).not.toBeNull();
        });

        it('leaves edit mode at once when nothing changed', async () => {
            const { click, monaco, confirm } = await render(TEXT_DOCUMENT, 'old text');

            click('Edit');
            click('Cancel');

            expect(confirm).not.toHaveBeenCalled();
            expect(monaco()).toBeNull();
        });

        it('lets the parent leave without asking when nothing changed', async () => {
            const { fixture, click, confirm } = await render(TEXT_DOCUMENT, 'old text');
            click('Edit');

            const leave = await firstValueFrom(fixture.componentInstance.confirmDiscard());

            expect(leave).toBe(true);
            expect(confirm).not.toHaveBeenCalled();
        });

        it("asks before the parent drops an unsaved edit and returns the user's answer", async () => {
            const { fixture, click, type, confirm } = await render(TEXT_DOCUMENT, 'old text', {
                confirmResult: 'close',
            });
            click('Edit');
            type('my edit');

            const leave = await firstValueFrom(fixture.componentInstance.confirmDiscard());

            expect(fixture.componentInstance.hasUnsavedEdit()).toBe(true);
            expect(confirm).toHaveBeenCalled();
            expect(leave).toBe(false);
        });
    });
});
