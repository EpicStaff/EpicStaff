import { ComponentFixture, TestBed } from '@angular/core/testing';

import { OrganizationServiceAccount } from '../../models/plugin-activity.model';
import { buildOrganizationServiceAccount } from '../../testing/plugin-fixtures';
import { PluginServiceAccountCardComponent } from './plugin-service-account-card.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('PluginServiceAccountCardComponent', () => {
    let fixture: ComponentFixture<PluginServiceAccountCardComponent>;
    let element: HTMLElement;

    function render(account: OrganizationServiceAccount): void {
        fixture = TestBed.createComponent(PluginServiceAccountCardComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.componentRef.setInput('account', account);
        fixture.detectChanges();
    }

    function badge(): string {
        return element.querySelector('app-plugin-badge')?.textContent?.trim() ?? '';
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        TestBed.configureTestingModule({ imports: [PluginServiceAccountCardComponent] });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('says the plugin is suspended in the organization', () => {
        render(buildOrganizationServiceAccount({ grant_state: 'suspended' }));

        expect(badge()).toBe('Suspended');
    });

    it('says the plugin is active, with its name and when its key was last used', () => {
        render(buildOrganizationServiceAccount());

        expect(badge()).toBe('Active');
        expect(element.querySelector('.account__name')?.textContent?.trim()).toBe('Weather');
        expect(element.querySelector('.account__facts')?.textContent).toContain('Never');
    });

    it('lists the hosts its backend may reach, with their reasons', () => {
        render(
            buildOrganizationServiceAccount({
                outbound_hosts: [
                    {
                        host: 'geocoding-api.open-meteo.com',
                        reason: 'Looks up places by name when someone adds a saved place.',
                    },
                ],
            })
        );

        const hosts = Array.from(element.querySelectorAll('.account__hosts li')).map((item) =>
            item.textContent?.replace(/\s+/g, ' ').trim()
        );
        expect(hosts).toEqual([
            'geocoding-api.open-meteo.com — Looks up places by name when someone adds a saved place.',
        ]);
        expect(element.textContent).toContain('Outbound hosts');
    });

    it('says when its backend cannot reach the internet', () => {
        render(buildOrganizationServiceAccount());

        expect(element.querySelector('.account__hosts')).toBeNull();
        expect(element.textContent).toContain('None. Its backend cannot reach the internet.');
    });

    it('says it keeps its data in its own database only when it has one', () => {
        render(buildOrganizationServiceAccount());
        expect(element.textContent).not.toContain('Keeps its data in its own database');

        render(buildOrganizationServiceAccount({ has_database: true }));
        expect(element.querySelector('.account__database')?.textContent?.trim()).toBe(
            'Keeps its data in its own database.'
        );
    });
});
