import { defer, finalize, Observable, Subscription } from 'rxjs';

/**
 * Runs graph saves one at a time, in the order they were subscribed.
 *
 * Every save the page sends carries the graph's `save_version` and gets a new one
 * back. Two in flight at once means the second was built with a version the first
 * is about to retire, and the server answers it with a 409. So each task is
 * started — and builds its payload — only once the one before it has settled.
 *
 * A task is lazy: nothing is built or sent until the returned observable is
 * subscribed and its turn comes. Unsubscribing while it waits takes it out of the
 * line; unsubscribing once it runs cancels it and lets the next one start.
 */
export class SerialSaveQueue {
    private isBusy = false;
    private readonly waiting: (() => void)[] = [];

    public run<T>(task: () => Observable<T>): Observable<T> {
        return new Observable<T>((subscriber) => {
            let running: Subscription | null = null;
            let hasStarted = false;
            let hasReleased = false;

            const release = (): void => {
                if (hasReleased) return;
                hasReleased = true;
                this.isBusy = false;
                this.waiting.shift()?.();
            };

            const start = (): void => {
                hasStarted = true;
                this.isBusy = true;
                running = defer(task).pipe(finalize(release)).subscribe(subscriber);
            };

            if (this.isBusy) {
                this.waiting.push(start);
            } else {
                start();
            }

            return () => {
                if (hasStarted) {
                    running?.unsubscribe();
                    return;
                }
                const index = this.waiting.indexOf(start);
                if (index >= 0) this.waiting.splice(index, 1);
            };
        });
    }
}
