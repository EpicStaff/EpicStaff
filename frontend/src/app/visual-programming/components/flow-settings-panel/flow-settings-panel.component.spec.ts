import { DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { FLOW_EDITOR_PREVIEW } from '../../core/providers/flow-editor-preview.token';
import { FlowSettingsPanelComponent } from './flow-settings-panel.component';

function create({ isPreview, canUpdateFlows }: { isPreview: boolean; canUpdateFlows: boolean }) {
    TestBed.configureTestingModule({
        providers: [
            { provide: DialogRef, useValue: { close: vi.fn() } },
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PermissionsService, useValue: { can: () => canUpdateFlows } },
        ],
    });
    return TestBed.createComponent(FlowSettingsPanelComponent).componentInstance;
}

describe('FlowSettingsPanelComponent', () => {
    it('locks the default timezone in the version preview, even for a user who may edit', () => {
        expect(create({ isPreview: true, canUpdateFlows: true })['isReadOnly']()).toBe(true);
    });

    it('locks the default timezone for a read-only user', () => {
        expect(create({ isPreview: false, canUpdateFlows: false })['isReadOnly']()).toBe(true);
    });

    it('keeps the default timezone editable in the live editor for a user who may edit', () => {
        expect(create({ isPreview: false, canUpdateFlows: true })['isReadOnly']()).toBe(false);
    });
});
