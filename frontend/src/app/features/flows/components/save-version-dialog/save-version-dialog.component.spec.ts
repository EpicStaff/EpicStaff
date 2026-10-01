import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { TestBed } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { SaveVersionDialogComponent } from './save-version-dialog.component';

describe('SaveVersionDialogComponent', () => {
    let component: SaveVersionDialogComponent;
    let close: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        close = vi.fn();
        TestBed.configureTestingModule({
            imports: [SaveVersionDialogComponent],
            providers: [
                { provide: DialogRef, useValue: { close, keydownEvents: new Subject<KeyboardEvent>() } },
                { provide: DIALOG_DATA, useValue: null },
            ],
        });
        // The form logic is under test; rendering needs ResizeObserver, which jsdom lacks.
        component = TestBed.createComponent(SaveVersionDialogComponent).componentInstance;
    });

    it('does not create a version whose name is only spaces', () => {
        component.form.controls.name.setValue('   ');

        component.onSubmit();

        expect(component.form.controls.name.hasError('whitespace')).toBe(true);
        expect(close).not.toHaveBeenCalled();
    });

    it('creates a version with the trimmed name', () => {
        component.form.controls.name.setValue('  Release 1  ');

        component.onSubmit();

        expect(close).toHaveBeenCalledWith({ name: 'Release 1', description: '' });
    });
});
