import { OverlayContainer } from '@angular/cdk/overlay';
import { TestBed } from '@angular/core/testing';

import { UnsavedChangesDialogData } from './unsaved-changes-dialog.component';
import { UnsavedChangesDialogService, UnsavedChangesResult } from './unsaved-changes-dialog.service';

const DATA: UnsavedChangesDialogData = {
    title: 'Unsaved Changes',
    message: 'You have unsaved changes.',
    saveText: 'Save & Leave',
    dontSaveText: 'Discard & Leave',
    cancelText: 'Keep Editing',
};

/** Opens the dialog the way callers do and records how it closes. */
function open(data: UnsavedChangesDialogData): { overlay: HTMLElement; results: UnsavedChangesResult[] } {
    const results: UnsavedChangesResult[] = [];
    TestBed.inject(UnsavedChangesDialogService)
        .confirm(data)
        .subscribe((result) => results.push(result));
    TestBed.tick();
    return { overlay: TestBed.inject(OverlayContainer).getContainerElement(), results };
}

function buttonLabels(overlay: HTMLElement): string[] {
    return Array.from(overlay.querySelectorAll('.dialog-actions button')).map(
        (button) => button.textContent?.trim() ?? ''
    );
}

function pressEnter(overlay: HTMLElement): void {
    const container = overlay.querySelector<HTMLElement>('.dialog-container')!;
    container.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    TestBed.tick();
}

describe('UnsavedChangesDialogComponent Save button', () => {
    it('shows Save by default, and Enter saves', () => {
        const { overlay, results } = open(DATA);

        expect(buttonLabels(overlay)).toContain('Save & Leave');

        pressEnter(overlay);

        expect(results).toEqual(['save']);
    });

    it('hides Save when asked to, and Enter then leaves the dialog open', () => {
        const { overlay, results } = open({ ...DATA, showSave: false });

        expect(buttonLabels(overlay)).toEqual(['Discard & Leave', 'Keep Editing']);

        pressEnter(overlay);

        expect(results).toEqual([]);
        expect(overlay.querySelector('.dialog-container')).not.toBeNull();
    });
});
