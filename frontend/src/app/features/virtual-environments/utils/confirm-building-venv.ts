import { ConfirmationDialogService } from '@shared/components';
import { escapeHtml } from '@shared/utils';
import { map, Observable } from 'rxjs';

/**
 * Ask before pointing code at a venv whose build has not finished.
 *
 * One wording for every picker: the warning is about what happens at run time, which does
 * not depend on where the venv was chosen.
 *
 * Returns:
 *     Whether the user confirmed. Dismissing the dialog counts as declining.
 */
export function confirmBuildingVenv(
    confirmationDialog: ConfirmationDialogService,
    venvName: string
): Observable<boolean> {
    return confirmationDialog
        .confirm({
            title: 'This environment is still building',
            message:
                `<strong>${escapeHtml(venvName)}</strong> has not finished building yet. ` +
                'If a flow reaches this step before the build is done, it stops here and waits ' +
                'for the environment to be ready.',
            confirmText: 'Use it anyway',
            cancelText: 'Cancel',
            type: 'warning',
        })
        .pipe(map((result) => result === true));
}
