import { FormControl } from '@angular/forms';

import { newAccountEmailValidator } from './new-account-email.validator';

function validate(email: string) {
    return newAccountEmailValidator()(new FormControl(email));
}

describe('newAccountEmailValidator', () => {
    it.each([
        'john.smith@gmail.com',
        'john_smith@gmail.com',
        'john-smith@gmail.com',
        'JOHN.SMITH@gmail.com',
        'john+newsletter@gmail.com',
        '12345@gmail.com',
        'a@b.co',
        'anna@mail.company.com.ua',
        `${'x'.repeat(64)}@gmail.com`,
    ])('accepts %s', (email) => {
        expect(validate(email)).toBeNull();
    });

    it('leaves an empty value to the required validator', () => {
        expect(validate('')).toBeNull();
    });

    it.each(['---@gmail.com', '___@gmail.com', '+john@gmail.com', '__proto__@x.com'])(
        'rejects %s because of its first or last character',
        (email) => {
            expect(validate(email)).toEqual({ emailEdges: true });
        }
    );

    it.each([
        'john%smith@gmail.com',
        'john!#$&*smith@gmail.com',
        "o'brien@gmail.com",
        'aaaa!@x.com',
        '"john"@gmail.com',
    ])('rejects %s because of a symbol other than . _ - +', (email) => {
        expect(validate(email)).toEqual({ emailCharacters: true });
    });

    it.each(['john smith@gmail.com', ' john@gmail.com'])('rejects %s because of whitespace', (email) => {
        expect(validate(email)).toEqual({ emailWhitespace: true });
    });

    it('rejects a local part longer than 64 characters', () => {
        expect(validate(`${'x'.repeat(65)}@gmail.com`)).toEqual({ emailLength: true });
    });

    it('accepts 254 characters in total and rejects 255', () => {
        // Every domain label stays within 63 characters.
        const emailOf = (lastLabelLength: number) =>
            `${'x'.repeat(64)}@${'d'.repeat(63)}.${'d'.repeat(63)}.${'d'.repeat(lastLabelLength)}.com`;
        expect(emailOf(57)).toHaveLength(254);
        expect(validate(emailOf(57))).toBeNull();
        expect(validate(emailOf(58))).toEqual({ emailLength: true });
    });

    it('reports the edge rule before the domain, like the backend', () => {
        expect(validate('---@localhost')).toEqual({ emailEdges: true });
    });

    it.each(['john', '@gmail.com', 'john@', 'john@localhost', 'john@gmail.c0m', 'john..smith@gmail.com'])(
        'rejects malformed %s',
        (email) => {
            expect(validate(email)).toEqual({ email: true });
        }
    );
});
