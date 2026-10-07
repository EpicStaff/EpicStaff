import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { RUN_TEST_PAYLOAD_LABEL, RunTestPayloadButtonComponent } from './run-test-payload-button.component';

describe('RunTestPayloadButtonComponent', () => {
    let fixture: ComponentFixture<RunTestPayloadButtonComponent>;
    let run: ReturnType<typeof vi.fn<() => void>>;

    beforeEach(() => {
        fixture = TestBed.createComponent(RunTestPayloadButtonComponent);
        run = vi.fn<() => void>();
        fixture.componentInstance.run.subscribe(run);
    });

    function button(): HTMLButtonElement {
        return fixture.nativeElement.querySelector('button');
    }

    function tooltipMessage(): string {
        return fixture.debugElement.query(By.directive(MatTooltip)).injector.get(MatTooltip).message;
    }

    it('runs on click while enabled, with the label as its name and icon-only tooltip', () => {
        fixture.detectChanges();

        button().click();

        expect(run).toHaveBeenCalledTimes(1);
        expect(button().getAttribute('aria-disabled')).toBe('false');
        expect(button().getAttribute('aria-label')).toBe(RUN_TEST_PAYLOAD_LABEL);
        expect(tooltipMessage()).toBe(RUN_TEST_PAYLOAD_LABEL);
    });

    it('drops the tooltip when the label is shown', () => {
        fixture.componentRef.setInput('labelled', true);
        fixture.detectChanges();

        expect(button().textContent).toContain(RUN_TEST_PAYLOAD_LABEL);
        expect(tooltipMessage()).toBe('');
    });

    it('stays focusable when disabled, ignores clicks and explains why on the button itself', () => {
        fixture.componentRef.setInput('disabledReason', 'Fix the test payload JSON to run');
        fixture.detectChanges();

        button().click();

        expect(run).not.toHaveBeenCalled();
        expect(button().disabled).toBe(false);
        expect(button().getAttribute('aria-disabled')).toBe('true');
        expect(tooltipMessage()).toBe('Fix the test payload JSON to run');
    });

    it('describes the disabled reason to assistive technology', async () => {
        fixture.componentRef.setInput('disabledReason', 'A run is starting...');
        fixture.detectChanges();
        await fixture.whenStable();

        const describedBy = button().getAttribute('aria-describedby');
        expect(describedBy).toBeTruthy();
        expect(document.getElementById(describedBy!)?.textContent).toBe('A run is starting...');
    });

    it('marks itself busy and shows a spinner while its run starts', () => {
        fixture.componentRef.setInput('isStarting', true);
        fixture.detectChanges();

        expect(button().getAttribute('aria-busy')).toBe('true');
        expect(fixture.nativeElement.querySelector('app-spinner2')).not.toBeNull();
    });
});
