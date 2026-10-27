import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { Component, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { GetMeResponse } from '@shared/models';

import type { TourDefinition } from '../../../../core/guided-tour';
import { GuidedTourTestbed, setUpGuidedTourTestbed } from '../../../../core/guided-tour/testing/guided-tour-testing';
import { UserMenuComponent } from './user-menu.component';

const USER: GetMeResponse = {
    id: 7,
    email: 'jane@example.com',
    display_name: 'Jane Doe',
    is_superadmin: false,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    memberships: [],
    active_organization_id: 3,
    active_permissions: null,
    avatar_url: null,
    completed_tours: [],
    custom_shortcuts: { custom: [], overrides: {} },
};

const TOUR_LABELS = ['Intro', 'Guide', 'Tips'];

/** Opens the menu the way the sidenav does: shown while open, and closing it removes it. */
@Component({
    imports: [UserMenuComponent],
    template: `
        @if (isMenuOpen()) {
            <app-user-menu
                [user]="user"
                [(isUserMenuOpen)]="isMenuOpen"
            />
        }
    `,
})
class MenuHostComponent {
    readonly isMenuOpen = signal(true);
    readonly user = USER;
}

describe('UserMenuComponent tours', () => {
    let testbed: GuidedTourTestbed;
    let fixture: ComponentFixture<MenuHostComponent>;
    let isGuideAvailable: WritableSignal<boolean>;

    function tour(key: string, label: string, icon: string, isAvailable: () => boolean): () => TourDefinition {
        return () => ({
            key,
            label,
            icon,
            autoStart: 'manual',
            isAvailable,
            steps: [{ id: 'welcome', content: { title: `${label} welcome`, body: [] } }],
        });
    }

    function menu(): HTMLElement | null {
        return (fixture.nativeElement as HTMLElement).querySelector('app-user-menu');
    }

    function entries(): HTMLButtonElement[] {
        return Array.from(menu()?.querySelectorAll<HTMLButtonElement>('button.nav-item') ?? []);
    }

    function labelOf(button: HTMLButtonElement): string | undefined {
        return button.querySelector('.nav-label')?.textContent?.trim();
    }

    /** The tours listed, in menu order; the menu's other entries left out. */
    function listedTours(): string[] {
        return entries()
            .map(labelOf)
            .filter((label): label is string => label !== undefined && TOUR_LABELS.includes(label));
    }

    /** The menu entry labelled `label`. Throws when it is not listed. */
    function entry(label: string): HTMLButtonElement {
        const found = entries().find((button) => labelOf(button) === label);
        if (!found) {
            throw new Error(`The menu lists no "${label}".`);
        }
        return found;
    }

    function iconOf(button: HTMLButtonElement): string | null | undefined {
        return button.querySelector('.nav-icon use')?.getAttribute('href');
    }

    beforeEach(() => {
        isGuideAvailable = signal(false);
        testbed = setUpGuidedTourTestbed({
            tours: [
                tour('intro', 'Intro', 'help', () => true),
                tour('guide', 'Guide', 'book', () => isGuideAvailable()),
                tour('tips', 'Tips', 'lightbulb', () => true),
            ],
            providers: [provideHttpClient(), provideHttpClientTesting()],
        });
        fixture = TestBed.createComponent(MenuHostComponent);
        fixture.detectChanges();
    });

    afterEach(() => testbed.cleanUp());

    it('lists the tours the user can take now, in registration order, each with its label and icon', () => {
        expect(listedTours()).toEqual(['Intro', 'Tips']);
        expect(iconOf(entry('Intro'))).toBe('#icon-help');
        expect(iconOf(entry('Tips'))).toBe('#icon-lightbulb');

        // E.g. an org switch grants what the tour needs.
        isGuideAvailable.set(true);
        fixture.detectChanges();

        expect(listedTours()).toEqual(['Intro', 'Guide', 'Tips']);
    });

    it('closes the menu and starts the tour picked', async () => {
        entry('Tips').click();
        fixture.detectChanges();
        await testbed.settle();

        expect(menu()).toBeNull();
        expect(testbed.service.activeTour()?.key).toBe('tips');
        expect(testbed.renderer().view?.content.title).toBe('Tips welcome');
    });
});
