import { nextListIndex } from './list-navigation.util';

describe('nextListIndex', () => {
    it.each([
        ['ArrowDown', 0, 3, 1],
        ['ArrowDown', 2, 3, 0],
        ['ArrowUp', 1, 3, 0],
        ['ArrowUp', 0, 3, 2],
        ['Home', 2, 3, 0],
        ['End', 0, 3, 2],
    ])('moves %s from %i in a list of %i to %i', (key, current, count, expected) => {
        expect(nextListIndex(key, current, count)).toBe(expected);
    });

    it.each([
        ['ArrowDown', 0],
        ['ArrowUp', 2],
    ])('starts %s at the item %i while nothing is highlighted', (key, expected) => {
        expect(nextListIndex(key, -1, 3)).toBe(expected);
    });

    it('ignores other keys and empty lists', () => {
        expect(nextListIndex('Enter', 0, 3)).toBeNull();
        expect(nextListIndex('ArrowDown', -1, 0)).toBeNull();
    });
});
