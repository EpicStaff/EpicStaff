import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';
import type { Mock } from 'vitest';

import { PluginRestore } from '../../models/plugin-admin.model';
import { PluginsAdminStorageService } from '../../services/plugins-admin-storage.service';
import { buildPluginBackup, buildPluginRestore } from '../../testing/plugin-fixtures';
import { PLUGIN_ERROR_MESSAGES } from '../../utils/plugin-error-message.util';
import { PluginRestoreDialogComponent, PluginRestoreDialogData } from './plugin-restore-dialog.component';

const DATA: PluginRestoreDialogData = {
    identifier: 'weather',
    pluginName: 'Weather',
    databaseName: 'plugin_weather',
    backup: buildPluginBackup({
        id: 62,
        file_name: '20261021T110100Z-u8-pre_upgrade.dump',
        version: '0.7.0',
        upgrade: { id: 8, to_version: '0.7.1' },
        created_at: '2026-10-21T11:01:00Z',
        restorable: true,
        not_restorable_reason: null,
    }),
    verificationPhrase: 'restore-weather',
};

describe('PluginRestoreDialogComponent', () => {
    let fixture: ComponentFixture<PluginRestoreDialogComponent>;
    let element: HTMLElement;
    let restoreBackup: Mock<(identifier: string, backupId: number, phrase: string) => Observable<PluginRestore>>;
    let keydownEvents: Subject<KeyboardEvent>;
    const dialogRef = { close: vi.fn(), keydownEvents: new Subject<KeyboardEvent>() };

    function restoreButton(): HTMLButtonElement {
        return Array.from(element.querySelectorAll<HTMLButtonElement>('.dialog__footer button')).find(
            (button) => button.textContent?.trim() === 'Restore'
        )!;
    }

    function type(text: string): void {
        const input = element.querySelector<HTMLInputElement>('#plugin-restore-verification')!;
        input.value = text;
        input.dispatchEvent(new Event('input'));
        fixture.detectChanges();
    }

    beforeEach(() => {
        vi.clearAllMocks();
        vi.stubGlobal(
            'ResizeObserver',
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            }
        );
        keydownEvents = new Subject<KeyboardEvent>();
        dialogRef.keydownEvents = keydownEvents;
        restoreBackup = vi.fn(() => of(buildPluginRestore({ state: 'pending', step: null })));
        TestBed.configureTestingModule({
            imports: [PluginRestoreDialogComponent],
            providers: [
                { provide: DIALOG_DATA, useValue: DATA },
                { provide: DialogRef, useValue: dialogRef },
                { provide: PluginsAdminStorageService, useValue: { restoreBackup } },
            ],
        });
        fixture = TestBed.createComponent(PluginRestoreDialogComponent);
        element = fixture.nativeElement as HTMLElement;
        fixture.detectChanges();
    });

    afterEach(() => vi.unstubAllGlobals());

    it('says what the restore replaces, that a backup comes first, and which phrase confirms it', () => {
        const body = element.querySelector('.dialog__body')?.textContent?.replace(/\s+/g, ' ') ?? '';

        expect(element.querySelector('h2')?.textContent?.trim()).toBe('Restore Before upgrade to 0.7.1');
        expect(body).toMatch(
            /Replace plugin_weather with this backup from Oct 21, 2026, .+\? Changes since then are lost\. A backup of the current database is taken first, so you can undo this\./
        );
        expect(body).toContain('Type restore-weather to confirm');
    });

    it('is enabled only by the exact phrase: nothing trimmed, case counts', () => {
        expect(restoreButton().disabled).toBe(true);

        for (const near of ['restore-weathe', 'Restore-weather', 'restore-weather ', ' restore-weather']) {
            type(near);
            expect(restoreButton().disabled, JSON.stringify(near)).toBe(true);
        }

        type('restore-weather');
        expect(restoreButton().disabled).toBe(false);
    });

    it('sends the phrase as typed and closes with the restore under way', () => {
        type('restore-weather');
        restoreButton().click();
        fixture.detectChanges();

        expect(restoreBackup).toHaveBeenCalledWith('weather', 62, 'restore-weather');
        expect(dialogRef.close).toHaveBeenCalledWith(expect.objectContaining({ id: 4, state: 'pending' }));
    });

    it('keeps the dialog open with the reason when the server refuses', () => {
        restoreBackup.mockReturnValue(
            throwError(
                () =>
                    new HttpErrorResponse({
                        status: 409,
                        error: { status_code: 409, code: 'restore_not_allowed', message: 'Refused.' },
                    })
            )
        );
        type('restore-weather');
        restoreButton().click();
        fixture.detectChanges();

        expect(dialogRef.close).not.toHaveBeenCalled();
        expect(element.querySelector('[role="alert"]')?.textContent?.trim()).toBe(
            PLUGIN_ERROR_MESSAGES.restore_not_allowed
        );
        expect(restoreButton().disabled).toBe(false);
    });

    it('closes on Escape, but not while the request is under way', () => {
        const pending = new Subject<PluginRestore>();
        restoreBackup.mockReturnValue(pending);
        type('restore-weather');
        restoreButton().click();
        fixture.detectChanges();

        keydownEvents.next(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(dialogRef.close).not.toHaveBeenCalled();

        pending.error(new HttpErrorResponse({ status: 502, error: null }));
        fixture.detectChanges();
        keydownEvents.next(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(dialogRef.close).toHaveBeenCalledWith();
    });
});
