import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActionCode, ResourceCode } from '@shared/models';

import { PermissionsService } from '../../../../../services/auth/permissions.service';
import { FlowMenuAction, FlowMenuComponent, FlowMenuSelection } from './flow-menu.component';

interface Rendered {
    fixture: ComponentFixture<FlowMenuComponent>;
    host: HTMLElement;
    emitted: FlowMenuSelection[];
}

function render(can: (resource: ResourceCode, action: ActionCode) => boolean): Rendered {
    TestBed.configureTestingModule({
        providers: [{ provide: PermissionsService, useValue: { can } }],
    });
    const fixture = TestBed.createComponent(FlowMenuComponent);
    const emitted: FlowMenuSelection[] = [];
    fixture.componentInstance.actionSelected.subscribe((selection) => emitted.push(selection));
    fixture.detectChanges();
    return { fixture, host: fixture.nativeElement as HTMLElement, emitted };
}

function menuButton(host: HTMLElement): HTMLButtonElement {
    return host.querySelector<HTMLButtonElement>('.menu-button')!;
}

function openMenu({ fixture, host }: Rendered): void {
    menuButton(host).click();
    fixture.detectChanges();
}

function menuItems(host: HTMLElement): HTMLElement[] {
    return Array.from(host.querySelectorAll<HTMLElement>('.context-menu .menu-item'));
}

function itemLabels(host: HTMLElement): string[] {
    return menuItems(host).map((item) => item.textContent?.trim() ?? '');
}

describe('FlowMenuComponent "View Details" item', () => {
    it('sits between Export and Delete, after every other item', () => {
        const rendered = render(() => true);
        openMenu(rendered);

        expect(itemLabels(rendered.host)).toEqual([
            'View Sessions',
            'Run',
            'Edit',
            'Copy',
            'Export',
            'View Details',
            'Delete',
        ]);
    });

    it("emits each item's own action", () => {
        const expected: Record<string, FlowMenuAction> = {
            'View Sessions': 'viewSessions',
            Run: 'run',
            Edit: 'rename',
            Copy: 'copy',
            Export: 'export',
            'View Details': 'viewDetails',
            Delete: 'delete',
        };
        const rendered = render(() => true);

        for (const label of Object.keys(expected)) {
            openMenu(rendered);
            menuItems(rendered.host)
                .find((item) => item.textContent?.trim() === label)!
                .click();
            rendered.fixture.detectChanges();
        }

        expect(rendered.emitted.map((selection) => selection.action)).toEqual(Object.values(expected));
    });

    it('emits viewDetails with the ⋮ button as the trigger, and closes the menu', () => {
        const rendered = render(() => true);
        openMenu(rendered);

        menuItems(rendered.host)
            .find((item) => item.textContent?.trim() === 'View Details')!
            .click();
        rendered.fixture.detectChanges();

        // The dialog closes back to the ⋮ button: the clicked item is destroyed with the menu.
        expect(rendered.emitted).toEqual([{ action: 'viewDetails', trigger: menuButton(rendered.host) }]);
        expect(menuItems(rendered.host)).toHaveLength(0);
    });
});
