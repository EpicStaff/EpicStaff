import { ConfirmationDialogData } from '@shared/components';

/** Confirmation shown when an upload dialog is closed while files are still uploading. */
export const CLOSE_DURING_UPLOAD_CONFIRMATION: ConfirmationDialogData = {
    title: 'Cancel uploads?',
    message: 'Uploads in progress will be cancelled; files already uploaded are kept. Close anyway?',
    confirmText: 'Close',
    cancelText: 'Keep uploading',
    type: 'warning',
};
