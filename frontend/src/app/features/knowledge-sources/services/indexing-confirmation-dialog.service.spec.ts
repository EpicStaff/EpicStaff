import { Dialog } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { ConfirmationResult } from '@shared/components';
import { firstValueFrom, of } from 'rxjs';

import { IndexingConfirmationDialogService } from './indexing-confirmation-dialog.service';

describe('IndexingConfirmationDialogService.confirm', () => {
    it.each<[string, ConfirmationResult | undefined, ConfirmationResult]>([
        ['confirmed', true, true],
        ['cancelled', false, false],
        ['closed with the close button', 'close', 'close'],
        ['dismissed with Escape or a click outside', undefined, 'close'],
    ])('answers for a dialog %s', async (_case, dialogResult, expected) => {
        TestBed.configureTestingModule({
            providers: [{ provide: Dialog, useValue: { open: () => ({ closed: of(dialogResult) }) } }],
        });
        const service = TestBed.inject(IndexingConfirmationDialogService);

        const answer = await firstValueFrom(
            service.confirm({ documents: [], ragType: 'naive', embedderName: null, llmName: null })
        );

        expect(answer).toBe(expected);
    });
});
