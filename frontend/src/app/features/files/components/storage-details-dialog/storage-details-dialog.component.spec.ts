import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ConfirmationDialogService } from '@shared/components';
import { ActionCode, ResourceCode, UserSummary } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { StorageGraph, StorageItemInfo } from '../../models/storage.models';
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

const ALL_PERMISSIONS = (): boolean => true;

function mount(
    data: StorageItemInfo,
    can: (resource: ResourceCode, action: ActionCode) => boolean = ALL_PERMISSIONS,
    usedIn: StorageGraph[] = []
): HTMLElement {
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can } },
            { provide: DIALOG_DATA, useValue: { ...data, usedIn } },
            { provide: DialogRef, useValue: { close: vi.fn() } },
            { provide: StorageApiService, useValue: {} },
            { provide: ConfirmationDialogService, useValue: {} },
        ],
    });
    const fixture = TestBed.createComponent(StorageDetailsDialogComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

function render(
    data: StorageItemInfo,
    can: (resource: ResourceCode, action: ActionCode) => boolean = ALL_PERMISSIONS
): RenderedDialog {
    const host = mount(data, can);
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

describe('StorageDetailsDialogComponent used in flows', () => {
    it('hides the flows the item is used in from a user who cannot read flows', () => {
        const canAllButReadFlows = (resource: ResourceCode, action: ActionCode): boolean =>
            !(resource === ResourceCode.Flows && action === ActionCode.Read);

        expect(render(AUTHORED_FILE, canAllButReadFlows).sections).toEqual(['authorship', 'DATA', 'STORAGE PATH']);
    });

    // Removing a file from a flow edits the flow, so the server asks for UPDATE on flows, not DELETE on files.
    it.each([
        {
            granted: 'read and update flows',
            grants: [`${ResourceCode.Flows}:${ActionCode.Read}`, `${ResourceCode.Flows}:${ActionCode.Update}`],
            expectedButtons: 2,
        },
        {
            granted: 'read flows and delete files',
            grants: [`${ResourceCode.Flows}:${ActionCode.Read}`, `${ResourceCode.Files}:${ActionCode.Delete}`],
            expectedButtons: 0,
        },
    ])(
        'offers to remove the item from each flow only to a user who can update flows ($granted)',
        ({ grants, expectedButtons }) => {
            const can = (resource: ResourceCode, action: ActionCode): boolean =>
                grants.includes(`${resource}:${action}`);
            const usedIn: StorageGraph[] = [
                { id: 1, name: 'Sales' },
                { id: 2, name: 'Support' },
            ];

            const host = mount(AUTHORED_FILE, can, usedIn);

            expect(host.querySelectorAll('.storage-details-dialog__chip-remove').length).toBe(expectedButtons);
        }
    );
});
