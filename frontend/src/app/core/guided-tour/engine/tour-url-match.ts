import { containsTree, IsActiveMatchOptions, UrlTree } from '@angular/router';

/** Only the path decides whether the user is on a URL. */
const SAME_PATH: IsActiveMatchOptions = {
    paths: 'exact',
    queryParams: 'ignored',
    matrixParams: 'ignored',
    fragment: 'ignored',
};
/** The URL itself or anything under it. */
const SAME_PATH_OR_BELOW: IsActiveMatchOptions = { ...SAME_PATH, paths: 'subset' };

/** Whether `url` has the path of `place`; query parameters, matrix parameters and the fragment may differ. */
export function isOnPath(url: UrlTree, place: UrlTree): boolean {
    return containsTree(url, place, SAME_PATH);
}

/** Whether `url` is `section` or anything under it, by path (e.g. `/settings/quickstart` is under `/settings`). */
export function isAtOrUnderPath(url: UrlTree, section: UrlTree): boolean {
    return containsTree(url, section, SAME_PATH_OR_BELOW);
}
