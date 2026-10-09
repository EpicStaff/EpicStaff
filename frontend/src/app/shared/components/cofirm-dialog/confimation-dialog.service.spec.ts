import { Dialog } from '@angular/cdk/dialog';
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
