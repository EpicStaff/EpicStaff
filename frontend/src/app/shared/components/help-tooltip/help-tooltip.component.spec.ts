import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { HelpTooltipComponent } from './help-tooltip.component';

function render(inputs: Record<string, string> = {}): ComponentFixture<HelpTooltipComponent> {
    const fixture = TestBed.createComponent(HelpTooltipComponent);
    for (const [name, value] of Object.entries(inputs)) {
        fixture.componentRef.setInput(name, value);
    }
    fixture.detectChanges();
    return fixture;
}

function svg(fixture: ComponentFixture<HelpTooltipComponent>): SVGElement {
    const element = (fixture.nativeElement as HTMLElement).querySelector('app-svg-icon svg');
    if (!element) throw new Error('no svg rendered');
    return element as SVGElement;
}

describe('HelpTooltipComponent icon size', () => {
    it('renders a square icon of `size` by default', () => {
        const icon = svg(render());

        expect(icon.style.width).toBe('16px');
        expect(icon.style.height).toBe('16px');
    });

    it('passes width and height through to the icon', () => {
        const icon = svg(render({ size: '16px', width: '18px', height: '12px' }));

        expect(icon.style.width).toBe('18px');
        expect(icon.style.height).toBe('12px');
    });

    it('overrides one axis and leaves the other at `size`', () => {
        const icon = svg(render({ size: '20px', width: '24px' }));

        expect(icon.style.width).toBe('24px');
        expect(icon.style.height).toBe('20px');
    });

    it('renders the icon named by `icon`', () => {
        const use = svg(render({ icon: 'info-circle' })).querySelector('use');

        expect(use?.getAttribute('href')).toBe('#icon-info-circle');
    });
});

describe('HelpTooltipComponent trigger', () => {
    function trigger(fixture: ComponentFixture<HelpTooltipComponent>): HTMLButtonElement {
        const button = (fixture.nativeElement as HTMLElement).querySelector('button');
        if (!button) throw new Error('no trigger button rendered');
        return button;
    }

    it.each<[branch: string, inputs: Record<string, string>]>([
        ['svg icon', {}],
        ['icon class', { iconClass: 'ti ti-help' }],
    ])('puts the tooltip with the `text` on a focusable, non-submitting button (%s)', (_branch, inputs) => {
        const fixture = render({ ...inputs, text: 'What this field does' });
        const button = trigger(fixture);
        const tooltip = fixture.debugElement.query(By.directive(MatTooltip));

        button.focus();

        expect(document.activeElement).toBe(button);
        expect(button.type).toBe('button');
        expect(tooltip.nativeElement).toBe(button);
        expect(tooltip.injector.get(MatTooltip).message).toBe('What this field does');
    });

    it.each<[description: string, inputs: Record<string, string>, expected: string]>([
        ['defaults to Help', {}, 'Help'],
        ['uses the given name', { ariaLabel: 'Email help' }, 'Email help'],
    ])('names the button: %s', (_description, inputs, expected) => {
        expect(trigger(render(inputs)).getAttribute('aria-label')).toBe(expected);
    });
});
