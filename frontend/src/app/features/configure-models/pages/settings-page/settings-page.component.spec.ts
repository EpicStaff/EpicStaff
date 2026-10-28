import { provideHttpClient } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { ActionCode, ActivePermissions, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ConfigService } from '../../../../services/config';
import { SettingsPageComponent } from './settings-page.component';

type Grants = Partial<Record<ResourceCode, ActionCode[]>>;

describe('SettingsPageComponent tabs', () => {
    let fixture: ComponentFixture<SettingsPageComponent>;

    function render(grants: Grants, isPluginsEnabled: boolean): void {
        TestBed.configureTestingModule({
            imports: [SettingsPageComponent],
            providers: [
                provideRouter([]),
                provideHttpClient(),
                { provide: ConfigService, useValue: { isPluginsEnabled } },
            ],
        });
        TestBed.inject(PermissionsService).setActivePermissions({
            org_id: 1,
            is_superadmin: false,
            role: { id: 1, name: 'Custom' },
            permissions: grants as ActivePermissions['permissions'],
        });
        fixture = TestBed.createComponent(SettingsPageComponent);
        fixture.detectChanges();
    }

    function tabLabels(): string[] {
        return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('.route-tab')).map(
            (tab) => tab.textContent?.trim() ?? ''
        );
    }

    it('shows Plugin activity, last, to a role with Read on Audit while plugins are on', () => {
        render({ [ResourceCode.Secrets]: [ActionCode.Read], [ResourceCode.Audit]: [ActionCode.Read] }, true);

        expect(tabLabels()).toEqual(['Secrets', 'Plugin activity']);
    });

    it('hides it while plugins are off', () => {
        render({ [ResourceCode.Audit]: [ActionCode.Read] }, false);

        expect(tabLabels()).toEqual([]);
    });

    it('hides it from a role without Read on Audit', () => {
        render({ [ResourceCode.LlmConfigs]: [ActionCode.Read] }, true);

        expect(tabLabels()).toEqual(['Default LLMs', 'LLM Library']);
    });

    it('describes the page without naming what the role may not see', () => {
        render({ [ResourceCode.Audit]: [ActionCode.Read] }, true);

        expect(
            (fixture.nativeElement as HTMLElement).querySelector('.settings-page__subtitle')?.textContent?.trim()
        ).toBe('For your current organization.');
    });
});
