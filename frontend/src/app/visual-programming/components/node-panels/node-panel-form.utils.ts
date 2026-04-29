import { AbstractControl, FormArray, FormBuilder, FormGroup, Validators } from '@angular/forms';

interface InputMapPair {
    key: string;
    value: string;
}

export function initializeInputMap(
    form: FormGroup,
    inputMap: Record<string, unknown> | null | undefined,
    fb: FormBuilder
): void {
    const inputMapArray = form.get('input_map') as FormArray;

    if (inputMap && Object.keys(inputMap).length > 0) {
        Object.entries(inputMap).forEach(([key, value]) => {
            inputMapArray.push(
                fb.group({
                    key: [key, Validators.required],
                    value: [String(value ?? ''), Validators.required],
                })
            );
        });
        return;
    }

    inputMapArray.push(
        fb.group({
            key: [''],
            value: ['variables.'],
        })
    );
}

export function getValidInputPairs(inputMapPairs: FormArray): AbstractControl[] {
    return inputMapPairs.controls.filter((control) => {
        const value = control.value as InputMapPair;
        return value.key?.trim() !== '' || value.value?.trim() !== '';
    });
}

export function createInputMapFromPairs(pairs: AbstractControl[]): Record<string, string> {
    return pairs.reduce((acc: Record<string, string>, curr: AbstractControl) => {
        const pair = curr.value as InputMapPair;
        if (pair.key?.trim()) {
            acc[pair.key.trim()] = pair.value;
        }
        return acc;
    }, {});
}

export function parseCommaSeparatedList(value: string | null | undefined): string[] {
    return value
        ? value
              .split(',')
              .map((item) => item.trim())
              .filter((item) => item.length > 0)
        : [];
}
