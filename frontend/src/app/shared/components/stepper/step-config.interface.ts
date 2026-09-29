import { Observable } from 'rxjs';

export interface StepConfig {
    id: number;
    label: string;
    onProceed: () => Observable<boolean>;
    canProceed: () => boolean;
    proceedLabel: string;
    hideProceed: () => boolean;
}
