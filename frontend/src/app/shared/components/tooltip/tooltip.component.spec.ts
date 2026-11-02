import { TestBed } from '@angular/core/testing';

import { TooltipComponent } from './tooltip.component';

describe('TooltipComponent', () => {
    it.each<[description: string, label: string, expected: string]>([
        ['after its field label', 'Email', 'Email help'],
        ['plainly without a label', '', 'Help'],
    ])('names the help button %s', (_description, label, expected) => {
        const fixture = TestBed.createComponent(TooltipComponent);
        fixture.componentRef.setInput('label', label);
        fixture.componentRef.setInput('tooltipText', 'The login address');
        fixture.detectChanges();

        const button = (fixture.nativeElement as HTMLElement).querySelector('app-help-tooltip button');

        expect(button?.getAttribute('aria-label')).toBe(expected);
    });
});
