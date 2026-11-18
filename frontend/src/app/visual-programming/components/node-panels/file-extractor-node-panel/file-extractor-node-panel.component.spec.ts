import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ActivePermissions, NodeType, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { FILES_READ_LOCK_MESSAGE } from '../../../core/helpers/storage-grants.util';
import { FileExtractorNodeModel } from '../../../core/models/node.model';
import { FileExtractorNodePanelComponent } from './file-extractor-node-panel.component';

const NODE: FileExtractorNodeModel = {
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
};

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

function render(): ComponentFixture<FileExtractorNodePanelComponent> {
    const fixture = TestBed.createComponent(FileExtractorNodePanelComponent);
    fixture.componentRef.setInput('node', NODE);
    fixture.detectChanges();
    return fixture;
}

function banner(fixture: ComponentFixture<FileExtractorNodePanelComponent>): string | null {
    const element = (fixture.nativeElement as HTMLElement).querySelector('app-hint-message');
    return element ? (element.textContent ?? '').trim() : null;
}

describe('FileExtractorNodePanelComponent without Files:Read', () => {
    beforeEach(() => TestBed.configureTestingModule({ providers: [provideHttpClient()] }));

    it('makes the whole panel read-only and says why', () => {
        grantFilesPermissions([ActionCode.Create, ActionCode.Update]);

        const fixture = render();

        expect(banner(fixture)).toBe(FILES_READ_LOCK_MESSAGE);
        expect(fixture.componentInstance.isReadOnly()).toBe(true);
        expect(fixture.componentInstance.form.disabled).toBe(true);
    });

    it('saves nothing from a locked panel', () => {
        grantFilesPermissions([ActionCode.Create]);
        const fixture = render();

        expect(fixture.componentInstance.onSave()).toBeNull();
        expect(fixture.componentInstance.onSaveSilently()).toBeNull();
    });

    it('does not lock a user who holds Files:Read, and shows no grant box', () => {
        grantFilesPermissions([ActionCode.Read]);

        const fixture = render();

        expect(banner(fixture)).toBeNull();
        expect(fixture.componentInstance.isReadOnly()).toBe(false);
        expect(fixture.componentInstance.form.enabled).toBe(true);
        expect(fixture.nativeElement.querySelector('app-storage-grants-field')).toBeNull();
    });

    it('does not lock before the permissions are loaded, and locks once they arrive', () => {
        const fixture = render();
        expect(banner(fixture)).toBeNull();

        grantFilesPermissions([]);
        fixture.detectChanges();

        expect(banner(fixture)).toBe(FILES_READ_LOCK_MESSAGE);
        expect(fixture.componentInstance.form.disabled).toBe(true);
    });

    it('opens the form once Files:Read arrives', () => {
        grantFilesPermissions([]);
        const fixture = render();
        expect(fixture.componentInstance.form.disabled).toBe(true);

        grantFilesPermissions([ActionCode.Read]);
        fixture.detectChanges();

        expect(banner(fixture)).toBeNull();
        expect(fixture.componentInstance.form.enabled).toBe(true);
    });
});
