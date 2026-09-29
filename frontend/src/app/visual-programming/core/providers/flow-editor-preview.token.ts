import { InjectionToken } from '@angular/core';

export const FLOW_EDITOR_PREVIEW = new InjectionToken<boolean>('FLOW_EDITOR_PREVIEW', {
    providedIn: 'root',
    factory: () => false,
});
