import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ORG_SWITCH_URL_RULES, OrgSwitchUrlRule } from '@shared/services';
import { EMPTY, of } from 'rxjs';
import type { Mock } from 'vitest';

import { UnsavedChangesRegistry } from '../../../../core/services/unsaved-changes-registry.service';
import { ActiveOrgService } from '../../../../services/auth/active-org.service';
import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../services/auth/profile.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsMenuComponent } from './organizations-menu.component';

/** A feature's rule, as features register them: `/reports/<id>/…` keeps only the report. */
const keepReport: OrgSwitchUrlRule = (url) => /^\/reports\/[^/?]+/.exec(url)?.[0] ?? null;

describe('OrganizationsMenuComponent organization switch', () => {
    let navigateByUrl: Mock<(url: string) => Promise<boolean>>;

    async function switchFrom(url: string, rules: OrgSwitchUrlRule[] = [keepReport]): Promise<string> {
        navigateByUrl = vi.fn(() => Promise.resolve(true));
        TestBed.resetTestingModule();
        TestBed.configureTestingModule({
            providers: [
                { provide: Router, useValue: { url, events: EMPTY, navigateByUrl } },
                { provide: ToastService, useValue: { error: vi.fn() } },
                { provide: UnsavedChangesRegistry, useValue: { canLeave: () => of(true) } },
                { provide: ProfileService, useValue: { switchOrg: () => of(undefined) } },
                { provide: PermissionsService, useValue: { canAccessWorkspace: () => false } },
                ...rules.map((rule) => ({ provide: ORG_SWITCH_URL_RULES, useValue: rule, multi: true })),
            ],
        });
        TestBed.inject(ActiveOrgService).set(1);
        const menu = TestBed.createComponent(OrganizationsMenuComponent).componentInstance;

        menu.onOrgClick(2);
        await Promise.resolve();

        // The first navigation remounts the page through /profile; the second is the target.
        return navigateByUrl.mock.calls[1][0];
    }

    afterEach(() => localStorage.clear());

    it("opens what a feature's rule maps its address to", async () => {
        expect(await switchFrom('/reports/12/pages/3?zoom=2')).toBe('/reports/12');
    });

    it('keeps an address no rule answers for', async () => {
        expect(await switchFrom('/knowledge-sources')).toBe('/knowledge-sources');
        expect(await switchFrom('/reports/12', [])).toBe('/reports/12');
    });

    it('still maps a flow or a session to its list first', async () => {
        expect(await switchFrom('/flows/42')).toBe('/flows/my');
        expect(await switchFrom('/graph/7')).toBe('/sessions');
    });
});
