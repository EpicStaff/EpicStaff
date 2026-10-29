import { Dialog } from '@angular/cdk/dialog';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { ApplicationRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ConfirmationDialogService } from './confimation-dialog.service';
import { ConfirmationDialogData } from './confirmation-dialog.component';

describe('ConfirmationDialogService.confirmMoveToRecycleBin', () => {
    let service: ConfirmationDialogService;
    let open: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        open = vi.fn(() => ({ closed: of({ action: 'confirm' }) }));
        TestBed.configureTestingModule({
            providers: [{ provide: Dialog, useValue: { open } }],
        });
        service = TestBed.inject(ConfirmationDialogService);
    });

    function openedData(): ConfirmationDialogData {
        return open.mock.calls[0][1].data as ConfirmationDialogData;
    }

    it('escapes the name', () => {
        service.confirmMoveToRecycleBin('<b>x</b>', 7).subscribe();
        expect(openedData().message).toContain('<strong>&lt;b&gt;x&lt;/b&gt;</strong>');
    });

    it('truncates the name before escaping it', () => {
        const name = `${'a'.repeat(49)}&${'b'.repeat(10)}`;
        service.confirmMoveToRecycleBin(name, 7, 50).subscribe();
        expect(openedData().message).toContain('&amp;...');
    });

    it('says the item moves to the recycle bin instead of being gone for good', () => {
        service.confirmMoveToRecycleBin('Report', 7).subscribe();
        expect(openedData().message).toContain('restore it for 7 days');
        expect(openedData().message).not.toContain('cannot be undone');
    });

    it('emits true when the dialog is confirmed', () => {
        let result: unknown;
        service.confirmMoveToRecycleBin('Report', 7).subscribe((value) => (result = value));
        expect(result).toBe(true);
    });
});

describe('ConfirmationDialogService dialog accessibility', () => {
    beforeEach(() => {
        TestBed.configureTestingModule({
            providers: [provideHttpClient(), provideHttpClientTesting()],
        });
    });

    afterEach(() => {
        TestBed.inject(Dialog).closeAll();
    });

    function openDialogs(): HTMLElement[] {
        return Array.from(document.querySelectorAll<HTMLElement>('[role="dialog"]'));
    }

    async function open(title: string): Promise<HTMLElement> {
        TestBed.inject(ConfirmationDialogService).confirm({ title, message: 'Sure?', type: 'danger' }).subscribe();
        await TestBed.inject(ApplicationRef).whenStable();
        return openDialogs().at(-1)!;
    }

    it('is modal and labelled by its title', async () => {
        const dialog = await open('Delete Report?');

        expect(dialog.getAttribute('aria-modal')).toBe('true');
        const titleId = dialog.getAttribute('aria-labelledby');
        expect(titleId).toBeTruthy();
        expect(document.getElementById(titleId!)?.textContent?.trim()).toBe('Delete Report?');
    });

    it('labels a dialog stacked on another by its own title', async () => {
        await open('First?');
        const second = await open('Second?');

        expect(openDialogs()).toHaveLength(2);
        expect(document.getElementById(second.getAttribute('aria-labelledby')!)?.textContent?.trim()).toBe('Second?');
    });
});
