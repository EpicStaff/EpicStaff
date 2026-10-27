import { OverlayContainer } from '@angular/cdk/overlay';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef, signal, WritableSignal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import {
    ActionCode,
    CatalogResponse,
    FullMembership,
    GetMeResponse,
    MyOrgPermissionsResponse,
    OrgCapability,
    ResourceCode,
} from '@shared/models';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { ProfileService } from '../../../../../services/auth/profile.service';
import { ConfigService } from '../../../../../services/config';
import { ProfileOverviewTabComponent } from './profile-overview-tab.component';

// jsdom has no ResizeObserver; components in the tab only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const FLOW_DESIGNER = { id: 7, name: 'Flow Designer' };
const MEMBER = { id: 3, name: 'Member' };
const SUPERADMIN_ROLE = { id: 1, name: 'Superadmin' };

function membership(orgId: number, role: { id: number; name: string }): FullMembership {
    return { id: orgId, organization: { id: orgId, name: `Org ${orgId}` }, role, joined_at: '2026-01-01T00:00:00Z' };
}

function user(overrides: Partial<GetMeResponse>): GetMeResponse {
    return {
        id: 1,
        email: 'olga@example.com',
        display_name: 'Olga',
        is_superadmin: false,
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        memberships: [],
        active_organization_id: null,
        active_permissions: null,
        avatar_url: null,
        completed_tours: [],
        custom_shortcuts: {} as GetMeResponse['custom_shortcuts'],
        ...overrides,
    };
}

function catalogResource(code: ResourceCode, group: string, label: string, applicableActions: ActionCode[]) {
    return {
        code,
        label,
        group,
        description: `${label} description`,
        applicable_actions: applicableActions,
        platform_actions: [],
        recommended_with: {} as CatalogResponse['resource_types'][number]['recommended_with'],
    };
}

const CATALOG: CatalogResponse = {
    actions: [
        { code: ActionCode.Create, label: 'Create', bit: 1 },
        { code: ActionCode.Read, label: 'Read', bit: 2 },
        { code: ActionCode.Update, label: 'Update', bit: 4 },
        { code: ActionCode.Delete, label: 'Delete', bit: 8 },
    ],
    resource_types: [
        catalogResource(ResourceCode.Roles, 'admin', 'Roles', [ActionCode.Read, ActionCode.Update]),
        catalogResource(ResourceCode.Flows, 'workspace', 'Flows', [
            ActionCode.Create,
            ActionCode.Read,
            ActionCode.Delete,
        ]),
        catalogResource(ResourceCode.Agents, 'workspace', 'Agents', [ActionCode.Read, ActionCode.Update]),
    ],
};

type OrgPermissions = OrgCapability['permissions'];

describe('ProfileOverviewTabComponent roles', () => {
    let fixture: ComponentFixture<ProfileOverviewTabComponent>;
    let currentUser: WritableSignal<GetMeResponse | null>;
    let httpTesting: HttpTestingController;

    afterEach(() => {
        httpTesting.verify();
        vi.unstubAllGlobals();
    });

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        currentUser = signal<GetMeResponse | null>(null);
        TestBed.configureTestingModule({
            imports: [ProfileOverviewTabComponent],
            providers: [
                provideHttpClient(),
                provideHttpClientTesting(),
                { provide: ConfigService, useValue: { apiUrl: '/api/' } as unknown as ConfigService },
                {
                    provide: ProfileService,
                    useValue: { currentUserSignal: currentUser } as unknown as ProfileService,
                },
            ],
        });
        httpTesting = TestBed.inject(HttpTestingController);
        fixture = TestBed.createComponent(ProfileOverviewTabComponent);
    });

    function render(profile: GetMeResponse): void {
        currentUser.set(profile);
        fixture.detectChanges();
    }

    function superadmin(): GetMeResponse {
        return user({
            is_superadmin: true,
            memberships: [membership(1, SUPERADMIN_ROLE), membership(2, SUPERADMIN_ROLE)],
        });
    }

    function chipLabels(): string[] {
        return Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('.role-tag')).map((chip) =>
            chip.textContent!.trim()
        );
    }

    function orgRoleButton(orgName: string): HTMLButtonElement {
        const row = Array.from<HTMLElement>(fixture.nativeElement.querySelectorAll('app-list-row')).find(
            (listRow) => listRow.querySelector('.org-name')!.textContent!.trim() === orgName
        )!;
        return row.querySelector<HTMLButtonElement>('button.org-role')!;
    }

    function openOrgRole(orgName: string): void {
        orgRoleButton(orgName).click();
        TestBed.inject(ApplicationRef).tick();
    }

    function dialog(): HTMLElement {
        return TestBed.inject(OverlayContainer).getContainerElement();
    }

    function texts(selector: string): string[] {
        return Array.from(dialog().querySelectorAll(selector)).map((element) => element.textContent!.trim());
    }

    function orgs(...capabilities: [number, typeof MEMBER, OrgPermissions][]): MyOrgPermissionsResponse {
        return {
            is_superadmin: false,
            orgs: capabilities.map(([orgId, role, permissions]) => ({
                org: { id: orgId, name: `Org ${orgId}` },
                role,
                permissions,
            })),
        };
    }

    function respond(orgPermissions: MyOrgPermissionsResponse): void {
        httpTesting.expectOne('/api/permissions/catalog/').flush(CATALOG);
        httpTesting.expectOne('/api/permissions/me/orgs/').flush(orgPermissions);
        TestBed.inject(ApplicationRef).tick();
    }

    function openSuperadminOrgRole(): void {
        render(superadmin());
        openOrgRole('Org 2');
        httpTesting.expectOne('/api/permissions/catalog/').flush(CATALOG);
        TestBed.inject(ApplicationRef).tick();
    }

    const MEMBER_AND_DESIGNER_ORGS = orgs(
        [1, MEMBER, { [ResourceCode.Roles]: [ActionCode.Read] } as OrgPermissions],
        [2, FLOW_DESIGNER, { [ResourceCode.Flows]: [ActionCode.Create, ActionCode.Delete] } as OrgPermissions]
    );

    it('shows one non-interactive chip per role by its name, including custom roles shared by several orgs', () => {
        render(
            user({ memberships: [membership(1, FLOW_DESIGNER), membership(2, MEMBER), membership(3, FLOW_DESIGNER)] })
        );

        expect(chipLabels()).toEqual(['Flow Designer', 'Member']);
        expect(fixture.nativeElement.querySelectorAll('button.role-tag').length).toBe(0);
    });

    it("shows a superadmin a single Super Admin chip instead of their memberships' Superadmin role", () => {
        render(superadmin());

        expect(chipLabels()).toEqual(['Super Admin']);
    });

    it('names the role and the organization on the role button of each organization row', () => {
        render(user({ memberships: [membership(1, MEMBER), membership(2, FLOW_DESIGNER)] }));

        expect(orgRoleButton('Org 2').getAttribute('aria-label')).toBe('View permissions for Flow Designer in Org 2');
        expect(orgRoleButton('Org 2').textContent!.trim()).toBe('Flow Designer');
    });

    it.each([
        ['Org 1', 'Member', ['Roles'], ['Read']],
        ['Org 2', 'Flow Designer', ['Flows'], ['Create', 'Delete']],
    ])(
        'opens the permissions %s grants through its role, whichever org is active',
        (orgName, roleName, resources, actions) => {
            render(
                user({ active_organization_id: 1, memberships: [membership(1, MEMBER), membership(2, FLOW_DESIGNER)] })
            );

            openOrgRole(orgName);
            respond(MEMBER_AND_DESIGNER_ORGS);

            expect(texts('.role-name')).toEqual([roleName]);
            expect(texts('.org-name')).toEqual([orgName]);
            expect(texts('.resource-label')).toEqual(resources);
            expect(texts('.action-label')).toEqual(actions);
            expect(
                Array.from(dialog().querySelectorAll('.granted')).map((icon) => icon.getAttribute('aria-label'))
            ).toEqual(actions.map((action) => `${action}: allowed`));
        }
    );

    it('shows the empty state for a role that grants nothing', () => {
        render(user({ memberships: [membership(1, MEMBER)] }));

        openOrgRole('Org 1');
        respond(orgs([1, MEMBER, {} as OrgPermissions]));

        expect(texts('.empty-title')).toEqual(['No permissions yet']);
        expect(texts('.resource-label')).toEqual([]);
    });

    it('shows every applicable permission when a superadmin opens a role', () => {
        openSuperadminOrgRole();

        expect(texts('.role-name')).toEqual(['Super Admin']);
        expect(texts('.resource-label')).toEqual(['Roles', 'Flows', 'Agents']);
        expect(texts('.group-count')).toEqual(['2 permissions', '5 permissions']);
    });

    it('collapses a group from its header', () => {
        openSuperadminOrgRole();

        const header = dialog().querySelector<HTMLButtonElement>('.group-header')!;
        header.click();
        TestBed.inject(ApplicationRef).tick();

        expect(header.getAttribute('aria-expanded')).toBe('false');
        expect(texts('.resource-label')).toEqual(['Flows', 'Agents']);
    });

    it.each([
        ['the catalog', '/api/permissions/catalog/'],
        ['the org permissions', '/api/permissions/me/orgs/'],
    ])('says the permissions are unavailable when loading %s fails', (_source, failingUrl) => {
        render(user({ memberships: [membership(1, MEMBER)] }));

        openOrgRole('Org 1');
        httpTesting.expectOne(failingUrl).flush('boom', { status: 500, statusText: 'Server Error' });
        httpTesting.match(() => true);
        TestBed.inject(ApplicationRef).tick();

        expect(texts('.empty-title')).toEqual(['Permissions unavailable']);
        expect(dialog().querySelector('app-loading-spinner')).toBeNull();
    });

    it.each([
        ['the user left the organization', orgs([1, MEMBER, {} as OrgPermissions])],
        [
            'the role in that organization changed, even though another org still has it',
            orgs(
                [1, MEMBER, { [ResourceCode.Roles]: [ActionCode.Read] } as OrgPermissions],
                [2, FLOW_DESIGNER, { [ResourceCode.Flows]: [ActionCode.Read] } as OrgPermissions]
            ),
        ],
        [
            'the membership in that organization has no role any more',
            {
                is_superadmin: false,
                orgs: [
                    { org: { id: 1, name: 'Org 1' }, role: MEMBER, permissions: {} as OrgPermissions },
                    { org: { id: 2, name: 'Org 2' }, role: null, permissions: {} as OrgPermissions },
                ],
            },
        ],
    ])('says the role is not found when %s', (_case, freshOrgPermissions) => {
        render(user({ memberships: [membership(1, MEMBER), membership(2, MEMBER)] }));

        openOrgRole('Org 2');
        respond(freshOrgPermissions);

        expect(texts('.empty-title')).toEqual(['Role not found']);
    });

    it('shows cached permissions at once and replaces them with the refreshed ones', () => {
        TestBed.inject(PermissionsService).loadCatalog().subscribe();
        TestBed.inject(PermissionsService).loadOrgPermissions().subscribe();
        httpTesting.expectOne('/api/permissions/catalog/').flush(CATALOG);
        httpTesting
            .expectOne('/api/permissions/me/orgs/')
            .flush(orgs([1, FLOW_DESIGNER, { [ResourceCode.Roles]: [ActionCode.Read] } as OrgPermissions]));
        render(user({ memberships: [membership(1, FLOW_DESIGNER)] }));

        openOrgRole('Org 1');
        expect(texts('.resource-label')).toEqual(['Roles']);

        httpTesting
            .expectOne('/api/permissions/me/orgs/')
            .flush(orgs([1, FLOW_DESIGNER, { [ResourceCode.Agents]: [ActionCode.Update] } as OrgPermissions]));
        TestBed.inject(ApplicationRef).tick();

        expect(texts('.resource-label')).toEqual(['Agents']);
    });
});
