import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { SidebarToggleButtonComponent } from './sidebar-toggle-button.component';

describe('SidebarToggleButtonComponent', () => {
    let fixture: ComponentFixture<SidebarToggleButtonComponent>;

    beforeEach(() => {
        fixture = TestBed.createComponent(SidebarToggleButtonComponent);
        fixture.componentRef.setInput('label', 'Open sidebar');
        fixture.detectChanges();
    });

    function button(): HTMLButtonElement {
        return (fixture.nativeElement as HTMLElement).querySelector('button')!;
    }

    function tooltip(): MatTooltip {
        return fixture.debugElement.query(By.directive(MatTooltip)).injector.get(MatTooltip);
    }

    it('renders a plain button named by its label, with the label as a tooltip on the right', () => {
        expect(button().type).toBe('button');
        expect(button().getAttribute('aria-label')).toBe('Open sidebar');
        expect(tooltip().message).toBe('Open sidebar');
        expect(tooltip().position).toBe('right');
    });

    it('is inactive by default', () => {
        expect(button().classList).not.toContain('active');
    });

    it('marks an open sidebar as active', () => {
        fixture.componentRef.setInput('active', true);
        fixture.detectChanges();

        expect(button().classList).toContain('active');
    });

    it('emits on click', () => {
        const toggled = vi.fn();
        fixture.componentInstance.toggled.subscribe(toggled);

        button().click();

        expect(toggled).toHaveBeenCalledTimes(1);
    });
});
