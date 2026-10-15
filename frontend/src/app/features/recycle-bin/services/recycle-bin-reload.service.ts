import { Injectable, signal } from '@angular/core';

/**
 * Lets the page ask the open tab to reload, after "Empty recycle bin" changed every tab.
 * Provided by RecycleBinPageComponent, so the tab in its router outlet gets the same instance.
 */
@Injectable()
export class RecycleBinReloadService {
    private readonly requestsSignal = signal(0);

    /** Goes up by one on every request; the tab reloads when it changes. */
    readonly requests = this.requestsSignal.asReadonly();

    request(): void {
        this.requestsSignal.update((count) => count + 1);
    }
}
