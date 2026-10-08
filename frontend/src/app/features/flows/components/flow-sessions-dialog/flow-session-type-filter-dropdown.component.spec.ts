import { CUSTOM_ELEMENTS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ClickOutsideDirective } from '@shared/directives';

import { SessionRunType } from '../../services/flows-sessions.service';
import { FlowSessionTypeFilterDropdownComponent } from './flow-session-type-filter-dropdown.component';

function render(value: SessionRunType[] = []): ComponentFixture<FlowSessionTypeFilterDropdownComponent> {
    const fixture = TestBed.createComponent(FlowSessionTypeFilterDropdownComponent);
    fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    return fixture;
}

function host(fixture: ComponentFixture<FlowSessionTypeFilterDropdownComponent>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
}

function open(fixture: ComponentFixture<FlowSessionTypeFilterDropdownComponent>): void {
    host(fixture).querySelector<HTMLButtonElement>('.dropdown-toggle')?.click();
    fixture.detectChanges();
}

function clickOption(fixture: ComponentFixture<FlowSessionTypeFilterDropdownComponent>, label: string): void {
    const options = Array.from(host(fixture).querySelectorAll<HTMLElement>('li.group-item'));
    options.find((option) => option.textContent?.trim() === label)?.click();
    fixture.detectChanges();
}

function clickButton(fixture: ComponentFixture<FlowSessionTypeFilterDropdownComponent>, selector: string): void {
    host(fixture).querySelector<HTMLButtonElement>(selector)?.click();
    fixture.detectChanges();
}

function collectEmissions(fixture: ComponentFixture<FlowSessionTypeFilterDropdownComponent>): SessionRunType[][] {
    const emitted: SessionRunType[][] = [];
    fixture.componentInstance.valueChange.subscribe((value) => emitted.push(value));
    return emitted;
}

describe('FlowSessionTypeFilterDropdownComponent', () => {
    beforeEach(() => {
        // The checkbox and icon are presentational; the option list and footer are under test.
        TestBed.overrideComponent(FlowSessionTypeFilterDropdownComponent, {
            set: { imports: [ClickOutsideDirective], schemas: [CUSTOM_ELEMENTS_SCHEMA] },
        });
    });

    it('offers Test and Live', () => {
        const fixture = render();
        open(fixture);

        const labels = Array.from(host(fixture).querySelectorAll('li.group-item')).map((option) =>
            option.textContent?.trim()
        );
        expect(labels).toEqual(['Test', 'Live']);
    });

    it('emits the selected run types on Save', () => {
        const fixture = render();
        const emitted = collectEmissions(fixture);
        open(fixture);
        clickOption(fixture, 'Live');
        clickButton(fixture, '.save-btn');

        expect(emitted).toEqual([['live']]);
        expect(host(fixture).querySelector('.dropdown-panel')).toBeNull();
    });

    it('starts from the current value and can deselect it', () => {
        const fixture = render(['test', 'live']);
        const emitted = collectEmissions(fixture);
        open(fixture);
        clickOption(fixture, 'Test');
        clickButton(fixture, '.save-btn');

        expect(emitted).toEqual([['live']]);
    });

    it('emits an empty selection on Clear Filter', () => {
        const fixture = render(['test']);
        const emitted = collectEmissions(fixture);
        open(fixture);
        clickButton(fixture, '.clear-filter-btn');

        expect(emitted).toEqual([[]]);
    });

    it('discards the draft on Cancel', () => {
        const fixture = render(['test']);
        const emitted = collectEmissions(fixture);
        open(fixture);
        clickOption(fixture, 'Live');
        clickButton(fixture, '.cancel-btn');
        open(fixture);
        clickButton(fixture, '.save-btn');

        expect(emitted).toEqual([['test']]);
    });

    it('marks the toggle as active only while a filter is applied', () => {
        expect(host(render()).querySelector('.node-filter-dropdown')?.classList.contains('has-value')).toBe(false);
        expect(
            host(render(['live']))
                .querySelector('.node-filter-dropdown')
                ?.classList.contains('has-value')
        ).toBe(true);
    });
});
