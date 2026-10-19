import { ComponentFixture, TestBed } from '@angular/core/testing';

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
