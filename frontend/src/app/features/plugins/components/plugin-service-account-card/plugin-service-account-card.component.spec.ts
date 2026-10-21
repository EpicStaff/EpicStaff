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
});
