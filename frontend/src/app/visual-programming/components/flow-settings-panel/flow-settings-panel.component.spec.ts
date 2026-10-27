import { DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { FLOW_EDITOR_PREVIEW } from '../../core/providers/flow-editor-preview.token';
import { FlowSettingsService } from '../../services/flow-settings.service';
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

describe('FlowSettingsPanelComponent toggles', () => {
    beforeEach(() => localStorage.clear());

    it.each([
        ['Always show node numbers', 'alwaysShowNodeNumbers'],
        ['Highlight unused nodes', 'highlightUnusedNodes'],
    ] as const)('"%s" flips the %s setting', (label, setting) => {
        TestBed.configureTestingModule({
            providers: [
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: FLOW_EDITOR_PREVIEW, useValue: false },
                { provide: PermissionsService, useValue: { can: () => true } },
            ],
        });
        const fixture = TestBed.createComponent(FlowSettingsPanelComponent);
        fixture.detectChanges();
        const settings = TestBed.inject(FlowSettingsService);
        const row = fixture.debugElement
            .queryAll(By.css('.form-section--toggle'))
            .find((section) => section.nativeElement.textContent.includes(label))!;

        row.nativeElement.querySelector('input[type="checkbox"]').click();
        fixture.detectChanges();
        expect(settings[setting]()).toBe(true);

        row.nativeElement.querySelector('input[type="checkbox"]').click();
        expect(settings[setting]()).toBe(false);
    });
});
