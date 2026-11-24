import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CollectionsExportControlComponent } from './collections-export-control.component';

/** Owns select mode and the selection, as the collections list does. */
@Component({
    imports: [CollectionsExportControlComponent],
    template: `
        <app-collections-export-control
            [selectMode]="selectMode()"
            [selectedCount]="selectedCount()"
            (selectModeEntered)="selectMode.set(true)"
            (selectAllToggled)="selectedCount.set(2)"
            (cleared)="leaveSelectMode()"
            (exportConfirmed)="leaveSelectMode()"
        />
    `,
})
class ListStubComponent {
    readonly selectMode = signal(false);
    readonly selectedCount = signal(0);

    leaveSelectMode(): void {
        this.selectMode.set(false);
        this.selectedCount.set(0);
    }
}

let fixture: ComponentFixture<ListStubComponent>;

function render(): void {
    fixture = TestBed.createComponent(ListStubComponent);
    fixture.detectChanges();
}

function buttonLabelled(label: string): HTMLButtonElement {
    const button = [...(fixture.nativeElement as HTMLElement).querySelectorAll('button')].find(
        (candidate) => candidate.getAttribute('aria-label') === label
    );
    expect(button, `a "${label}" button`).toBeDefined();
    return button!;
}

/** Clicks the button with this label, as a user does: it takes the focus first. Waits for the render after. */
async function click(label: string): Promise<void> {
    const button = buttonLabelled(label);
    button.focus();
    button.click();
    await settle();
}

async function settle(): Promise<void> {
    fixture.detectChanges();
    await fixture.whenStable();
}

/** Opens the chevron's menu and picks one of its items; the items render in an overlay. */
async function pickFromMenu(label: string): Promise<void> {
    await click('Selection options');
    const item = [...document.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')].find(
        (candidate) => candidate.textContent?.trim() === label
    );
    expect(item, `a "${label}" menu item`).toBeDefined();
    item!.focus();
    item!.click();
    await settle();
}

function focusedLabel(): string | null {
    return document.activeElement?.getAttribute('aria-label') ?? null;
}

describe('CollectionsExportControlComponent focus', () => {
    it.each([
        { way: 'the export button', enter: () => click('Export collections') },
        { way: "the menu's Select", enter: () => pickFromMenu('Select') },
        { way: "the menu's Select all", enter: () => pickFromMenu('Select all') },
    ])('moves the focus to cancel when select mode is entered with $way', async ({ enter }) => {
        render();

        await enter();

        expect(focusedLabel()).toBe('Cancel selection');
    });

    it.each([
        { way: 'cancel', leave: () => click('Cancel selection') },
        { way: 'confirm', leave: () => click('Export selected') },
    ])('moves the focus back to the export button when select mode is left with $way', async ({ leave }) => {
        render();
        await pickFromMenu('Select all');

        await leave();

        expect(focusedLabel()).toBe('Export collections');
    });
});
