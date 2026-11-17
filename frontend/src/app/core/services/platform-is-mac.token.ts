import { InjectionToken } from '@angular/core';

/** Whether the app runs on an Apple device, where shortcuts use ⌘ instead of Ctrl. */
export const PLATFORM_IS_MAC = new InjectionToken<boolean>('PLATFORM_IS_MAC', {
    providedIn: 'root',
    factory: () => /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent),
});
