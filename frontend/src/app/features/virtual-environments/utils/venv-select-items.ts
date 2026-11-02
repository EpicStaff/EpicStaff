import { SelectItem } from '@shared/components';

import { Venv, VENV_STATUS_VIEWS } from '../models/venv.model';

/** The headings the venv pickers split their options under. One definition, so the two
 *  pickers cannot drift apart in wording. */
export const FAVORITES_GROUP = 'Favorite';
export const OTHER_GROUP = 'Others';

/** How many library names a row shows before the rest become a count. Fixed rather than
 *  measured: what fits depends on the panel's width, which this has no way of knowing. */
const SHOWN_LIBRARIES = 3;

/**
 * The venvs as picker options: the caller's favorites first, the rest after, each under its
 * heading.
 *
 * A stable split -- inside each group the venvs keep the order they arrived in, which is the
 * order the backend sorted them into.
 */
/** The venv's libraries as one line, the overflow counted rather than listed. */
function librarySummary(venv: Venv): string | undefined {
    if (!venv.libs.length) return undefined;
    const shown = venv.libs.slice(0, SHOWN_LIBRARIES).map((lib) => lib.name);
    const hidden = venv.libs.length - shown.length;
    return hidden > 0 ? `${shown.join(', ')} +${hidden}` : shown.join(', ');
}

export function toVenvSelectItems(venvs: Venv[]): SelectItem[] {
    const toItem = (venv: Venv): SelectItem => ({
        name: venv.name,
        value: venv.id,
        group: venv.is_favorite ? FAVORITES_GROUP : OTHER_GROUP,
        meta: librarySummary(venv),
        // The status the venv list page shows on its badge, in the same words and color.
        tip: VENV_STATUS_VIEWS[venv.status]?.label,
        tipColor: VENV_STATUS_VIEWS[venv.status]?.color,
        // A build that failed produces no environment to run in, so there is nothing to pick;
        // a build still running is a choice the user may make, after a warning.
        disabled: venv.status === 'failed',
    });
    return [...venvs.filter((venv) => venv.is_favorite), ...venvs.filter((venv) => !venv.is_favorite)].map(toItem);
}
