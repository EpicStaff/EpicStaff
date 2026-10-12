import { UpperCasePipe } from '@angular/common';
import { NO_ERRORS_SCHEMA, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { ValidationErrorsComponent } from '@shared/components';
import { of } from 'rxjs';

import { ToastService } from '../../../../../../../services/notifications';
import { COLLECTION_DESCRIPTION_MAX_LENGTH } from '../../../../../constants/constants';
import { CollectionStatus, CreateCollectionDtoResponse } from '../../../../../models/collection.model';
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

/** Only the guidance field matters here, so the file upload and preview parts are not rendered. */
function render(): ComponentFixture<StepUploadFilesComponent> {
    TestBed.configureTestingModule({
        providers: [
            { provide: ToastService, useValue: { success: vi.fn(), error: vi.fn() } },
            { provide: CollectionsStorageService, useValue: { updateCollectionById: vi.fn(() => of(COLLECTION)) } },
            { provide: DocumentsApiService, useValue: {} },
            {
                provide: DocumentsStorageService,
                useValue: { documents: signal([]), uploadingDocuments: signal([]) },
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
