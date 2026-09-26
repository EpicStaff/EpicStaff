import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { HttpErrorResponse } from '@angular/common/http';
import { Component, forwardRef, input } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { JsonEditorFormFieldComponent } from '@shared/components';
import { of, throwError } from 'rxjs';

import { PersistenceTableEntry } from '../../models/persistence-table.model';
import { PersistenceTablesApiService } from '../../services/persistence-tables-api.service';
import { PersistenceEntryDialogComponent, PersistenceEntryDialogData } from './persistence-entry-dialog.component';

// jsdom has no ResizeObserver; the overflow directives in the template only need it to exist.
class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

// Stands in for the Monaco-backed JSON field, which does not render under the test runner.
@Component({
    selector: 'app-json-editor-form-field',
    template: '',
    providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => JsonFieldStubComponent), multi: true }],
})
class JsonFieldStubComponent implements ControlValueAccessor {
    readonly label = input('');
    readonly required = input(false);
    readonly editorHeight = input(200);

    writeValue(): void {}
    registerOnChange(): void {}
    registerOnTouched(): void {}
}

const ENTRY: PersistenceTableEntry = {
    id: 7,
    table: 1,
    key: 'profile_42',
    value: { plan: 'pro' },
    created_at: '2026-09-27T12:00:00Z',
    updated_at: '2026-09-27T12:00:00Z',
    updated_by_session: null,
    updated_by_graph: null,
    updated_by_graph_name: null,
};

// The envelope the global exception handler returns for a key taken in this table.
function keyTakenError(): HttpErrorResponse {
    return new HttpErrorResponse({
        status: 400,
        error: {
            status_code: 400,
            code: 'invalid',
            message: 'key: An entry with this key already exists in this table.',
        },
    });
}

function openDialog(data: PersistenceEntryDialogData) {
    const api = { createEntry: vi.fn(() => of(ENTRY)), updateEntry: vi.fn(() => of(ENTRY)) };
    const close = vi.fn();
    TestBed.configureTestingModule({
        providers: [
            { provide: DIALOG_DATA, useValue: data },
            { provide: DialogRef, useValue: { close } },
            { provide: PersistenceTablesApiService, useValue: api },
        ],
    });
    TestBed.overrideComponent(PersistenceEntryDialogComponent, {
        remove: { imports: [JsonEditorFormFieldComponent] },
        add: { imports: [JsonFieldStubComponent] },
    });
    const fixture = TestBed.createComponent(PersistenceEntryDialogComponent);
    fixture.detectChanges();
    return { fixture, dialog: fixture.componentInstance, api, close };
}

describe('PersistenceEntryDialogComponent', () => {
    beforeEach(() => vi.stubGlobal('ResizeObserver', ResizeObserverStub));
    afterEach(() => vi.unstubAllGlobals());

    it('lets an existing entry edit its key and sends the new key with the value', () => {
        const { dialog, api, close } = openDialog({ tableId: 1, entry: ENTRY });
        expect(dialog.form.controls.key.enabled).toBe(true);
        expect(dialog.form.controls.key.value).toBe('profile_42');

        dialog.form.controls.key.setValue('profile_43');
        dialog.submit();

        expect(api.updateEntry).toHaveBeenCalledWith(7, { key: 'profile_43', value: { plan: 'pro' } });
        expect(close).toHaveBeenCalledWith(ENTRY);
    });

    it('still creates a new entry in the given table', () => {
        const { dialog, api } = openDialog({ tableId: 3 });
        dialog.form.setValue({ key: 'fresh', value: '42' });
        dialog.submit();

        expect(api.createEntry).toHaveBeenCalledWith({ table: 3, key: 'fresh', value: 42 });
    });

    it('shows a 400 key error inline under the key field, not in the banner', () => {
        const { fixture, dialog, api, close } = openDialog({ tableId: 1, entry: ENTRY });
        api.updateEntry.mockReturnValue(throwError(() => keyTakenError()));

        dialog.form.controls.key.setValue('taken');
        dialog.submit();
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        const inlineError = element.querySelector('.validation-errors')?.textContent?.trim();
        expect(inlineError).toBe('An entry with this key already exists in this table.');
        expect(element.querySelector('.persistence-dialog__error-message')).toBeNull();
        expect(dialog.form.controls.key.hasError('server')).toBe(true);
        expect(close).not.toHaveBeenCalled();

        // Editing the key clears the server error, so the user can retry.
        dialog.form.controls.key.setValue('free');
        expect(dialog.form.controls.key.hasError('server')).toBe(false);
    });

    it('shows the same inline key error when creating onto an existing key', () => {
        const { fixture, dialog, api } = openDialog({ tableId: 1 });
        api.createEntry.mockReturnValue(throwError(() => keyTakenError()));

        dialog.form.setValue({ key: 'taken', value: '1' });
        dialog.submit();
        fixture.detectChanges();

        expect(dialog.form.controls.key.getError('server')).toEqual([
            'An entry with this key already exists in this table.',
        ]);
        expect(dialog.errorMessage()).toBeNull();
    });

    it('keeps several flattened field errors together in the banner', () => {
        const { dialog, api } = openDialog({ tableId: 1, entry: ENTRY });
        const message = 'key: An entry with this key already exists in this table.; value: Value is too large.';
        api.updateEntry.mockReturnValue(
            throwError(() => new HttpErrorResponse({ status: 400, error: { code: 'invalid', message } }))
        );

        dialog.submit();

        expect(dialog.form.controls.key.hasError('server')).toBe(false);
        expect(dialog.errorMessage()).toBe(message);
    });

    it('falls back to the banner for errors that are not about the key', () => {
        const { fixture, dialog, api } = openDialog({ tableId: 1, entry: ENTRY });
        api.updateEntry.mockReturnValue(
            throwError(() => new HttpErrorResponse({ status: 500, error: { message: 'Server exploded' } }))
        );

        dialog.submit();
        fixture.detectChanges();

        const element = fixture.nativeElement as HTMLElement;
        expect(element.querySelector('.persistence-dialog__error-message')?.textContent).toContain('Server exploded');
    });
});
