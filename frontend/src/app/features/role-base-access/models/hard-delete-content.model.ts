import { ConfirmationDialogData } from '@shared/components';

export type HardDeleteContent = Pick<ConfirmationDialogData, 'message' | 'caution' | 'cautionTitle' | 'breakdown'>;
