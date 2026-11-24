import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export type ToastPosition = 'top-right' | 'bottom-right';

export interface ToastMessage {
    id: number;
    message: string;
    type: ToastType;
    duration: number;
    /** Show the whole message instead of clamping it to 3 lines. */
    fullText: boolean;
    action: ToastAction | null;
}

/** A button on a toast; using it closes the toast. */
export interface ToastAction {
    label: string;
    run: () => void;
}

/** Opt-in display options of one toast. */
export interface ToastOptions {
    /** Show the whole message, however long, instead of clamping it to 3 lines. For messages that must be read in full. */
    fullText?: boolean;
    /** A button that does something about the message, such as downloading what has become ready. */
    action?: ToastAction;
}

/** A released toast stays at least this long, so it does not vanish the moment the pointer leaves it. */
export const MIN_TIME_AFTER_RELEASE_MS = 2_000;

/** The countdown to a toast closing on its own, stopped while anything holds the toast. */
interface AutoClose {
    timer: ReturnType<typeof setTimeout> | null;
    remainingMs: number;
    startedAt: number;
    holds: number;
}

@Injectable({
    providedIn: 'root',
})
export class ToastService {
    private toasts = new BehaviorSubject<ToastMessage[]>([]);
    private counter = 0;
    private toastPositions = new Map<number, ToastPosition>();
    private autoCloses = new Map<number, AutoClose>();
    public defaultPosition: ToastPosition = 'bottom-right';

    get toasts$(): Observable<ToastMessage[]> {
        return this.toasts.asObservable();
    }

    show(
        message: string,
        type: ToastType = 'info',
        duration: number = 3000,
        position?: ToastPosition,
        options: ToastOptions = {}
    ): number {
        // The id lets `remove` take the toast down before its duration ends, e.g. a progress message.
        const id = this.counter++;

        // Store the position for this toast
        this.toastPositions.set(id, position || this.defaultPosition);

        // Add new toast to the list
        const currentToasts = this.toasts.value;
        const newToast: ToastMessage = {
            id,
            message,
            type,
            duration,
            fullText: options.fullText ?? false,
            action: options.action ?? null,
        };

        this.toasts.next([...currentToasts, newToast]);

        this.autoCloses.set(id, { timer: null, remainingMs: duration, startedAt: 0, holds: 0 });
        this.startAutoClose(id);

        return id;
    }

    remove(id: number): void {
        const currentToasts = this.toasts.value;
        this.toasts.next(currentToasts.filter((toast) => toast.id !== id));
        this.toastPositions.delete(id);
        const autoClose = this.autoCloses.get(id);
        if (autoClose?.timer != null) {
            clearTimeout(autoClose.timer);
        }
        this.autoCloses.delete(id);
    }

    /**
     * Keeps the toast up while the user points at it or moves focus into it, so its button can be reached. Every
     * hold is ended by `releaseAutoClose`; the rest of its time runs once the last hold has ended.
     */
    holdAutoClose(id: number): void {
        const autoClose = this.autoCloses.get(id);
        if (!autoClose) {
            return;
        }
        autoClose.holds++;
        if (autoClose.timer != null) {
            clearTimeout(autoClose.timer);
            autoClose.timer = null;
            autoClose.remainingMs = Math.max(autoClose.remainingMs - (Date.now() - autoClose.startedAt), 0);
        }
    }

    releaseAutoClose(id: number): void {
        const autoClose = this.autoCloses.get(id);
        if (!autoClose || autoClose.holds === 0) {
            return;
        }
        autoClose.holds--;
        if (autoClose.holds === 0) {
            autoClose.remainingMs = Math.max(autoClose.remainingMs, MIN_TIME_AFTER_RELEASE_MS);
            this.startAutoClose(id);
        }
    }

    success(message: string, duration: number = 5000, position?: ToastPosition, options?: ToastOptions): void {
        this.show(message, 'success', duration, position, options);
    }

    error(message: string, duration: number = 7000, position?: ToastPosition, options?: ToastOptions): void {
        this.show(message, 'error', duration, position, options);
    }

    warning(message: string, duration: number = 6000, position?: ToastPosition, options?: ToastOptions): void {
        this.show(message, 'warning', duration, position, options);
    }

    info(message: string, duration: number = 5000, position?: ToastPosition, options?: ToastOptions): void {
        this.show(message, 'info', duration, position, options);
    }

    // Helper method to get the position for a specific toast
    getPositionForToast(id: number): ToastPosition {
        return this.toastPositions.get(id) || this.defaultPosition;
    }

    // Set the default position for all toasts (unless overridden per toast)
    setDefaultPosition(position: ToastPosition): void {
        this.defaultPosition = position;
    }

    private startAutoClose(id: number): void {
        const autoClose = this.autoCloses.get(id);
        if (!autoClose) {
            return;
        }
        autoClose.startedAt = Date.now();
        autoClose.timer = setTimeout(() => this.remove(id), autoClose.remainingMs);
    }
}
