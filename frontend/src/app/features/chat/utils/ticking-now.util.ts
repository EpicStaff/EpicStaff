import { inject, NgZone, Signal, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { interval } from 'rxjs';

/**
 * The current time, moved on every `periodMs`, for times shown relative to now ("6m", "today"). Call it in an
 * injection context: it stops when that context is destroyed. The timer runs outside the zone, as a pending interval
 * would keep the app from ever being stable; the signal still re-renders what reads it.
 */
export function tickingNow(periodMs: number): Signal<number> {
    const now = signal(Date.now());
    const ticks = interval(periodMs).pipe(takeUntilDestroyed());
    inject(NgZone).runOutsideAngular(() => ticks.subscribe(() => now.set(Date.now())));
    return now.asReadonly();
}
