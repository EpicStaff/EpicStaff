import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { FLOW_EDITOR_PREVIEW } from '../providers/flow-editor-preview.token';
import { IfFlowEditableDirective } from './if-flow-editable.directive';

@Component({
    imports: [IfFlowEditableDirective],
    template: `<button *appIfFlowEditable>Editing</button>`,
})
class HostComponent {}

function renderedButton({ isPreview, canUpdateFlows }: { isPreview: boolean; canUpdateFlows: boolean }) {
    TestBed.configureTestingModule({
        providers: [
            { provide: FLOW_EDITOR_PREVIEW, useValue: isPreview },
            { provide: PermissionsService, useValue: { can: () => canUpdateFlows } },
        ],
    });
    const fixture = TestBed.createComponent(HostComponent);
    fixture.detectChanges();
    return (fixture.nativeElement as HTMLElement).querySelector('button');
}

describe('IfFlowEditableDirective', () => {
    it('shows editing controls to a user who may edit, in the live editor', () => {
        expect(renderedButton({ isPreview: false, canUpdateFlows: true })).not.toBeNull();
    });

    it('hides them in a version preview, even for a user who may edit', () => {
        expect(renderedButton({ isPreview: true, canUpdateFlows: true })).toBeNull();
    });

    it('hides them from a user without Flows:Update', () => {
        expect(renderedButton({ isPreview: false, canUpdateFlows: false })).toBeNull();
    });
});
