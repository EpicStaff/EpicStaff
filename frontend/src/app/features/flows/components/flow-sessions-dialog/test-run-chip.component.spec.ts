import { TestBed } from '@angular/core/testing';

import { TestRunChipComponent } from './test-run-chip.component';
import { isTestRunTrigger } from './trigger-display.constants';

function render(): HTMLElement {
    const fixture = TestBed.createComponent(TestRunChipComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
}

describe('isTestRunTrigger', () => {
    it('is true only when the trigger is flagged as a test run', () => {
        expect(isTestRunTrigger({ trigger_type: 'webhook', trigger_id: 1, is_test_run: true })).toBe(true);
        expect(isTestRunTrigger({ trigger_type: 'webhook', trigger_id: 1, is_test_run: false })).toBe(false);
        expect(isTestRunTrigger({ trigger_type: 'webhook', trigger_id: 1 })).toBe(false);
        expect(isTestRunTrigger(null)).toBe(false);
        expect(isTestRunTrigger(undefined)).toBe(false);
    });
});

describe('TestRunChipComponent', () => {
    it('renders only the flask icon, named "Test run" for assistive technology', () => {
        const chip = render().querySelector('.test-run-chip');

        expect(chip?.querySelector('i')?.className).toBe('ti ti-flask');
        expect(chip?.querySelector('i')?.getAttribute('aria-hidden')).toBe('true');
        expect(chip?.textContent?.trim()).toBe('');
        expect(chip?.getAttribute('role')).toBe('img');
        expect(chip?.getAttribute('aria-label')).toBe('Test run');
    });
});
