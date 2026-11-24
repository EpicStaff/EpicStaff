import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';

import { ConversationListSection } from '../../utils/conversation-list-tab.util';
import { ConversationSectionBadgeComponent } from './conversation-section-badge.component';

describe('ConversationSectionBadgeComponent', () => {
    let fixture: ComponentFixture<ConversationSectionBadgeComponent>;

    function render(section: ConversationListSection, holder: string | null = null, isAnnounced = false): void {
        fixture = TestBed.createComponent(ConversationSectionBadgeComponent);
        fixture.componentRef.setInput('section', section);
        fixture.componentRef.setInput('holder', holder);
        fixture.componentRef.setInput('isAnnounced', isAnnounced);
        fixture.detectChanges();
    }

    const badge = (): HTMLElement => fixture.nativeElement.querySelector('.conversation-section-badge');
    const tooltip = (): string =>
        fixture.debugElement.query(By.css('.conversation-section-badge')).injector.get(MatTooltip).message;

    it.each([
        { section: 'waiting' as const, icon: '#icon-waiting', color: 'var(--color-status-waiting)' },
        { section: 'in_progress' as const, icon: '#icon-headset-outline', color: 'var(--color-status-in-progress)' },
        { section: 'bot' as const, icon: '#icon-bot', color: 'var(--accent-color)' },
        { section: 'closed' as const, icon: '#icon-closed', color: 'var(--color-text-secondary)' },
        { section: 'test_open' as const, icon: '#icon-flask', color: 'var(--color-status-info)' },
        { section: 'test_closed' as const, icon: '#icon-closed', color: 'var(--color-text-secondary)' },
    ])("shows the $section header's icon, in its colour, 8px whatever its header size", ({ section, icon, color }) => {
        render(section);
        expect(badge().querySelector('use')?.getAttribute('href')).toBe(icon);
        expect(badge().style.getPropertyValue('--section-badge-color')).toBe(color);
        expect(badge().querySelector('svg')?.style.width).toBe('8px');
    });

    it('says who took the conversation in its tooltip', () => {
        render('in_progress', 'Grace Hopper');
        expect(tooltip()).toBe('Taken by Grace Hopper');
    });

    it('has no tooltip while nobody holds the conversation', () => {
        render('bot');
        expect(tooltip()).toBe('');
    });

    describe('for assistive technology', () => {
        // The tooltip's text, as Material links it to the badge for a screen reader.
        const description = (): string =>
            (badge().getAttribute('aria-describedby') ?? '')
                .split(' ')
                .map((id) => document.getElementById(id)?.textContent ?? '')
                .join(' ')
                .trim();

        it.each([
            { section: 'waiting' as const, label: 'Waiting for a person' },
            { section: 'in_progress' as const, label: 'In progress' },
            { section: 'test_open' as const, label: 'Tests' },
        ])('announced, is an image named by its section: $label', ({ section, label }) => {
            render(section, null, true);
            expect(badge().getAttribute('role')).toBe('img');
            expect(badge().getAttribute('aria-label')).toBe(label);
            expect(badge().getAttribute('aria-hidden')).toBeNull();
        });

        it('announced, describes who took the conversation and can be focused for it', async () => {
            render('in_progress', 'Grace Hopper', true);
            // Material links the tooltip's text after the render.
            await fixture.whenStable();
            expect(badge().getAttribute('aria-label')).toBe('In progress');
            expect(description()).toBe('Taken by Grace Hopper');
            expect(badge().tabIndex).toBe(0);
        });

        it('announced, while nobody holds the conversation: no description, and not a Tab stop', async () => {
            render('bot', null, true);
            await fixture.whenStable();
            expect(badge().getAttribute('aria-label')).toBe('Bot');
            expect(description()).toBe('');
            expect(badge().hasAttribute('tabindex')).toBe(false);
        });

        it('not announced, is hidden from it and never focusable, even with a holder', () => {
            render('in_progress', 'Grace Hopper');
            expect(badge().getAttribute('aria-hidden')).toBe('true');
            expect(badge().hasAttribute('role')).toBe(false);
            expect(badge().hasAttribute('aria-label')).toBe(false);
            expect(badge().hasAttribute('tabindex')).toBe(false);
        });
    });
});
