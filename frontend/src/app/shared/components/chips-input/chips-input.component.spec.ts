import { TestBed } from '@angular/core/testing';

import { ChipsInputComponent } from './chips-input.component';

describe('ChipsInputComponent read-only empty text', () => {
    function emptyText(readOnlyEmptyText?: string): string {
        const fixture = TestBed.createComponent(ChipsInputComponent);
        fixture.componentRef.setInput('readOnly', true);
        if (readOnlyEmptyText !== undefined) fixture.componentRef.setInput('readOnlyEmptyText', readOnlyEmptyText);
        fixture.detectChanges();
        return fixture.nativeElement.querySelector('.chips-empty').textContent.trim();
    }

    it('says "No libraries" unless the caller gives other text', () => {
        expect(emptyText()).toBe('No libraries');
        expect(emptyText('No levels')).toBe('No levels');
    });
});
