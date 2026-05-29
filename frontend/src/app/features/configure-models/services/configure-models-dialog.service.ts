import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { inject, Injectable } from '@angular/core';
import { Observable, Subject } from 'rxjs';

import { ConfigureModelsDialogComponent } from '../components/configure-models-dialog/configure-models-dialog.component';

@Injectable({
    providedIn: 'root',
})
export class ConfigureModelsDialogService {
    private readonly dialog: Dialog = inject(Dialog);

    private currentRef: DialogRef<void> | null = null;
    private readonly openedSubject = new Subject<void>();
    public readonly opened$: Observable<void> = this.openedSubject.asObservable();

    public open(): DialogRef<void> {
        if (this.currentRef) {
            this.openedSubject.next();
            return this.currentRef;
        }
        const ref = this.dialog.open<void>(ConfigureModelsDialogComponent, {
            width: 'calc(100vw - 2rem)',
            height: 'calc(100vh - 2rem)',
        });
        this.currentRef = ref;
        ref.closed.subscribe(() => {
            if (this.currentRef === ref) this.currentRef = null;
        });
        this.openedSubject.next();
        return ref;
    }

    public close(): void {
        this.currentRef?.close();
    }

    public isOpen(): boolean {
        return this.currentRef !== null;
    }
}
