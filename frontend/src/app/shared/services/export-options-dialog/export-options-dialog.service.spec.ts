import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ExportEntityLabels, ExportOptions } from '@shared/models';

import { ExportOptionsDialogService } from './export-options-dialog.service';

const FLOWS: ExportEntityLabels = { singular: 'flow', plural: 'flows' };
const AGENTS: ExportEntityLabels = { singular: 'agent', plural: 'agents' };

describe('ExportOptionsDialogService', () => {
    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [provideHttpClient(), provideHttpClientTesting()],
        });
    });

    afterEach(() => TestBed.inject(Dialog).closeAll());

    /** Opens the dialog and returns what it emitted so far, whether it completed, and the dialog element. */
    async function ask(
        count: number,
        labels: ExportEntityLabels
    ): Promise<{ answers: ExportOptions[]; completed: () => boolean; dialog: HTMLElement }> {
        const answers: ExportOptions[] = [];
        let completed = false;
        TestBed.inject(ExportOptionsDialogService)
            .ask(count, labels)
            .subscribe({ next: (answer) => answers.push(answer), complete: () => (completed = true) });
        await settle();
        const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!;
        return { answers, completed: () => completed, dialog };
    }

    async function settle(): Promise<void> {
        await TestBed.inject(ApplicationRef).whenStable();
    }

    async function click(element: HTMLElement | null): Promise<void> {
        element!.click();
        await settle();
    }

    function button(dialog: HTMLElement, label: string): HTMLButtonElement | null {
        return (
            [...dialog.querySelectorAll<HTMLButtonElement>('button')].find(
                (candidate) => candidate.textContent?.trim() === label
            ) ?? null
        );
    }

    it.each([
        {
            count: 2,
            labels: FLOWS,
            title: 'Export 2 flows',
            message:
                'Knowledge data adds the knowledge collections the flows use, with their files, so they work after import. The archive can get large.',
        },
        {
            count: 1,
            labels: AGENTS,
            title: 'Export 1 agent',
            message:
                'Knowledge data adds the knowledge collections the agents use, with their files, so they work after import. The archive can get large.',
        },
    ])('names what is exported: "$title"', async ({ count, labels, title, message }) => {
        const { dialog } = await ask(count, labels);

        expect(dialog.querySelector('.dialog-title')?.textContent?.trim()).toBe(title);
        expect(dialog.querySelector('.dialog-message')?.textContent?.trim()).toBe(message);
    });

    it('includes knowledge when the user exports with the box left checked', async () => {
        const { answers, completed, dialog } = await ask(2, FLOWS);

        expect(dialog.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked).toBe(true);
        await click(button(dialog, 'Export'));

        expect(answers).toEqual([{ includeKnowledge: true }]);
        expect(completed()).toBe(true);
    });

    it('leaves knowledge out when the user clears the box before exporting', async () => {
        const { answers, dialog } = await ask(3, AGENTS);

        await click(dialog.querySelector<HTMLInputElement>('input[type="checkbox"]'));
        await click(button(dialog, 'Export'));

        expect(answers).toEqual([{ includeKnowledge: false }]);
    });

    it.each([
        ['cancels', (dialog: HTMLElement) => button(dialog, 'Cancel')],
        ['closes the dialog', (dialog: HTMLElement) => dialog.querySelector<HTMLElement>('button[aria-label="Close"]')],
    ])('emits nothing and completes when the user %s', async (_case, control) => {
        const { answers, completed, dialog } = await ask(2, FLOWS);

        await click(control(dialog));

        expect(answers).toEqual([]);
        expect(completed()).toBe(true);
    });
});
