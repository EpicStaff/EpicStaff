import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../services/auth/permissions.service';
import { SectionHeaderComponent } from './section-header.component';

function render(expanded: boolean, showAdd = true): ComponentFixture<SectionHeaderComponent> {
    TestBed.configureTestingModule({
        providers: [{ provide: PermissionsService, useValue: { can: () => true, canAny: () => true } }],
    });
    const fixture = TestBed.createComponent(SectionHeaderComponent);
    fixture.componentRef.setInput('label', 'Bot');
    fixture.componentRef.setInput('expanded', expanded);
    fixture.componentRef.setInput('resource', ResourceCode.Chats);
    fixture.componentRef.setInput('showAdd', showAdd);
    fixture.detectChanges();
    return fixture;
}

const toggleButton = (fixture: ComponentFixture<SectionHeaderComponent>): HTMLButtonElement =>
    (fixture.nativeElement as HTMLElement).querySelector('.header__toggle') as HTMLButtonElement;

describe('SectionHeaderComponent', () => {
    it('renders the toggle as a native button so Enter and Space activate it', () => {
        const button = toggleButton(render(true));

        expect(button.tagName).toBe('BUTTON');
        expect(button.type).toBe('button');
        expect(button.textContent).toContain('Bot');
    });

    it('emits toggleSection when the toggle is clicked', () => {
        const fixture = render(true);
        const emitted = vi.fn();
        fixture.componentInstance.toggleSection.subscribe(emitted);

        toggleButton(fixture).click();

        expect(emitted).toHaveBeenCalledTimes(1);
    });

    it('reflects expanded in aria-expanded', () => {
        const fixture = render(false);
        expect(toggleButton(fixture).getAttribute('aria-expanded')).toBe('false');

        fixture.componentRef.setInput('expanded', true);
        fixture.detectChanges();

        expect(toggleButton(fixture).getAttribute('aria-expanded')).toBe('true');
    });

    it('hides the Add button when showAdd is false', () => {
        const query = (fixture: ComponentFixture<SectionHeaderComponent>) =>
            (fixture.nativeElement as HTMLElement).querySelector('[aria-label="Add"]');

        expect(query(render(true, true))).not.toBeNull();
        TestBed.resetTestingModule();
        expect(query(render(true, false))).toBeNull();
    });

    it('does not toggle when Add is clicked', () => {
        const fixture = render(true);
        const toggled = vi.fn();
        const added = vi.fn();
        fixture.componentInstance.toggleSection.subscribe(toggled);
        fixture.componentInstance.add.subscribe(added);

        ((fixture.nativeElement as HTMLElement).querySelector('[aria-label="Add"]') as HTMLButtonElement).click();

        expect(added).toHaveBeenCalledTimes(1);
        expect(toggled).not.toHaveBeenCalled();
    });
});
