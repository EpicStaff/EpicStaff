import { isFocusLost } from './focus.util';

describe('isFocusLost', () => {
    let button: HTMLButtonElement;

    beforeEach(() => {
        button = document.createElement('button');
        document.body.appendChild(button);
    });

    afterEach(() => button.remove());

    it('is false while an element on the page has the focus', () => {
        button.focus();

        expect(isFocusLost(document)).toBe(false);
    });

    it('is true once the focused element is removed and the focus falls to the body', () => {
        button.focus();
        button.remove();

        expect(isFocusLost(document)).toBe(true);
    });

    it('is true when nothing was focused', () => {
        button.blur();

        expect(isFocusLost(document)).toBe(true);
    });
});
