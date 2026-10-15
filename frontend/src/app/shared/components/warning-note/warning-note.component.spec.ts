import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { WarningNoteComponent } from './warning-note.component';

@Component({
    imports: [WarningNoteComponent],
    template: '<app-warning-note>This trigger is in the recycle bin.</app-warning-note>',
})
class HostComponent {}

describe('WarningNoteComponent', () => {
    it('shows the projected text', () => {
        const fixture = TestBed.createComponent(HostComponent);
        fixture.detectChanges();

        const note = (fixture.nativeElement as HTMLElement).querySelector('app-warning-note');
        expect(note?.textContent?.trim()).toBe('This trigger is in the recycle bin.');
    });
});
