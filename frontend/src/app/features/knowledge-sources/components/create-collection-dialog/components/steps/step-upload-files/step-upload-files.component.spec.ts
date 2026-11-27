import { UpperCasePipe } from '@angular/common';
import { NO_ERRORS_SCHEMA, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { ValidationErrorsComponent } from '@shared/components';
import { of, Subject } from 'rxjs';

import { ToastService } from '../../../../../../../services/notifications';
import { COLLECTION_DESCRIPTION_MAX_LENGTH } from '../../../../../constants/constants';
import { CollectionStatus, CreateCollectionDtoResponse } from '../../../../../models/collection.model';
import { CollectionDocument, DisplayedListDocument } from '../../../../../models/document.model';
import { CollectionsStorageService } from '../../../../../services/collections-storage.service';
import { DocumentsApiService } from '../../../../../services/documents-api.service';
import { DocumentsStorageService } from '../../../../../services/documents-storage.service';
import { StepUploadFilesComponent } from './step-upload-files.component';

const COLLECTION: CreateCollectionDtoResponse = {
    collection_id: 7,
    collection_name: 'CoreStack',
    description: null,
    status: CollectionStatus.EMPTY,
    document_count: 0,
    rag_configurations: [],
    created_at: '2026-03-12T13:28:23Z',
    updated_at: '2026-03-12T13:28:23Z',
    created_by: null,
    last_edited_by: null,
    last_edited_at: null,
};

/** The file upload and preview parts are not rendered; `storedDocuments` stands in for the document cache. */
function render(
    storedDocuments: WritableSignal<CollectionDocument[]> = signal([])
): ComponentFixture<StepUploadFilesComponent> {
    TestBed.configureTestingModule({
        providers: [
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            { provide: CollectionsStorageService, useValue: { updateCollectionById: vi.fn(() => of(COLLECTION)) } },
            { provide: DocumentsApiService, useValue: { previewDocumentBlob: vi.fn(() => of(new Blob())) } },
            {
                provide: DocumentsStorageService,
                useValue: { documents: storedDocuments, uploadingDocuments: signal([]) },
            },
        ],
    });
    TestBed.overrideComponent(StepUploadFilesComponent, {
        set: { imports: [ReactiveFormsModule, ValidationErrorsComponent, UpperCasePipe], schemas: [NO_ERRORS_SCHEMA] },
    });
    const fixture = TestBed.createComponent(StepUploadFilesComponent);
    fixture.componentRef.setInput('collection', COLLECTION);
    fixture.detectChanges();
    return fixture;
}

describe('StepUploadFilesComponent guidance for agents', () => {
    it('accepts guidance up to the backend limit and rejects longer guidance', () => {
        const { description } = render().componentInstance;

        description.setValue('x'.repeat(COLLECTION_DESCRIPTION_MAX_LENGTH));
        expect(description.valid).toBe(true);

        description.setValue('x'.repeat(COLLECTION_DESCRIPTION_MAX_LENGTH + 1));
        expect(description.hasError('maxlength')).toBe(true);
    });
});

const NOTES: CollectionDocument = {
    document_id: 1,
    file_name: 'notes.txt',
    file_size: 8,
    file_type: 'txt',
    source_collection: COLLECTION.collection_id,
};
const README: CollectionDocument = { ...NOTES, document_id: 2, file_name: 'readme.md', file_type: 'md' };

function listed(document: CollectionDocument): DisplayedListDocument {
    return { ...document, isValidType: true, isValidSize: true };
}

describe('StepUploadFilesComponent selected document', () => {
    it('keeps the open document when the user keeps an unsaved edit', () => {
        const step = render(signal([NOTES, README])).componentInstance;
        step.selectedDocument.set(listed(NOTES));
        const answer = new Subject<boolean>();
        vi.spyOn(step, 'confirmLeave').mockReturnValue(answer);

        step.selectDocument(listed(README));
        answer.next(false);

        expect(step.selectedDocument()?.document_id).toBe(NOTES.document_id);
    });

    it('opens another document once the unsaved edit is dropped', () => {
        const step = render(signal([NOTES, README])).componentInstance;
        step.selectedDocument.set(listed(NOTES));
        vi.spyOn(step, 'confirmLeave').mockReturnValue(of(true));

        step.selectDocument(listed(README));

        expect(step.selectedDocument()?.document_id).toBe(README.document_id);
    });

    it('does not ask when the open document is picked again', () => {
        const step = render(signal([NOTES])).componentInstance;
        const notes = listed(NOTES);
        step.selectedDocument.set(notes);
        const confirmLeave = vi.spyOn(step, 'confirmLeave');

        step.selectDocument(notes);

        expect(confirmLeave).not.toHaveBeenCalled();
    });

    it('closes the open document once it is deleted', () => {
        const storedDocuments = signal([NOTES, README]);
        const fixture = render(storedDocuments);
        fixture.componentInstance.selectedDocument.set(listed(NOTES));
        fixture.detectChanges();

        storedDocuments.set([README]);
        fixture.detectChanges();

        expect(fixture.componentInstance.selectedDocument()).toBeNull();
    });
});
