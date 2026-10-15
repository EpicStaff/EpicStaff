import { DestroyRef, WritableSignal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AbstractControl } from '@angular/forms';
import { startWith } from 'rxjs';

/**
 * Keeps `target` holding the secret ids picked in `controlNames` of `form`, so a secret picker can
 * keep showing a picked secret that's in the recycle bin (see SecretsStorageService.selectItems).
 */
export function trackPickedSecrets(
    form: AbstractControl,
    controlNames: string[],
    target: WritableSignal<number[]>,
    destroyRef: DestroyRef
): void {
    form.valueChanges.pipe(startWith(null), takeUntilDestroyed(destroyRef)).subscribe(() => {
        const ids = controlNames
            .map((name) => form.get(name)?.value)
            .filter((value): value is number => typeof value === 'number');
        // Most edits touch other fields: keep the same array so the picker's items aren't rebuilt.
        const current = target();
        if (ids.length !== current.length || ids.some((id, index) => id !== current[index])) target.set(ids);
    });
}
