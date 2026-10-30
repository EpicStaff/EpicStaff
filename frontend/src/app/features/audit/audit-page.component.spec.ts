import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';

import { PermissionsService } from '../../services/auth/permissions.service';
import { ConfigService } from '../../services/config';
import { AUDIT_ROUTES } from './audit.routes';

@Component({ template: 'sessions-page' })
class SessionsStubComponent {}

@Component({ template: 'actions-page' })
class ActionsStubComponent {}

async function openAudit(isSessionAuditEnabled: boolean, isUserAuditEnabled: boolean): Promise<RouterTestingHarness> {
    const [pageRoute] = AUDIT_ROUTES;
    const [indexRoute, sessionsRoute, actionsRoute] = pageRoute.children!;
    TestBed.configureTestingModule({
        providers: [
            provideRouter([
                {
                    path: 'audit',
                    loadComponent: pageRoute.loadComponent,
                    children: [
                        indexRoute,
                        { ...sessionsRoute, loadComponent: () => SessionsStubComponent },
                        { ...actionsRoute, loadComponent: () => ActionsStubComponent },
                    ],
                },
                { path: 'agents', children: [] },
            ]),
            { provide: ConfigService, useValue: { isSessionAuditEnabled, isUserAuditEnabled } },
            {
                provide: PermissionsService,
                useValue: { can: () => true, resolveDefaultRoute: () => '/agents' },
            },
        ],
    });
    const harness = await RouterTestingHarness.create();
    await harness.navigateByUrl('/audit');
    return harness;
}

function tabLabels(root: HTMLElement): string[] {
    return Array.from(root.querySelectorAll('.route-tab')).map((tab) => tab.textContent!.trim());
}

describe('audit page', () => {
    it('shows sessions without tabs when user audit is off', async () => {
        const harness = await openAudit(true, false);

        expect(TestBed.inject(Router).url).toBe('/audit/sessions');
        expect(tabLabels(harness.routeNativeElement!)).toEqual([]);
        expect(harness.routeNativeElement!.textContent).toContain('sessions-page');
    });

    it('shows both tabs when both are allowed', async () => {
        const harness = await openAudit(true, true);

        expect(tabLabels(harness.routeNativeElement!)).toEqual(['Sessions', 'User actions']);
    });

    it('redirects /audit to the first allowed tab', async () => {
        await openAudit(false, true);

        expect(TestBed.inject(Router).url).toBe('/audit/actions');
    });

    it('sends the caller to the default route when no tab is allowed', async () => {
        await openAudit(false, false);

        expect(TestBed.inject(Router).url).toBe('/agents');
    });
});
