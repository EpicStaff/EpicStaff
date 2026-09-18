import { ConfirmationDialogData } from '../../../shared/components/cofirm-dialog/confirmation-dialog.component';

export type SurfaceBundleClearKind = 'tools' | 'collections' | 'files';

export function buildClearSurfaceBundleDialog(
    kind: SurfaceBundleClearKind,
    surfaceName?: string | null
): ConfirmationDialogData {
    const surface = surfaceName?.trim() ? `<strong>${surfaceName.trim()}</strong>` : 'this surface';

    if (kind === 'tools') {
        return {
            title: 'Remove all tools?',
            message: `You are about to remove all tools from ${surface}.`,
            confirmText: 'Remove All',
            cancelText: 'Cancel',
            type: 'warning',
            cautionTitle: 'Attention',
            caution:
                'If you remove them now, any agent using this surface will <strong>lose access</strong> to these tools.',
            isShownBorder: true,
        };
    }

    if (kind === 'collections') {
        return {
            title: 'Remove all collections?',
            message: `You are about to remove all knowledge collections from ${surface}.`,
            confirmText: 'Remove All',
            cancelText: 'Cancel',
            type: 'warning',
            cautionTitle: 'Attention',
            caution:
                'If you remove them now, any agent using this surface will <strong>lose access</strong> to these collections.',
            isShownBorder: true,
        };
    }

    return {
        title: 'Remove all files & folders?',
        message: `You are about to remove all files and folders from ${surface}.`,
        confirmText: 'Remove All',
        cancelText: 'Cancel',
        type: 'warning',
        cautionTitle: 'Attention',
        caution:
            'If you remove them now, any agent using this surface will <strong>lose access</strong> to these files and folders.',
        isShownBorder: true,
    };
}
