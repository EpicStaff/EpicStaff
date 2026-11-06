import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ActivePermissions, NodeType, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { FileExtractorNodeModel } from '../../../core/models/node.model';
import { StorageGrants } from '../../../core/models/storage-grants.model';
import { FileExtractorNodePanelComponent } from './file-extractor-node-panel.component';

const ALL_FILES = [ActionCode.Read, ActionCode.Create, ActionCode.Update, ActionCode.Delete];
const WRITE_AND_DELETE: StorageGrants = { read: false, write: true, delete: true };

function node(storageGrants: StorageGrants | undefined): FileExtractorNodeModel {
    return {
        id: 'extractor-1',
        backendId: 4,
        nodeUuid: null,
        type: NodeType.FILE_EXTRACTOR,
        node_name: 'Extract',
        data: undefined,
        position: { x: 0, y: 0 },
        ports: null,
        size: { width: 200, height: 100 },
        input_map: {},
        output_variable_path: null,
        storageGrants,
    };
}

function grantFilesPermissions(files: ActionCode[]): void {
    TestBed.inject(PermissionsService).setActivePermissions({
        org_id: 1,
        is_superadmin: false,
        role: { id: 1, name: 'Custom' },
        permissions: {
            [ResourceCode.Files]: files,
            [ResourceCode.Flows]: [ActionCode.Update],
        } as unknown as ActivePermissions['permissions'],
    });
}

function render(storageGrants: StorageGrants | undefined): ComponentFixture<FileExtractorNodePanelComponent> {
    const fixture = TestBed.createComponent(FileExtractorNodePanelComponent);
    fixture.componentRef.setInput('node', node(storageGrants));
    fixture.detectChanges();
    return fixture;
}

function banner(fixture: ComponentFixture<FileExtractorNodePanelComponent>): string | null {
    const element = (fixture.nativeElement as HTMLElement).querySelector('app-hint-message');
    return element ? (element.textContent ?? '').trim() : null;
}

describe('BaseSidePanel storage grant lock', () => {
    beforeEach(() => TestBed.configureTestingModule({ providers: [provideHttpClient()] }));

    it('locks the panel and shows the banner when the grants exceed the user permissions', () => {
        grantFilesPermissions([ActionCode.Read, ActionCode.Create]);

        const fixture = render(WRITE_AND_DELETE);

        expect(banner(fixture)).toBe(
            "This code runs with Files: Update, Files: Delete, which you don't have. Contact an admin to change it."
        );
        expect(fixture.componentInstance.isReadOnly()).toBe(true);
        expect(fixture.componentInstance.form.disabled).toBe(true);
    });

    it('does not lock a user who holds every permission the grants stand for', () => {
        grantFilesPermissions(ALL_FILES);

        const fixture = render(WRITE_AND_DELETE);

        expect(banner(fixture)).toBeNull();
        expect(fixture.componentInstance.isReadOnly()).toBe(false);
        expect(fixture.componentInstance.form.enabled).toBe(true);
    });

    it('does not lock a node with grants that are off or not configured', () => {
        grantFilesPermissions([]);

        expect(banner(render({ read: false, write: false, delete: false }))).toBeNull();
        expect(banner(render({ read: null, write: null, delete: null }))).toBeNull();
    });

    it('does not lock before the permissions are loaded, and locks once they arrive', () => {
        const fixture = render(WRITE_AND_DELETE);

        expect(banner(fixture)).toBeNull();
        expect(fixture.componentInstance.storageGrantLock()).toBeNull();

        grantFilesPermissions([ActionCode.Read]);
        fixture.detectChanges();

        expect(banner(fixture)).toContain('Files: Create, Files: Update, Files: Delete');
        expect(fixture.componentInstance.form.disabled).toBe(true);
    });

    it('enables the form once the permissions grow to cover the grants', () => {
        grantFilesPermissions([ActionCode.Read]);
        const fixture = render(WRITE_AND_DELETE);
        expect(fixture.componentInstance.form.disabled).toBe(true);

        grantFilesPermissions(ALL_FILES);
        fixture.detectChanges();

        expect(banner(fixture)).toBeNull();
        expect(fixture.componentInstance.form.enabled).toBe(true);
    });
});
