import { SelectItem } from '@shared/components';

import { Venv } from '../models/venv.model';

/** The headings the venv pickers split their options under. One definition, so the two
 *  pickers cannot drift apart in wording. */
export const FAVORITES_GROUP = 'Favorites';
export const OTHER_GROUP = 'All';

/**
 * The venvs as picker options: the caller's favorites first, the rest after, each under its
 * heading.
 *
 * A stable split -- inside each group the venvs keep the order they arrived in, which is the
 * order the backend sorted them into.
 */
export function toVenvSelectItems(venvs: Venv[]): SelectItem[] {
    const toItem = (venv: Venv): SelectItem => ({
        name: venv.name,
        value: venv.id,
        group: venv.is_favorite ? FAVORITES_GROUP : OTHER_GROUP,
    });
    return [...venvs.filter((venv) => venv.is_favorite), ...venvs.filter((venv) => !venv.is_favorite)].map(toItem);
}
