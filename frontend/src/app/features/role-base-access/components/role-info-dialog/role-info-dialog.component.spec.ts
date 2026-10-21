import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, CatalogResponse, GetRoleResponse } from '@shared/models';
import {
    ROLE_PERMISSION_EXTENSIONS,
    RolePermissionExtension,
    RolePermissionExtensionRoleState,
    RolePermissionExtensionRow,
} from '@shared/services';
import { EMPTY, Observable, of, Subject } from 'rxjs';
import type { Mock } from 'vitest';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { RoleInfoDialogComponent } from './role-info-dialog.component';

class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const CATALOG: CatalogResponse = {
    actions: [
        { code: ActionCode.Read, label: 'View', bit: 1 },
        { code: ActionCode.Update, label: 'Edit', bit: 4 },
    ],
    resource_types: [],
};

function row(code: string, label: string): RolePermissionExtensionRow {
    return {
        code,
        label,
        description: '',
        iconUrl: null,
        actions: [
            { action: ActionCode.Read, description: `Open ${label}.`, requires: [] },
            { action: ActionCode.Update, description: `Change ${label}.`, requires: [ActionCode.Read] },
        ],
        grantable: [],
    };
}

const MEMBER: GetRoleResponse = {
    id: 3,
    name: 'Member',
    description: 'Works in the organization.',
    is_built_in: true,
    scope: 'global',
    org_id: null,
    org: null,
    assigned_count: 4,
    permissions: [],
};

describe('RoleInfoDialogComponent with extension rows', () => {
    let fixture: ComponentFixture<RoleInfoDialogComponent>;
    let element: HTMLElement;
    let roleState: Mock<(roleId: number, orgId?: number) => Observable<RolePermissionExtensionRoleState>>;

    function render(role: GetRoleResponse): void {
        TestBed.overrideProvider(DIALOG_DATA, { useValue: role });
        fixture = TestBed.createComponent(RoleInfoDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    }

    function pluginsGroup(): HTMLElement | null {
        return element.querySelector<HTMLElement>('[data-group-key="plugins"]');
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        // The manifest defaults of a built-in role: Member gets View on Weather, nothing on Atlas.
        roleState = vi.fn(() =>
            of({
                rows: [row('plugin:weather', 'Weather'), row('plugin:atlas', 'Atlas')],
                granted: [
                    { code: 'plugin:weather', actions: [ActionCode.Read] },
                    { code: 'plugin:atlas', actions: [] },
                ],
                editable: false,
            })
        );
        const extension: RolePermissionExtension = {
            groupKey: 'plugins',
            groupLabel: 'Plugins',
            groupIconClass: 'ti ti-puzzle',
            isActive: () => true,
            rowsForOrg: () => of([]),
            roleState,
            saveRole: () => EMPTY,
        };
        TestBed.configureTestingModule({
            imports: [RoleInfoDialogComponent],
            providers: [
                { provide: DialogRef, useValue: { close: vi.fn() } },
                { provide: DIALOG_DATA, useValue: MEMBER },
                { provide: Dialog, useValue: { open: vi.fn() } },
                {
                    provide: PermissionsService,
                    useValue: {
                        catalog: signal(CATALOG),
                        loadCatalog: () => of(CATALOG),
                        isSuperadmin: false,
                        orgsWith: () => [{ id: 1, name: 'Org A' }],
                    },
                },
                { provide: ROLE_PERMISSION_EXTENSIONS, useValue: [extension] },
            ],
        });
    });

    afterEach(() => vi.unstubAllGlobals());

    it("asks for a built-in role's rows without an organization", () => {
        render(MEMBER);

        expect(roleState).toHaveBeenCalledWith(MEMBER.id, undefined);
    });

    it('shows the rows the role holds read-only, with only the actions it holds', () => {
        render(MEMBER);

        const weatherBoxes = Array.from(
            element.querySelectorAll<HTMLInputElement>('[data-resource-code="plugin:weather"] input[type="checkbox"]')
        );

        expect(pluginsGroup()?.querySelector('.group-name')?.textContent?.trim()).toBe('Plugins');
        expect(weatherBoxes).toHaveLength(1);
        expect(weatherBoxes[0].checked).toBe(true);
        expect(weatherBoxes[0].disabled).toBe(true);
        // A row the role holds nothing on is left out, as for catalog rows.
        expect(element.querySelector('[data-resource-code="plugin:atlas"]')).toBeNull();
        // Read-only: no bulk controls.
        expect(element.querySelector('[data-group-key="plugins"] .resource-row.bulk')).toBeNull();
    });

    it("shows the built-in Superadmin role's extension rows read-only, like any built-in role's", () => {
        const superadmin: GetRoleResponse = { ...MEMBER, id: 1, name: 'Superadmin', description: 'Administrators.' };
        roleState.mockReturnValueOnce(
            of({
                rows: [row('plugin:weather', 'Weather')],
                granted: [{ code: 'plugin:weather', actions: [ActionCode.Read, ActionCode.Update] }],
                editable: false,
            })
        );
        render(superadmin);

        expect(roleState).toHaveBeenCalledWith(superadmin.id, undefined);
        const weatherBoxes = Array.from(
            element.querySelectorAll<HTMLInputElement>('[data-resource-code="plugin:weather"] input[type="checkbox"]')
        );
        expect(weatherBoxes).toHaveLength(2);
        expect(weatherBoxes.every((box) => box.checked && box.disabled)).toBe(true);
        expect(pluginsGroup()?.querySelector('.group-count')?.textContent?.replace(/\s+/g, ' ').trim()).toBe('2 / 2');
        expect(element.querySelector('[data-group-key="plugins"] .resource-row.bulk')).toBeNull();
    });

    it('keeps Duplicate disabled until the extension rows have loaded', () => {
        const state = new Subject<RolePermissionExtensionRoleState>();
        roleState.mockReturnValueOnce(state);
        render(MEMBER);
        const duplicate = (): HTMLButtonElement =>
            Array.from(element.querySelectorAll<HTMLButtonElement>('.header button')).find(
                (button) => button.textContent?.trim() === 'Duplicate Role'
            )!;

        expect(duplicate().disabled).toBe(true);

        state.next({ rows: [], granted: [], editable: false });
        state.complete();
        fixture.detectChanges();

        expect(duplicate().disabled).toBe(false);
    });
});
