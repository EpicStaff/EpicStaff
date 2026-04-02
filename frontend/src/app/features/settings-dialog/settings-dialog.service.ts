import { Dialog, DialogRef } from '@angular/cdk/dialog';
import { Injectable } from '@angular/core';

import { SettingsDialogComponent } from './settings-dialog.component';

@Injectable({
    providedIn: 'root',
})
export class SettingsDialogService {
    public constructor(private readonly dialog: Dialog) {}

    public openSettingsDialog(): DialogRef<void> {
        return this.dialog.open<void>(SettingsDialogComponent, {
            width: '950px',
            maxWidth: '95vw',
            height: '700px',
            maxHeight: '95vh',
        });
    }
}
