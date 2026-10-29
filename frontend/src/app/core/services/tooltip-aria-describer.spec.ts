import { AriaDescriber } from '@angular/cdk/a11y';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';

import { TooltipAriaDescriber } from './tooltip-aria-describer';

@Component({
    imports: [MatTooltip],
    template: `
        <button
            id="text-button"
            type="button"
            [matTooltip]="textButtonTooltip()"
        >
            Save
        </button>
        <button
            id="icon-button"
            type="button"
            aria-label="Delete"
            [matTooltip]="iconButtonTooltip()"
        ></button>
        <label for="name-input">Flow name</label>
        <input
            id="name-input"
            type="text"
            [matTooltip]="inputTooltip()"
        />
    `,
})
class HostComponent {
    readonly textButtonTooltip = signal('Save');
    readonly iconButtonTooltip = signal('Delete');
    readonly inputTooltip = signal('Flow name');
}

describe('TooltipAriaDescriber', () => {
    let fixture: ComponentFixture<HostComponent>;

    const element = (id: string): HTMLElement => fixture.nativeElement.querySelector(`#${id}`);

    /** What a screen reader reads after the element's name: the text of the elements its aria-describedby points at. */
    function descriptionOf(id: string): string[] {
        return (element(id).getAttribute('aria-describedby') ?? '')
            .split(/\s+/)
            .filter(Boolean)
            .map((descriptionId) => document.getElementById(descriptionId)?.textContent ?? '');
    }

    async function render(): Promise<void> {
        fixture.detectChanges();
        await fixture.whenStable();
    }

    beforeEach(async () => {
        TestBed.configureTestingModule({ providers: [{ provide: AriaDescriber, useClass: TooltipAriaDescriber }] });
        fixture = TestBed.createComponent(HostComponent);
        await render();
    });

    it.each([
        ['a text button whose tooltip repeats its text', 'text-button'],
        ['a button whose tooltip repeats its aria-label', 'icon-button'],
        ['a field whose tooltip repeats its label', 'name-input'],
    ])('leaves the tooltip out of the description of %s', (_case, id) => {
        expect(descriptionOf(id)).toEqual([]);
    });

    it('describes a button with a tooltip that says more than its name', async () => {
        fixture.componentInstance.textButtonTooltip.set('Save the flow');
        fixture.componentInstance.iconButtonTooltip.set('Delete the flow');
        await render();

        expect(descriptionOf('text-button')).toEqual(['Save the flow']);
        expect(descriptionOf('icon-button')).toEqual(['Delete the flow']);
    });

    it('drops the description again once the tooltip changes back to the name', async () => {
        fixture.componentInstance.inputTooltip.set('The name the flow list shows');
        await render();
        expect(descriptionOf('name-input')).toEqual(['The name the flow list shows']);

        fixture.componentInstance.inputTooltip.set('Flow name');
        await render();

        expect(descriptionOf('name-input')).toEqual([]);
    });
});
