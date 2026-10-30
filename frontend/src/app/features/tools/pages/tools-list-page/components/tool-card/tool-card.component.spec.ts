import { OverlayContainer } from '@angular/cdk/overlay';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { LABELS_STORE } from '@shared/services';
import { of } from 'rxjs';

import { PermissionsService } from '../../../../../../services/auth/permissions.service';
import { ToolsLabelsStorageService } from '../../../../services/tools-labels-storage.service';
import { ToolCardComponent } from './tool-card.component';
import { ToolCardMenuActionEvent, ToolCardVM } from './tool-card.model';

const CUSTOM_TOOL: ToolCardVM = {
    id: 3,
    kind: 'custom',
    name: 'Local/Remote GitHub Search Tool',
    description: 'Searches GitHub',
    labelIds: [],
    favorite: false,
    builtIn: false,
};

const MCP_TOOL: ToolCardVM = { ...CUSTOM_TOOL, id: 9, kind: 'mcp', name: 'Weather MCP' };

interface Rendered {
    fixture: ComponentFixture<ToolCardComponent>;
    overlay: HTMLElement;
    emitted: ToolCardMenuActionEvent[];
}

function render(tool: ToolCardVM, canWrite = true): Rendered {
    const labels = { labels: signal([]), labelTree: signal([]), loadLabels: () => of([]) };
    TestBed.configureTestingModule({
        providers: [
            { provide: PermissionsService, useValue: { can: () => canWrite } },
            { provide: ToolsLabelsStorageService, useValue: labels },
            { provide: LABELS_STORE, useValue: labels },
        ],
    });
    const fixture = TestBed.createComponent(ToolCardComponent);
    fixture.componentRef.setInput('tool', tool);
    const emitted: Rendered['emitted'] = [];
    fixture.componentInstance.menuAction.subscribe((event) => emitted.push(event));
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, overlay, emitted };
}

function menuButton(fixture: ComponentFixture<ToolCardComponent>): HTMLButtonElement {
    return (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.menu-btn')!;
}

function openMenu(fixture: ComponentFixture<ToolCardComponent>): void {
    menuButton(fixture).click();
    fixture.detectChanges();
}

function menuItems(overlay: HTMLElement): HTMLButtonElement[] {
    return Array.from(overlay.querySelectorAll<HTMLButtonElement>('.menu-item'));
}

function menuLabels(overlay: HTMLElement): string[] {
    return menuItems(overlay).map((item) => item.textContent?.trim() ?? '');
}

function viewDetailsItem(overlay: HTMLElement): HTMLButtonElement | undefined {
    return menuItems(overlay).find((item) => item.textContent?.trim() === 'View Details');
}

describe('ToolCardComponent "View Details" menu item', () => {
    it('emits view_details for a custom tool with the menu trigger, and closes the menu', () => {
        const { fixture, overlay, emitted } = render(CUSTOM_TOOL);
        openMenu(fixture);

        viewDetailsItem(overlay)!.click();
        fixture.detectChanges();

        // The details dialog closes back to the trigger: the focused menu item dies with the menu.
        expect(emitted).toEqual([{ tool: CUSTOM_TOOL, action: 'view_details', trigger: menuButton(fixture) }]);
        expect(menuItems(overlay)).toHaveLength(0);
    });

    it('emits view_details for an MCP tool', () => {
        const { fixture, overlay, emitted } = render(MCP_TOOL);
        openMenu(fixture);

        viewDetailsItem(overlay)!.click();

        expect(emitted).toEqual([{ tool: MCP_TOOL, action: 'view_details', trigger: menuButton(fixture) }]);
    });

    it('sits right above Delete', () => {
        const { fixture, overlay } = render(CUSTOM_TOOL);
        openMenu(fixture);

        expect(menuLabels(overlay).slice(-2)).toEqual(['View Details', 'Delete']);
    });

    it('is offered to a user who can only read tools', () => {
        const { fixture, overlay } = render(CUSTOM_TOOL, false);
        openMenu(fixture);

        expect(menuLabels(overlay)).toEqual(['Show Used Places', 'View Details']);
    });

    it('is hidden for a built-in tool, which has no author', () => {
        const { fixture, overlay } = render({ ...CUSTOM_TOOL, builtIn: true });
        openMenu(fixture);

        expect(menuItems(overlay).length).toBeGreaterThan(0);
        expect(viewDetailsItem(overlay)).toBeUndefined();
    });
});

describe('ToolCardComponent "Duplicate" menu item', () => {
    function duplicateItem(overlay: HTMLElement): HTMLButtonElement {
        return menuItems(overlay).find((item) => item.textContent?.trim() === 'Duplicate')!;
    }

    it('does nothing for a tool this user may not copy, and says why', () => {
        const reason = 'This code reads secrets. Copying it requires the Use permission on Secrets.';
        const { fixture, overlay, emitted } = render({ ...CUSTOM_TOOL, copyBlockedReason: reason });
        openMenu(fixture);

        duplicateItem(overlay).click();
        fixture.detectChanges();

        expect(emitted).toEqual([]);
        expect(duplicateItem(overlay).getAttribute('aria-disabled')).toBe('true');
        const tooltip = fixture.debugElement
            .queryAll(By.directive(MatTooltip))
            .find((debugElement) => debugElement.nativeElement === duplicateItem(overlay));
        expect(tooltip?.injector.get(MatTooltip).message).toBe(reason);
    });

    it('emits duplicate for a tool this user may copy', () => {
        const { fixture, overlay, emitted } = render(CUSTOM_TOOL);
        openMenu(fixture);

        duplicateItem(overlay).click();

        expect(emitted.map((event) => event.action)).toEqual(['duplicate']);
    });
});
