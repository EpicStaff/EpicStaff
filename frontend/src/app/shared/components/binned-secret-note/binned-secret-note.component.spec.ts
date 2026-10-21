import { TestBed } from '@angular/core/testing';

import { SecretsStorageService } from '../../services/secrets/secrets-storage.service';
import { BinnedSecretNoteComponent } from './binned-secret-note.component';

function render(selected: number | number[] | null, readonly = false): string {
    TestBed.configureTestingModule({
        providers: [{ provide: SecretsStorageService, useValue: { isBinned: (id: number) => id === 7 } }],
    });
    const fixture = TestBed.createComponent(BinnedSecretNoteComponent);
    fixture.componentRef.setInput('selected', selected);
    fixture.componentRef.setInput('readonly', readonly);
    fixture.detectChanges();
    return ((fixture.nativeElement as HTMLElement).textContent ?? '').replace(/\s+/g, ' ').trim();
}

describe('BinnedSecretNoteComponent', () => {
    it('says a picked secret is in the recycle bin and how to fix it', () => {
        expect(render(7)).toBe(
            "This secret is in the recycle bin, so it can't be used. Restore it from the Recycle Bin, or pick another one."
        );
    });

    it('also finds a binned secret in a list', () => {
        expect(render([1, 7])).toContain('in the recycle bin');
    });

    it('says nothing for live secrets', () => {
        expect(render([1, 2])).toBe('');
    });

    it('gives a read-only viewer no fix they cannot make', () => {
        expect(render(7, true)).toBe("This secret is in the recycle bin, so it can't be used.");
    });
});
