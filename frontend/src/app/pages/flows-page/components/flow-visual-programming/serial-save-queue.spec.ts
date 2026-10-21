import { Subject, throwError } from 'rxjs';

import { SerialSaveQueue } from './serial-save-queue';

describe('SerialSaveQueue', () => {
    it('starts a task only once the one before it has completed', () => {
        const queue = new SerialSaveQueue();
        const first = new Subject<string>();
        const started: string[] = [];

        queue.run(() => (started.push('first'), first)).subscribe();
        queue.run(() => (started.push('second'), first)).subscribe();
        expect(started).toEqual(['first']);

        first.complete();
        expect(started).toEqual(['first', 'second']);
    });

    it('builds nothing before its turn, so a task reads state the previous one left', () => {
        const queue = new SerialSaveQueue();
        const first = new Subject<void>();
        let version = 1;
        const sentWith: number[] = [];

        queue.run(() => first).subscribe({ complete: () => (version = 2) });
        queue
            .run(() => {
                sentWith.push(version);
                return new Subject<void>();
            })
            .subscribe();

        first.complete();
        expect(sentWith).toEqual([2]);
    });

    it('releases the next task when a task errors', () => {
        const queue = new SerialSaveQueue();
        const started: string[] = [];

        queue.run(() => throwError(() => new Error('boom'))).subscribe({ error: () => undefined });
        queue.run(() => (started.push('after'), new Subject<void>())).subscribe();

        expect(started).toEqual(['after']);
    });

    it('drops a waiting task that is unsubscribed, without blocking the line', () => {
        const queue = new SerialSaveQueue();
        const first = new Subject<void>();
        const started: string[] = [];

        queue.run(() => first).subscribe();
        const waiting = queue.run(() => (started.push('dropped'), new Subject<void>())).subscribe();
        queue.run(() => (started.push('kept'), new Subject<void>())).subscribe();

        waiting.unsubscribe();
        first.complete();

        expect(started).toEqual(['kept']);
    });

    it('lets the next task start when a running one is unsubscribed', () => {
        const queue = new SerialSaveQueue();
        const started: string[] = [];

        const running = queue.run(() => new Subject<void>()).subscribe();
        queue.run(() => (started.push('next'), new Subject<void>())).subscribe();

        running.unsubscribe();
        expect(started).toEqual(['next']);
    });
});
