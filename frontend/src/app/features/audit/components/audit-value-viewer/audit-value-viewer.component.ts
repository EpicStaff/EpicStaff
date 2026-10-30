import { Component, computed, ElementRef, input, output, viewChild } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';
import { AppSvgIconComponent, CopyButtonComponent, JSON_EDITOR_OPTIONS, JsonEditorComponent } from '@shared/components';

const PLAIN_TEXT_EDITOR_OPTIONS = { ...JSON_EDITOR_OPTIONS, language: 'plaintext', readOnly: true };

@Component({
    selector: 'app-audit-value-viewer',
    imports: [AppSvgIconComponent, CopyButtonComponent, JsonEditorComponent, MatTooltipModule],
    templateUrl: './audit-value-viewer.component.html',
    styleUrls: ['./audit-value-viewer.component.scss'],
    host: { '(document:keydown.escape)': 'onEscape($event)' },
})
export class AuditValueViewerComponent {
    readonly field = input.required<string>();
    readonly rowName = input<string>('');
    readonly value = input.required<string>();
    readonly isPlainText = input<boolean>(false);
    readonly closed = output<void>();

    private readonly closeButton = viewChild.required<ElementRef<HTMLButtonElement>>('closeButton');

    protected readonly title = computed(() => (this.isPlainText() ? 'Text Viewer' : 'JSON Viewer'));
    protected readonly subtitle = computed(() =>
        this.rowName() ? `${this.field()} - ${this.rowName()}` : this.field()
    );
    protected readonly editorOptions = computed(() =>
        this.isPlainText() ? PLAIN_TEXT_EDITOR_OPTIONS : JSON_EDITOR_OPTIONS
    );

    /** Moves the keyboard focus into the viewer, which sits after the table in the Tab order. */
    focus(): void {
        this.closeButton().nativeElement.focus();
    }

    // an open dropdown or other overlay that handled this Escape marks it defaultPrevented; leave the viewer open then
    protected onEscape(event: Event): void {
        if (!event.defaultPrevented) {
            this.closed.emit();
        }
    }
}
