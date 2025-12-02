import { Component, ChangeDetectionStrategy, output } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
    selector: 'app-editor-toolbar',
    standalone: true,
    imports: [CommonModule],
    templateUrl: './editor-toolbar.component.html',
    styleUrls: ['./editor-toolbar.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EditorToolbarComponent {
    public tokenInserted = output<string>();

    public insertToken(token: string): void {
        this.tokenInserted.emit(token);
    }
}

