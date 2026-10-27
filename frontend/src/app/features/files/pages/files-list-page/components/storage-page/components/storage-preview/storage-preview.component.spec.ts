import { TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../../../../services/auth/permissions.service';
import { StorageItem } from '../../../../../../models/storage.models';
import { StorageApiService } from '../../../../../../services/storage-api.service';
import { StoragePreviewComponent } from './storage-preview.component';

// A folder is never downloaded for preview, so the storage API is never called.
const FOLDER: StorageItem = { id: 10, name: 'reports', path: 'reports/', type: 'folder' };

describe('StoragePreviewComponent "Add to flow" permission', () => {
    beforeEach(() => {
        // jsdom has no ResizeObserver; the button's CollapseOnOverflowDirective needs one once it renders.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
    });

    afterEach(() => vi.unstubAllGlobals());

    // Linking a file to a flow edits the flow, so the server asks for UPDATE on flows, not CREATE on files;
    // the dialog also lists the flows, which needs READ on them.
    it.each([
        {
            granted: 'read and update flows',
            grants: [`${ResourceCode.Flows}:${ActionCode.Read}`, `${ResourceCode.Flows}:${ActionCode.Update}`],
            offered: true,
        },
        {
            granted: 'read flows and create files',
            grants: [`${ResourceCode.Flows}:${ActionCode.Read}`, `${ResourceCode.Files}:${ActionCode.Create}`],
            offered: false,
        },
        {
            granted: 'update flows without reading them',
            grants: [`${ResourceCode.Flows}:${ActionCode.Update}`],
            offered: false,
        },
    ])('offers "Add to flow" only to a user who can read and update flows ($granted)', ({ grants, offered }) => {
        const can = (resource: ResourceCode, action: ActionCode): boolean => grants.includes(`${resource}:${action}`);
        TestBed.configureTestingModule({
            imports: [StoragePreviewComponent],
            providers: [
                { provide: PermissionsService, useValue: { can, canAny: () => false } },
                { provide: StorageApiService, useValue: {} },
            ],
        });
        const fixture = TestBed.createComponent(StoragePreviewComponent);
        fixture.componentRef.setInput('item', FOLDER);
        fixture.detectChanges();

        const button = (fixture.nativeElement as HTMLElement).querySelector('.storage-preview__add-to-flow');

        expect(button !== null).toBe(offered);
    });
});
