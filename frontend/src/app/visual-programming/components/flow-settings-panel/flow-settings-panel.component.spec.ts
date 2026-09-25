import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';

import { FlowSettingsPanelComponent, FlowSettingsPanelData } from './flow-settings-panel.component';

function create(data: FlowSettingsPanelData | null): FlowSettingsPanelComponent {
    TestBed.configureTestingModule({
        providers: [
            { provide: DialogRef, useValue: { close: vi.fn() } },
            { provide: DIALOG_DATA, useValue: data },
        ],
    });
    return TestBed.createComponent(FlowSettingsPanelComponent).componentInstance;
}

describe('FlowSettingsPanelComponent', () => {
    it('locks the default timezone in the version preview', () => {
        expect(create({ readOnly: true })['timezoneControl'].disabled).toBe(true);
    });

    it('keeps the default timezone editable in the live editor', () => {
        expect(create(null)['timezoneControl'].enabled).toBe(true);
    });
});
