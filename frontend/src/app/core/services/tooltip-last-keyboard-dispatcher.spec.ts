import { Dialog } from '@angular/cdk/dialog';
import { OverlayKeyboardDispatcher } from '@angular/cdk/overlay';
import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatTooltip } from '@angular/material/tooltip';

import { EnterSubmitDirective } from '../../shared/directives/enter-submit.directive';
import { TooltipLastKeyboardDispatcher } from './tooltip-last-keyboard-dispatcher';

@Component({
    imports: [MatTooltip, EnterSubmitDirective],
    template: `
        <div (appEnterSubmit)="submits = submits + 1">
            <input
                type="text"
                aria-label="Flow name"
                matTooltip="The name the flow list shows"
            />
        </div>
    `,
})
class NameDialogComponent {
    submits = 0;
}

@Component({
    imports: [MatTooltip],
    template: `<input
        type="text"
        aria-label="Search"
        matTooltip="Searches flow names"
    />`,
})
class PageComponent {}

describe('TooltipLastKeyboardDispatcher', () => {
    const tooltip = (): string | undefined => document.querySelector('.mat-mdc-tooltip')?.textContent?.trim();

    /** Runs change detection and the tooltip's zero-delay show and hide timers. */
    async function settle(): Promise<void> {
        TestBed.tick();
        await new Promise((resolve) => setTimeout(resolve));
        TestBed.tick();
    }

    /** A key press as a browser sends it: from the focused element, with keyCode (the CDK reads Escape by it). */
    function press(key: string, keyCode: number): void {
        const target = document.activeElement ?? document.body;
        target.dispatchEvent(new KeyboardEvent('keydown', { key, keyCode, bubbles: true, cancelable: true }));
    }

    /** Tabs into the field, so the CDK sees keyboard focus and the tooltip shows. */
    async function tabInto(field: HTMLElement): Promise<void> {
        press('Tab', 9);
        field.focus();
        await settle();
    }

    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [{ provide: OverlayKeyboardDispatcher, useClass: TooltipLastKeyboardDispatcher }],
        });
    });

    afterEach(() => {
        TestBed.inject(Dialog).closeAll();
    });

    describe('in a dialog', () => {
        async function openDialog(): Promise<{
            dialog: Dialog;
            content: NameDialogComponent;
            field: HTMLInputElement;
        }> {
            const dialog = TestBed.inject(Dialog);
            const content = dialog.open(NameDialogComponent).componentInstance!;
            await settle();
            const field = document.querySelector<HTMLInputElement>('.cdk-dialog-container input')!;
            await tabInto(field);
            return { dialog, content, field };
        }

        it('shows the field tooltip on keyboard focus', async () => {
            await openDialog();

            expect(tooltip()).toBe('The name the flow list shows');
        });

        it('submits the dialog on Enter while the tooltip shows', async () => {
            const { content } = await openDialog();

            press('Enter', 13);

            expect(content.submits).toBe(1);
        });

        it('closes the dialog with one Escape while the tooltip shows', async () => {
            const { dialog } = await openDialog();

            press('Escape', 27);
            await settle();

            expect(dialog.openDialogs).toEqual([]);
        });
    });

    it('hides a visible tooltip on Escape when no dialog is open', async () => {
        const fixture = TestBed.createComponent(PageComponent);
        fixture.autoDetectChanges();
        await settle();
        await tabInto(fixture.nativeElement.querySelector('input'));
        expect(tooltip()).toBe('Searches flow names');

        press('Escape', 27);
        await settle();

        expect(tooltip()).toBeUndefined();
    });
});
