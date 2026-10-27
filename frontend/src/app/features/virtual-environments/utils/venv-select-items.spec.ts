import { Venv } from '../models/venv.model';
import { FAVORITES_GROUP, OTHER_GROUP, toVenvSelectItems } from './venv-select-items';

function venv(id: number, name: string, isFavorite: boolean): Venv {
    return {
        id,
        name,
        libs: [],
        status: 'completed',
        error: null,
        owner: null,
        created_at: null,
        is_favorite: isFavorite,
    };
}

describe('toVenvSelectItems', () => {
    it('puts the favorites first and keeps the given order inside each group', () => {
        const items = toVenvSelectItems([
            venv(1, 'b', false),
            venv(2, 'z', true),
            venv(3, 'a', false),
            venv(4, 'y', true),
        ]);

        // Neither group is re-sorted: 'z' before 'y' and 'b' before 'a' are the caller's order,
        // which is the order the backend sorted the venvs into.
        expect(items.map((item) => item.name)).toEqual(['z', 'y', 'b', 'a']);
        expect(items.map((item) => item.group)).toEqual([FAVORITES_GROUP, FAVORITES_GROUP, OTHER_GROUP, OTHER_GROUP]);
        expect(items.map((item) => item.value)).toEqual([2, 4, 1, 3]);
    });
});
