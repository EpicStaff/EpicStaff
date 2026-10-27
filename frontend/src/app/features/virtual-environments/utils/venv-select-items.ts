import { SelectItem } from '@shared/components';

import { Venv, VENV_STATUS_VIEWS } from '../models/venv.model';

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
        // The status the venv list page shows on its badge, in the same words.
        tip: VENV_STATUS_VIEWS[venv.status]?.label,
        // A build that failed produces no environment to run in, so there is nothing to pick;
        // a build still running is a choice the user may make, after a warning.
        disabled: venv.status === 'failed',
    });
    return [...venvs.filter((venv) => venv.is_favorite), ...venvs.filter((venv) => !venv.is_favorite)].map(toItem);
}
