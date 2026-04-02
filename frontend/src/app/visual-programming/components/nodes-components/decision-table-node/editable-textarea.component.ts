import { AfterViewInit, Component, ElementRef, EventEmitter, Input, Output, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';

@Component({
    selector: 'app-editable-textarea',
    standalone: true,
    imports: [FormsModule],
    template: `
        <textarea
            #textarea
            [(ngModel)]="value"
            (keydown.enter)="$event.preventDefault(); emitValue()"
            (blur)="emitValue()"
            class="cell-textarea"
        ></textarea>
    `,
    styles: [
        `
            :host {
                display: block;
                width: 100%;
                height: 100%;
            }

            .cell-textarea {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                padding: 12px 18px;
                resize: none;
                border: none;
                outline: none;
                background: var(--color-nodes-background);
                color: var(--color-text-primary);
                font-size: inherit;
                font-family: inherit;
                z-index: 10;
            }
        `,
    ],
})
export class EditableTextareaComponent implements AfterViewInit {
    @Input() value: string = '';
    @Output() valueChange = new EventEmitter<string>();
    @ViewChild('textarea') textarea!: ElementRef<HTMLTextAreaElement>;

    ngAfterViewInit() {
        setTimeout(() => {
            const el = this.textarea.nativeElement;
            el.focus();
            el.selectionStart = el.selectionEnd = el.value.length;
        }, 0);
    }

    emitValue() {
        this.valueChange.emit(this.value);
    }
}
