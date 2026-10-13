import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { UserSummary } from '@shared/models';

import { StorageItemInfo } from '../../models/storage.models';
import { StorageApiService } from '../../services/storage-api.service';
import { StorageDetailsDialogComponent } from './storage-details-dialog.component';

const IVAN: UserSummary = { id: 1, display_name: 'Ivan Bohun', avatar_url: null };
const OLENA: UserSummary = { id: 2, display_name: 'Olena Pchilka', avatar_url: null };
const CREATED_AT = new Date(2026, 2, 12, 13, 28, 23).toISOString();
const EDITED_AT = new Date(2026, 2, 14, 9, 5, 0).toISOString();

const AUTHORED_FILE: StorageItemInfo = {
    id: 7,
    name: 'Copywriting.txt',
    path: 'Marketing/Copywriting.txt',
    type: 'file',
    size: 214_000,
    modified: EDITED_AT,
    created_by: IVAN,
    created_at: CREATED_AT,
    last_edited_by: OLENA,
    last_edited_at: EDITED_AT,
};

// A folder with no tracked authorship: the storage API sends nulls for every field.
const UNTRACKED_FOLDER: StorageItemInfo = {
    id: null,
    name: 'Marketing',
    path: 'Marketing/',
    type: 'folder',
    modified: EDITED_AT,
    created_by: null,
    created_at: null,
    last_edited_by: null,
    last_edited_at: null,
};

// A storage item built without the optional authorship keys at all.
const FILE_WITHOUT_AUTHORSHIP: StorageItemInfo = {
    name: 'Blog.pdf',
    path: 'Marketing/Blog.pdf',
    type: 'file',
};

interface RenderedDialog {
    title: string;
    /** Each body section in order: `authorship` for the authorship block, otherwise the section title. */
    sections: string[];
    names: string[];
}

function render(data: StorageItemInfo): RenderedDialog {
    TestBed.configureTestingModule({
        providers: [
            { provide: DIALOG_DATA, useValue: { ...data, usedIn: [] } },
            { provide: DialogRef, useValue: { close: vi.fn() } },
            { provide: StorageApiService, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
        ],
    });
    const fixture = TestBed.createComponent(StorageDetailsDialogComponent);
    fixture.detectChanges();
    const host = fixture.nativeElement as HTMLElement;
    const sections = Array.from(
        host.querySelectorAll<HTMLElement>('.storage-details-dialog__content > .storage-details-dialog__section')
    ).map((section) =>
        section.querySelector('app-authorship-details')
            ? 'authorship'
            : (section.querySelector('.storage-details-dialog__section-title')?.textContent?.trim() ?? '')
    );
    return {
        title: host.querySelector('.storage-details-dialog__title')?.textContent?.trim() ?? '',
        sections,
        names: Array.from(host.querySelectorAll<HTMLElement>('.authorship-details__name')).map(
            (name) => name.textContent?.trim() ?? ''
        ),
    };
}

describe('StorageDetailsDialogComponent authorship', () => {
    it('shows the owner and last editor of a file above the existing sections', () => {
        expect(render(AUTHORED_FILE)).toEqual({
            title: 'File Details',
            sections: ['authorship', 'DATA', 'STORAGE PATH', 'USED IN FLOWS'],
            names: ['Ivan Bohun', 'Olena Pchilka'],
        });
    });

    it('shows the authorship block of a folder with untracked authorship as dashes', () => {
        expect(render(UNTRACKED_FOLDER)).toEqual({
            title: 'Folder Details',
            sections: ['authorship', 'DATA', 'STORAGE PATH', 'USED IN FLOWS'],
            names: ['—', '—'],
        });
    });

    it('treats authorship fields missing from the item like null ones', () => {
        expect(render(FILE_WITHOUT_AUTHORSHIP).names).toEqual(['—', '—']);
    });
});
