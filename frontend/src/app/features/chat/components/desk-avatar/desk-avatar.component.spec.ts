import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ChatBindingStatus } from '../../utils/binding-status.util';
import { deskAvatarColor } from '../../utils/desk-avatar.util';
import { DeskAvatarComponent } from './desk-avatar.component';

describe('DeskAvatarComponent', () => {
    let fixture: ComponentFixture<DeskAvatarComponent>;

    function render(inputs: {
        name: string;
        deskId?: string | null;
        icon?: string | null;
        status?: ChatBindingStatus | null;
        count?: number;
        showBadge?: boolean;
    }): HTMLElement {
        fixture = TestBed.createComponent(DeskAvatarComponent);
        Object.entries(inputs).forEach(([key, value]) => fixture.componentRef.setInput(key, value));
        fixture.detectChanges();
        return fixture.nativeElement as HTMLElement;
    }

    const query = (host: HTMLElement, selector: string): HTMLElement | null => host.querySelector(selector);

    it('is one image named in words: desk, status and how many wait for a person', () => {
        const host = render({ name: 'Sales', deskId: 'b-1', status: 'live', count: 2 });
        expect(host.getAttribute('role')).toBe('img');
        expect(host.getAttribute('aria-label')).toBe('Sales desk, Live, 2 waiting for a person');
        // Everything drawn inside is hidden, so nothing is read twice.
        Array.from(host.children).forEach((child) => expect(child.getAttribute('aria-hidden')).toBe('true'));
    });

    it('shows the initials on the fill picked by the desk id', () => {
        const host = render({ name: 'Sales team', deskId: 'b-1' });
        expect(query(host, '.desk-avatar__initials')?.textContent).toBe('ST');
        expect(query(host, '.desk-avatar__picture')?.style.backgroundColor).toBe(deskAvatarColor('b-1'));
        expect(query(host, '.desk-avatar__picture--neutral')).toBeNull();
    });

    it('draws a given icon instead of the initials, on the neutral fill when it is not a desk', () => {
        const host = render({ name: 'All desks', icon: 'messages' });
        expect(query(host, '.desk-avatar__initials')).toBeNull();
        expect(query(host, 'app-svg-icon use')?.getAttribute('href')).toBe('#icon-messages');
        expect(query(host, '.desk-avatar__picture--neutral')).not.toBeNull();
    });

    it('falls back to an icon for a blank name', () => {
        const host = render({ name: '  ', deskId: 'b-1' });
        expect(query(host, '.desk-avatar__initials')).toBeNull();
        expect(query(host, 'app-svg-icon')).not.toBeNull();
    });

    it.each([
        ['live', 'Live'],
        ['paused', 'Paused'],
        ['broken', 'Broken'],
    ] as const)('marks a %s desk with its own shape class and says %s', (status, label) => {
        const host = render({ name: 'Sales', deskId: 'b-1', status });
        const marks = host.querySelectorAll('.desk-avatar__status');
        expect(marks.length).toBe(1);
        expect(marks[0].classList).toContain(`desk-avatar__status--${status}`);
        expect(host.getAttribute('aria-label')).toBe(`Sales desk, ${label}`);
    });

    it('draws no status mark without a status', () => {
        const host = render({ name: 'All desks', count: 1 });
        expect(query(host, '.desk-avatar__status')).toBeNull();
        expect(host.getAttribute('aria-label')).toBe('All desks, 1 waiting for a person');
    });

    it('hides the badge at zero and caps it at 99+, while the name keeps the exact count', () => {
        expect(query(render({ name: 'Sales', deskId: 'b-1', count: 0 }), '.desk-avatar__badge')).toBeNull();
        expect(query(render({ name: 'Sales', deskId: 'b-1', count: 7 }), '.desk-avatar__badge')?.textContent).toBe('7');
        const host = render({ name: 'Sales', deskId: 'b-1', count: 120 });
        expect(query(host, '.desk-avatar__badge')?.textContent).toBe('99+');
        expect(host.getAttribute('aria-label')).toBe('Sales desk, 120 waiting for a person');
    });

    it('leaves the badge to its host when told to, keeping the count in the name', () => {
        const host = render({ name: 'Sales', deskId: 'b-1', count: 3, showBadge: false });
        expect(query(host, '.desk-avatar__badge')).toBeNull();
        expect(host.getAttribute('aria-label')).toBe('Sales desk, 3 waiting for a person');
    });
});
