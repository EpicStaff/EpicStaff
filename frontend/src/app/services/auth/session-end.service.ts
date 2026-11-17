import { Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';

/**
 * Tells work that outlives a page, such as a background job's wait, that the session in this tab has ended.
 * Unlike `AppStorageService.clearAll`, which also runs on an organization switch, this fires only on sign-out.
 */
@Injectable({ providedIn: 'root' })
export class SessionEndService {
    private readonly endedSubject = new Subject<void>();

    /** Emits on every sign-out, a requested one and one forced by a failed token refresh. */
    readonly ended$: Observable<void> = this.endedSubject.asObservable();

    notifyEnded(): void {
        this.endedSubject.next();
    }
}
