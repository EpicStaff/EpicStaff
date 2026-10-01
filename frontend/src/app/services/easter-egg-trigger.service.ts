import { Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';

export const EASTER_EGG_REQUIRED_CLICKS = 7;
export const EASTER_EGG_MAX_CLICK_GAP_MS = 600;

/** Counts rapid clicks on the app logo and emits `activated$` once the required streak is reached. */
@Injectable({ providedIn: 'root' })
export class EasterEggTriggerService {
    private readonly activationSubject = new Subject<void>();
    private clickCount = 0;
    private lastClickTimestampMs: number | null = null;

    readonly activated$: Observable<void> = this.activationSubject.asObservable();

    /** Registers one logo click; a gap longer than the allowed maximum restarts the streak. */
    registerLogoClick(timestampMs: number = performance.now()): void {
        const isInStreak =
            this.lastClickTimestampMs !== null && timestampMs - this.lastClickTimestampMs < EASTER_EGG_MAX_CLICK_GAP_MS;
        this.clickCount = isInStreak ? this.clickCount + 1 : 1;
        this.lastClickTimestampMs = timestampMs;

        if (this.clickCount >= EASTER_EGG_REQUIRED_CLICKS) {
            this.clickCount = 0;
            this.lastClickTimestampMs = null;
            this.activationSubject.next();
        }
    }
}
