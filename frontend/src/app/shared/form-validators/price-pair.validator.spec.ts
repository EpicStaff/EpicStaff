import { FormControl, FormGroup } from '@angular/forms';

import { pricePairValidator } from './price-pair.validator';

describe('pricePairValidator', () => {
    function buildGroup(input: number | null | string, output: number | null | string): FormGroup {
        return new FormGroup(
            { input: new FormControl(input), output: new FormControl(output) },
            { validators: pricePairValidator('input', 'output') }
        );
    }

    it.each([
        { input: null, output: null },
        { input: '', output: null },
        { input: 2.5, output: 10 },
        { input: 0, output: 0 },
    ])('accepts input=$input output=$output', ({ input, output }) => {
        expect(buildGroup(input, output).hasError('pricePair')).toBe(false);
    });

    it.each([
        { input: 2.5, output: null },
        { input: null, output: 10 },
        { input: 0, output: '' },
    ])('rejects input=$input output=$output', ({ input, output }) => {
        expect(buildGroup(input, output).hasError('pricePair')).toBe(true);
    });
});
