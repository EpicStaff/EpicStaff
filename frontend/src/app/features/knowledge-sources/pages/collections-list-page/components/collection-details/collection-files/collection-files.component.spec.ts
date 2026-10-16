import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';

import { PermissionsService } from '../../../../../../../services/auth/permissions.service';
import { DisplayedListDocument } from '../../../../../models/document.model';
import { DocumentsStorageService } from '../../../../../services/documents-storage.service';
import { CollectionFilesComponent } from './collection-files.component';

function document(overrides: Partial<DisplayedListDocument>): DisplayedListDocument {
    return {
        file_name: 'file',
        file_size: 1,
        source_collection: 1,
        isValidType: true,
        isValidSize: true,
        ...overrides,
    };
}

const DOCUMENTS: DisplayedListDocument[] = [
    document({ document_id: 1, file_name: 'a.pdf', file_type: 'pdf' }),
    document({ document_id: 2, file_name: 'b.txt', file_type: 'txt' }),
    document({ document_id: 3, file_name: 'c.pdf', file_type: 'pdf' }),
    document({ file_name: 'd.exe', isValidType: false }),
];

function render(): ComponentFixture<CollectionFilesComponent> {
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can: () => true } },
            { provide: DocumentsStorageService, useValue: { isDeleting: () => false } },
            { provide: ConfirmationDialogService, useValue: {} },
        ],
    });
    const fixture = TestBed.createComponent(CollectionFilesComponent);
    fixture.componentRef.setInput('documents', DOCUMENTS);
    fixture.detectChanges();
    return fixture;
}

function fileNames(fixture: ComponentFixture<CollectionFilesComponent>): string[] {
    const host = fixture.nativeElement as HTMLElement;
    return Array.from(host.querySelectorAll('.files__name')).map((name) => name.textContent?.trim() ?? '');
}

describe('CollectionFilesComponent filter by type', () => {
    it('lists every file without a filter', () => {
        expect(fileNames(render())).toEqual(['a.pdf', 'b.txt', 'c.pdf', 'd.exe']);
    });

    it('lists only the stored files of the chosen type, keeping rejected files visible', () => {
        const fixture = render();

        fixture.componentRef.setInput('fileTypeFilter', 'pdf');
        fixture.detectChanges();

        expect(fileNames(fixture)).toEqual(['a.pdf', 'c.pdf', 'd.exe']);
    });

    it('lists every file again once the filter goes back to all types, the documents themselves untouched', () => {
        const fixture = render();

        fixture.componentRef.setInput('fileTypeFilter', 'txt');
        fixture.detectChanges();
        expect(fixture.componentInstance.documents()).toEqual(DOCUMENTS);

        fixture.componentRef.setInput('fileTypeFilter', null);
        fixture.detectChanges();

        expect(fileNames(fixture)).toEqual(['a.pdf', 'b.txt', 'c.pdf', 'd.exe']);
    });
});
