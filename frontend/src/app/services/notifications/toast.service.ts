import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

export type ToastPosition = 'top-right' | 'top-left' | 'top-center' | 'bottom-right' | 'bottom-left' | 'bottom-center';

export interface ToastMessage {
    id: number;
    message: string;
    type: ToastType;
    duration: number;
}

@Injectable({
    providedIn: 'root',
})
export class ToastService {
    private toasts = new BehaviorSubject<ToastMessage[]>([]);
    private counter = 0;
    private toastPositions = new Map<number, ToastPosition>();
    public defaultPosition: ToastPosition = 'bottom-right';

    get toasts$(): Observable<ToastMessage[]> {
        return this.toasts.asObservable();
    }

    show(message: string, type: ToastType = 'info', duration: number = 3000, position?: ToastPosition): void {
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
        };

        this.toasts.next([...currentToasts, newToast]);

        // Remove toast after duration
        setTimeout(() => {
            this.remove(id);
        }, duration);
    }

    remove(id: number): void {
        const currentToasts = this.toasts.value;
        this.toasts.next(currentToasts.filter((toast) => toast.id !== id));
        this.toastPositions.delete(id);
    }

    success(message: string, duration: number = 5000, position?: ToastPosition): void {
        this.show(message, 'success', duration, position);
    }

    error(message: string, duration: number = 7000, position?: ToastPosition): void {
        this.show(message, 'error', duration, position);
    }

    warning(message: string, duration: number = 6000, position?: ToastPosition): void {
        this.show(message, 'warning', duration, position);
    }

    info(message: string, duration: number = 5000, position?: ToastPosition): void {
        this.show(message, 'info', duration, position);
    }

    // Helper method to get the position for a specific toast
    getPositionForToast(id: number): ToastPosition {
        return this.toastPositions.get(id) || this.defaultPosition;
    }

    // Set the default position for all toasts (unless overridden per toast)
    setDefaultPosition(position: ToastPosition): void {
        this.defaultPosition = position;
    }
}
