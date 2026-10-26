import { Dialog, DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { ActionCode, CatalogResponse, GetRoleResponse, ResourceCode } from '@shared/models';
import {
    ROLE_PERMISSION_EXTENSIONS,
    RolePermissionExtension,
    RolePermissionExtensionError,
    RolePermissionExtensionGrant,
    RolePermissionExtensionRoleState,
    RolePermissionExtensionRow,
} from '@shared/services';
import { EMPTY, Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { PermissionsService } from '../../../../services/auth/permissions.service';
import { ToastService } from '../../../../services/notifications';
import { OrganizationsStorageService } from '../../services/admin/organizations-storage.service';
import { RolesService } from '../../services/admin/roles.service';
import { CreateRoleDialogComponent, CreateRoleDialogData } from './create-role-dialog.component';

// jsdom has no ResizeObserver; app-button's overflow directive only needs it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

const CATALOG: CatalogResponse = {
    actions: [
        { code: ActionCode.Read, label: 'View', bit: 1 },
        { code: ActionCode.Create, label: 'Create', bit: 2 },
        { code: ActionCode.Update, label: 'Edit', bit: 4 },
    ],
    resource_types: [
        {
            code: ResourceCode.Flows,
            label: 'Flows',
            group: 'workspace',
            description: 'Flows of the organization.',
            applicable_actions: [ActionCode.Read, ActionCode.Create, ActionCode.Update],
            platform_actions: [],
            recommended_with: {
                [ActionCode.Create]: [],
                [ActionCode.Read]: [],
                [ActionCode.Update]: [],
                [ActionCode.Delete]: [],
                [ActionCode.Export]: [],
                [ActionCode.Use]: [],
                [ActionCode.List]: [],
            },
        },
    ],
};

/** A row the fake extension adds: View and Edit, of which the actor may grant View only. */
const WEATHER_ROW: RolePermissionExtensionRow = {
    code: 'plugin:weather',
    label: 'Weather',
    description: '',
    iconUrl: '/icons/weather.svg',
    actions: [
        { action: ActionCode.Read, description: 'Open Weather.', requires: [] },
        { action: ActionCode.Update, description: 'Change places.', requires: [ActionCode.Read] },
    ],
    grantable: [ActionCode.Read],
};

const ORG_A = { id: 1, name: 'Org A' };

function role(overrides: Partial<GetRoleResponse> = {}): GetRoleResponse {
    return {
        id: 7,
        name: 'Forecasters',
        description: null,
        is_built_in: false,
        scope: 'org',
        org_id: ORG_A.id,
        org: ORG_A,
        assigned_count: 0,
        permissions: [{ resource_type: ResourceCode.Flows, actions: [ActionCode.Read] }],
        ...overrides,
    };
}

function stateWith(granted: RolePermissionExtensionGrant[]): RolePermissionExtensionRoleState {
    return { rows: [WEATHER_ROW], granted, editable: true };
}

/** A fake extension: role-base-access only ever sees the token's contract. */
function createExtension() {
    return {
        groupKey: 'plugins',
        groupLabel: 'Plugins',
        groupIconClass: 'ti ti-puzzle',
        isActive: vi.fn(() => true),
        rowsForOrg: vi.fn<(orgId: number) => Observable<RolePermissionExtensionRow[]>>(() => of([WEATHER_ROW])),
        roleState: vi.fn<(roleId: number, orgId?: number) => Observable<RolePermissionExtensionRoleState>>(() =>
            of(stateWith([{ code: WEATHER_ROW.code, actions: [ActionCode.Read] }]))
        ),
        saveRole: vi.fn<
            (roleId: number, granted: RolePermissionExtensionGrant[]) => Observable<RolePermissionExtensionRoleState>
        >((_roleId, granted) => of(stateWith(granted))),
    } satisfies RolePermissionExtension;
}

describe('CreateRoleDialogComponent with extension rows', () => {
    let fixture: ComponentFixture<CreateRoleDialogComponent>;
    let element: HTMLElement;
    let dialogRef: { close: Mock; keydownEvents: typeof EMPTY };
    let rolesService: {
        createRole: Mock<() => Observable<GetRoleResponse>>;
        updateRole: Mock<(id: number) => Observable<GetRoleResponse>>;
    };
    let extension: ReturnType<typeof createExtension>;
    let toast: { success: Mock; error: Mock };

    function render(data: CreateRoleDialogData): void {
        TestBed.configureTestingModule({
            imports: [CreateRoleDialogComponent],
            providers: [
                { provide: DialogRef, useValue: dialogRef },
                { provide: DIALOG_DATA, useValue: data },
                { provide: Dialog, useValue: { open: vi.fn() } },
                {
                    provide: PermissionsService,
                    useValue: {
                        catalog: signal(CATALOG),
                        loadCatalog: () => of(CATALOG),
                        isSuperadmin: false,
                        // The actor may view and create flows in Org A, not edit them.
                        canInOrg: (_orgId: number, _resource: ResourceCode, action: ActionCode) =>
                            action !== ActionCode.Update,
                        orgsWith: () => [ORG_A],
                    },
                },
                { provide: RolesService, useValue: rolesService },
                { provide: OrganizationsStorageService, useValue: { getOrganizations: () => of([]) } },
                { provide: ToastService, useValue: toast },
                { provide: ROLE_PERMISSION_EXTENSIONS, useValue: [extension] },
            ],
        });
        fixture = TestBed.createComponent(CreateRoleDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        settle();
    }

    function settle(): void {
        fixture.detectChanges();
        TestBed.tick();
        fixture.detectChanges();
    }

    /** The cells of a row, one per catalog action (View, Create, Edit). */
    function cells(code: string): HTMLElement[] {
        return Array.from(element.querySelectorAll<HTMLElement>(`[data-resource-code="${code}"] .action-cell`));
    }

    function cellBox(code: string, column: number): HTMLInputElement | null {
        return cells(code)[column].querySelector<HTMLInputElement>('input[type="checkbox"]');
    }

    function clickPrimary(): void {
        element.querySelector<HTMLButtonElement>('.header app-button[type="primary"] button')!.click();
        settle();
    }

    function title(): string | undefined {
        return element.querySelector('.header .title')?.textContent?.trim();
    }

    function headerButton(text: string): HTMLButtonElement {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('.header button')).find(
            (button) => button.textContent?.trim() === text
        )!;
    }

    function ticked(code: string): boolean[] {
        return [0, 2].map((column) => cellBox(code, column)!.checked);
    }

    beforeEach(() => {
        vi.stubGlobal('ResizeObserver', ResizeObserverStub);
        dialogRef = { close: vi.fn(), keydownEvents: EMPTY };
        rolesService = {
            createRole: vi.fn(() => of(role())),
            updateRole: vi.fn((id: number) => of(role({ id }))),
        };
        extension = createExtension();
        toast = { success: vi.fn(), error: vi.fn() };
    });

    afterEach(() => vi.unstubAllGlobals());

    it("merges the extension's rows as their own group after the catalog groups", () => {
        render({ preselectedOrgId: ORG_A.id });

        const groups = Array.from(element.querySelectorAll<HTMLElement>('.group')).map((group) => ({
            key: group.dataset['groupKey'],
            name: group.querySelector('.group-name')?.textContent?.trim(),
        }));
        expect(groups).toEqual([
            { key: 'workspace', name: 'Workspace Resources' },
            { key: 'plugins', name: 'Plugins' },
        ]);
        expect(extension.rowsForOrg).toHaveBeenCalledWith(ORG_A.id);
        // A cell only for the row's own actions; the Create column shows a dash.
        expect(cellBox(WEATHER_ROW.code, 0)).not.toBeNull();
        expect(cells(WEATHER_ROW.code)[1].textContent?.trim()).toBe('—');
        expect(cellBox(WEATHER_ROW.code, 2)).not.toBeNull();
    });

    it("disables the cells outside the actor's ceiling and shows each action's description as the tooltip", () => {
        render({ preselectedOrgId: ORG_A.id });

        expect(cellBox(WEATHER_ROW.code, 0)!.disabled).toBe(false);
        expect(cellBox(WEATHER_ROW.code, 2)!.disabled).toBe(true);
        const tooltips = fixture.debugElement
            .queryAll(By.css(`[data-resource-code="${WEATHER_ROW.code}"] .action-cell`))
            .map((cell) => cell.injector.get(MatTooltip).message);
        expect(tooltips).toEqual(['Open Weather.', '', 'Change places.']);
    });

    it('creates the role first, without the extension cells, then saves the extension rows for the new role', () => {
        render({ preselectedOrgId: ORG_A.id });
        fixture.componentInstance.form.controls.name.setValue('Forecasters');
        cellBox(WEATHER_ROW.code, 0)!.click();
        settle();

        clickPrimary();

        expect(rolesService.createRole).toHaveBeenCalledWith({
            org_id: ORG_A.id,
            name: 'Forecasters',
            description: null,
            permissions: [],
        });
        expect(extension.saveRole).toHaveBeenCalledWith(7, [{ code: WEATHER_ROW.code, actions: [ActionCode.Read] }]);
        expect(rolesService.createRole.mock.invocationCallOrder[0]).toBeLessThan(
            extension.saveRole.mock.invocationCallOrder[0]
        );
        expect(dialogRef.close).toHaveBeenCalledWith({ action: 'created', role: role() });
    });

    it('switches to editing the created role when its extension rows fail, and saves them on the next Save', () => {
        render({ preselectedOrgId: ORG_A.id });
        fixture.componentInstance.form.controls.name.setValue('Forecasters');
        cellBox(WEATHER_ROW.code, 0)!.click();
        extension.saveRole.mockReturnValueOnce(
            throwError(() => new RolePermissionExtensionError("You can't give plugin permissions you don't have."))
        );
        settle();

        clickPrimary();

        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(title()).toBe('Edit role in Org A');
        expect(element.querySelector('.permission-notice--error')?.textContent).toContain(
            "The role was created, but its Plugins permissions were not. You can't give plugin permissions"
        );
        expect(element.querySelector('.subheader app-select')).toBeNull();

        clickPrimary();

        expect(rolesService.createRole).toHaveBeenCalledTimes(1);
        expect(rolesService.updateRole).toHaveBeenCalledWith(7, {
            name: 'Forecasters',
            description: null,
            permissions: [],
        });
        expect(extension.saveRole).toHaveBeenCalledTimes(2);
        expect(dialogRef.close).toHaveBeenCalledWith({ action: 'created', role: role() });
        // This dialog created the role, even though the second save was an update.
        expect(toast.success).toHaveBeenCalledWith('Role created');
    });

    it('reports the created role when the dialog is cancelled after a failed extension save', () => {
        render({ preselectedOrgId: ORG_A.id });
        fixture.componentInstance.form.controls.name.setValue('Forecasters');
        cellBox(WEATHER_ROW.code, 0)!.click();
        extension.saveRole.mockReturnValueOnce(throwError(() => new RolePermissionExtensionError('Refused.')));
        settle();
        clickPrimary();

        fixture.componentInstance.onCancel();

        expect(dialogRef.close).toHaveBeenCalledWith({ action: 'created', role: role() });
    });

    describe('editing a role', () => {
        it("loads the role's extension rows and skips their save when nothing in them changed", () => {
            render({ role: role() });

            expect(extension.roleState).toHaveBeenCalledWith(7, undefined);
            expect(cellBox(WEATHER_ROW.code, 0)!.checked).toBe(true);

            clickPrimary();

            expect(rolesService.updateRole).toHaveBeenCalledTimes(1);
            expect(extension.saveRole).not.toHaveBeenCalled();
            expect(dialogRef.close).toHaveBeenCalledWith({ action: 'updated', role: role() });
        });

        it('saves every row of the extension when one of them changed', () => {
            render({ role: role() });

            cellBox(WEATHER_ROW.code, 0)!.click();
            settle();
            clickPrimary();

            expect(extension.saveRole).toHaveBeenCalledWith(7, [{ code: WEATHER_ROW.code, actions: [] }]);
        });

        it('keeps read-only rows untouched by Select All and Clear All', () => {
            extension.roleState.mockReturnValueOnce(
                of({ ...stateWith([{ code: WEATHER_ROW.code, actions: [ActionCode.Read] }]), editable: false })
            );
            render({ role: role() });

            expect(cellBox(WEATHER_ROW.code, 0)!.disabled).toBe(true);
            fixture.componentInstance.onClearAll();
            settle();
            clickPrimary();

            expect(extension.saveRole).not.toHaveBeenCalled();
        });
    });

    it("preselects a duplicated role's extension cells where the target org has the same rows", () => {
        render({
            duplicateSource: {
                name: 'Forecasters',
                description: null,
                permissions: [`${ResourceCode.Flows}:${ActionCode.Read}`],
                extensionPermissions: ['plugin:weather:read', 'plugin:atlas:read'],
                orgId: ORG_A.id,
            },
        });

        expect(cellBox(WEATHER_ROW.code, 0)!.checked).toBe(true);

        clickPrimary();

        expect(rolesService.createRole).toHaveBeenCalledWith(
            expect.objectContaining({
                permissions: [{ resource_type: ResourceCode.Flows, actions: [ActionCode.Read] }],
            })
        );
        expect(extension.saveRole).toHaveBeenCalledWith(7, [{ code: WEATHER_ROW.code, actions: [ActionCode.Read] }]);
    });

    it('neither asks nor shows an inactive extension', () => {
        extension.isActive.mockReturnValue(false);
        render({ preselectedOrgId: ORG_A.id });

        expect(extension.rowsForOrg).not.toHaveBeenCalled();
        expect(element.querySelector('[data-group-key="plugins"]')).toBeNull();
    });

    it('shows why the extension rows could not be loaded and saves the role without them', () => {
        extension.rowsForOrg.mockReturnValueOnce(
            throwError(() => new RolePermissionExtensionError("Couldn't load the plugin permissions."))
        );
        render({ preselectedOrgId: ORG_A.id });
        fixture.componentInstance.form.controls.name.setValue('Forecasters');
        settle();

        expect(element.querySelector('.permission-notice--error')?.textContent?.trim()).toBe(
            "Couldn't load the plugin permissions."
        );

        clickPrimary();

        expect(rolesService.createRole).toHaveBeenCalledTimes(1);
        expect(extension.saveRole).not.toHaveBeenCalled();
    });

    it('keeps Save disabled while the extension rows load', () => {
        const rows = new Subject<RolePermissionExtensionRow[]>();
        extension.rowsForOrg.mockReturnValueOnce(rows);
        render({ preselectedOrgId: ORG_A.id });
        fixture.componentInstance.form.controls.name.setValue('Forecasters');
        settle();

        expect(headerButton('Create').disabled).toBe(true);

        rows.next([WEATHER_ROW]);
        rows.complete();
        settle();

        expect(headerButton('Create').disabled).toBe(false);
    });

    it('keeps Duplicate disabled until the extension rows of the role have loaded', () => {
        const state = new Subject<RolePermissionExtensionRoleState>();
        extension.roleState.mockReturnValueOnce(state);
        render({ role: role() });

        expect(headerButton('Duplicate Role').disabled).toBe(true);

        state.next(stateWith([{ code: WEATHER_ROW.code, actions: [ActionCode.Read] }]));
        state.complete();
        settle();

        expect(headerButton('Duplicate Role').disabled).toBe(false);
    });

    it("says in one line which of the copied role's cells were left out for being outside the ceiling", () => {
        render({
            duplicateSource: {
                name: 'Forecasters',
                description: null,
                permissions: [],
                extensionPermissions: ['plugin:weather:read', 'plugin:weather:update'],
                orgId: ORG_A.id,
            },
        });

        expect(ticked(WEATHER_ROW.code)).toEqual([true, false]);
        expect(element.querySelector('.permission-notice--warning')?.textContent?.trim()).toBe(
            "1 Plugins permission of the copied role left out: you can't grant them in this organization."
        );
    });

    describe('required actions', () => {
        const FULLY_GRANTABLE: RolePermissionExtensionRow = {
            ...WEATHER_ROW,
            grantable: [ActionCode.Read, ActionCode.Update],
        };

        it('ticks View along with Edit, and clears Edit with View', () => {
            extension.rowsForOrg.mockReturnValueOnce(of([FULLY_GRANTABLE]));
            render({ preselectedOrgId: ORG_A.id });

            cellBox(WEATHER_ROW.code, 2)!.click();
            settle();
            expect(ticked(WEATHER_ROW.code)).toEqual([true, true]);

            cellBox(WEATHER_ROW.code, 0)!.click();
            settle();
            expect(ticked(WEATHER_ROW.code)).toEqual([false, false]);
        });

        it('shows no "related permissions" banner for extension rows', () => {
            extension.rowsForOrg.mockReturnValueOnce(of([FULLY_GRANTABLE]));
            render({ preselectedOrgId: ORG_A.id });

            cellBox(WEATHER_ROW.code, 2)!.click();
            settle();

            expect(element.querySelector('.related-banner.is-open')).toBeNull();
        });

        it('cannot tick an action whose required action is outside the ceiling and not held', () => {
            extension.rowsForOrg.mockReturnValueOnce(of([{ ...WEATHER_ROW, grantable: [ActionCode.Update] }]));
            render({ preselectedOrgId: ORG_A.id });

            expect(cellBox(WEATHER_ROW.code, 0)!.disabled).toBe(true);
            expect(cellBox(WEATHER_ROW.code, 2)!.disabled).toBe(true);
        });
    });

    describe('cells outside the ceiling', () => {
        /** The role holds View and Edit on Weather; the actor may grant View only. */
        function renderHoldingEdit(): void {
            extension.roleState.mockReturnValueOnce(
                of(stateWith([{ code: WEATHER_ROW.code, actions: [ActionCode.Read, ActionCode.Update] }]))
            );
            render({ role: role() });
        }

        it('keeps View, which the held Edit requires, ticked and disabled', () => {
            renderHoldingEdit();

            expect(ticked(WEATHER_ROW.code)).toEqual([true, true]);
            expect(cellBox(WEATHER_ROW.code, 0)!.disabled).toBe(true);
            expect(cellBox(WEATHER_ROW.code, 2)!.disabled).toBe(true);
        });

        it('are left as they are by Clear All and Select All, so nothing is saved for them', () => {
            renderHoldingEdit();

            fixture.componentInstance.onClearAll();
            settle();
            expect(ticked(WEATHER_ROW.code)).toEqual([true, true]);
            fixture.componentInstance.onSelectAll();
            settle();
            expect(ticked(WEATHER_ROW.code)).toEqual([true, true]);

            clickPrimary();

            expect(extension.saveRole).not.toHaveBeenCalled();
        });
    });
});
