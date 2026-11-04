import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { AvailablePlugin } from '../../models/available-plugin.model';
import { buildAvailablePlugin } from '../../testing/plugin-fixtures';
import { APPS_LIST_SEARCH_THRESHOLD, AppsListComponent, AppsListVariant } from './apps-list.component';

function apps(count: number): AvailablePlugin[] {
    return Array.from({ length: count }, (_, index) =>
        buildAvailablePlugin({ identifier: `app-${index + 1}`, name: `Example app ${index + 1}` })
    );
}

@Component({
    imports: [AppsListComponent],
    template: `<app-apps-list
        [apps]="apps()"
        [variant]="variant()"
        [organizationName]="organizationName()"
        [currentIdentifier]="currentIdentifier()"
        [newIdentifiers]="newIdentifiers()"
        (appChosen)="chosen = chosen + 1"
        ><a
            class="footer-link"
            href="/workspace/plugins"
            >Manage apps</a
        ></app-apps-list
    >`,
})
class HostComponent {
    readonly apps = signal<AvailablePlugin[]>([]);
    readonly variant = signal<AppsListVariant>('popover');
    readonly organizationName = signal<string | null>('Acme');
    readonly currentIdentifier = signal<string | null>(null);
    readonly newIdentifiers = signal<ReadonlySet<string>>(new Set());
    chosen = 0;
}

describe('AppsListComponent', () => {
    let fixture: ComponentFixture<HostComponent>;
    let host: HostComponent;
    let element: HTMLElement;

    beforeEach(() => {
        // jsdom has no ResizeObserver; the organization's overflow tooltip needs one.
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        TestBed.configureTestingModule({ providers: [provideRouter([{ path: '**', children: [] }])] });
        fixture = TestBed.createComponent(HostComponent);
        host = fixture.componentInstance;
        element = fixture.nativeElement as HTMLElement;
    });

    function show(list: AvailablePlugin[]): void {
        host.apps.set(list);
        fixture.detectChanges();
    }

    function searchField(): HTMLInputElement | null {
        return element.querySelector('app-search input');
    }

    function search(text: string): void {
        const field = searchField()!;
        field.value = text;
        field.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    function links(): HTMLAnchorElement[] {
        return Array.from(element.querySelectorAll<HTMLAnchorElement>('a.apps-list__item'));
    }

    function names(): string[] {
        return Array.from(element.querySelectorAll('.apps-list__name-text')).map((name) => name.textContent!.trim());
    }

    function emptyText(): string | null {
        return element.querySelector('.apps-list__empty')?.textContent?.trim() ?? null;
    }

    it('links each app to its page, with its icon, name and description', () => {
        show([buildAvailablePlugin()]);

        const [link] = links();
        expect(link.getAttribute('href')).toBe('/plugins/weather');
        expect(link.querySelector('img')!.getAttribute('src')).toBe('/api/plugin-public/weather/icon/?v=0.1.0');
        expect(names()).toEqual(['Weather']);
        expect(link.querySelector('.apps-list__description')!.textContent!.trim()).toBe(
            'Forecasts for the places your organization cares about.'
        );
    });

    it('heads a popover with its heading and the organization', () => {
        show(apps(2));

        expect(element.querySelector('.apps-list__heading')!.textContent!.trim()).toBe('Apps');
        expect(element.querySelector('.apps-list__organization')!.textContent!.trim()).toBe('Acme');
        expect(element.querySelector('ul')!.getAttribute('aria-label')).toBe('Apps');
    });

    it(`offers a search only above ${APPS_LIST_SEARCH_THRESHOLD} apps`, () => {
        show(apps(APPS_LIST_SEARCH_THRESHOLD));
        expect(searchField()).toBeNull();

        show(apps(APPS_LIST_SEARCH_THRESHOLD + 1));
        expect(searchField()!.getAttribute('aria-label')).toBe('Find an app');
    });

    it('narrows the list by name, whatever the case, and says when nothing matches', () => {
        show([...apps(6), buildAvailablePlugin({ identifier: 'atlas', name: 'Atlas' })]);

        search('  ATL ');
        expect(names()).toEqual(['Atlas']);

        search('zzz');
        expect(names()).toEqual([]);
        expect(emptyText()).toBe('No apps match');
    });

    it('says when the organization has no apps', () => {
        show([]);

        expect(emptyText()).toBe('No apps in this organization');
    });

    it('checks the current app and marks it as the current one', () => {
        host.currentIdentifier.set('app-2');
        show(apps(3));

        const current = links().filter((link) => link.getAttribute('aria-current') === 'true');
        expect(current.map((link) => link.getAttribute('href'))).toEqual(['/plugins/app-2']);
        expect(current[0].querySelector('.apps-list__check')).not.toBeNull();
        expect(element.querySelectorAll('.apps-list__check').length).toBe(1);
    });

    it('tags the new apps', () => {
        host.newIdentifiers.set(new Set(['app-3']));
        show(apps(3));

        const tagged = links().filter((link) => link.querySelector('.apps-list__new'));
        expect(tagged.map((link) => link.getAttribute('href'))).toEqual(['/plugins/app-3']);
        expect(tagged[0].querySelector('.apps-list__new')!.textContent!.trim()).toBe('New');
    });

    it('shows what its owner puts under the list', () => {
        show(apps(1));

        expect(element.querySelector('.apps-list__footer .footer-link')!.textContent!.trim()).toBe('Manage apps');
    });

    it('drops the heading and the search inline, however many apps there are', () => {
        host.variant.set('inline');
        show(apps(APPS_LIST_SEARCH_THRESHOLD + 3));

        expect(element.querySelector('.apps-list__head')).toBeNull();
        expect(searchField()).toBeNull();
        expect(names().length).toBe(APPS_LIST_SEARCH_THRESHOLD + 3);
    });

    it('tells its owner when an app is followed here, not when it opens elsewhere', () => {
        show(apps(1));
        // The browser would open the link in a new tab: jsdom must not try to navigate.
        const keepPage = (event: Event): void => event.preventDefault();
        document.addEventListener('click', keepPage);
        try {
            for (const init of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { button: 1 }]) {
                links()[0].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, ...init }));
            }
            expect(host.chosen).toBe(0);

            links()[0].dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            expect(host.chosen).toBe(1);
        } finally {
            document.removeEventListener('click', keepPage);
        }
    });
});
