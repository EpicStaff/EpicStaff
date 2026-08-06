import {
    ChangeDetectionStrategy,
    Component,
    computed,
    ElementRef,
    forwardRef,
    HostBinding,
    input,
    signal,
    viewChild,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { TooltipComponent } from '../tooltip/tooltip.component';

const VAR_PATTERN = /\{[^{}\n]+\}/g;

function escapeHtml(text: string): string {
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

@Component({
    selector: 'app-template-textarea',
    imports: [TooltipComponent],
    templateUrl: './template-textarea.component.html',
    styleUrls: ['./template-textarea.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => TemplateTextareaComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TemplateTextareaComponent implements ControlValueAccessor {
    label = input<string>('');
    tooltipText = input<string>('');
    icon = input<string>('help_outline');
    placeholder = input<string>('Enter text...');
    rows = input<number>(3);
    required = input<boolean>(false);
    invalid = input<boolean>(false);
    disabled = input<boolean>(false);
    showLineNumbers = input<boolean>(false);
    resizable = input<boolean>(true);
    stretch = input<boolean>(false);

    private controlDisabled = signal(false);
    isDisabled = computed(() => this.disabled() || this.controlDisabled());

    value = signal<string>('');

    // Trailing newline needs a padding char, otherwise <pre> collapses the last line.
    highlightedHtml = computed(() => {
        const source = this.value();
        const escaped = escapeHtml(source);
        const highlighted = escaped.replace(
            VAR_PATTERN,
            (match) => `<span class="template-textarea__var">${match}</span>`
        );
        return source.endsWith('\n') ? `${highlighted} ` : highlighted;
    });

    lineNumbers = computed<number[]>(() => {
        const count = this.value().split('\n').length;
        return Array.from({ length: count }, (_, i) => i + 1);
    });

    private readonly textareaRef = viewChild<ElementRef<HTMLTextAreaElement>>('textareaRef');
    private readonly highlightRef = viewChild<ElementRef<HTMLElement>>('highlightRef');
    private readonly gutterRef = viewChild<ElementRef<HTMLElement>>('gutterRef');

    private readonly minHeightPx = 40;
    private resizing = false;
    private dragStartY = 0;
    private dragStartHeight = 0;

    private onChange: (value: string) => void = () => {};
    private onTouched: () => void = () => {};

    @HostBinding('class.mod-stretch') get stretchClass(): boolean {
        return this.stretch();
    }

    writeValue(value: string | null): void {
        this.value.set(value ?? '');
    }

    registerOnChange(fn: (value: string) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.controlDisabled.set(isDisabled);
    }

    handleInput(event: Event): void {
        if (this.isDisabled()) return;
        const val = (event.target as HTMLTextAreaElement).value;
        this.value.set(val);
        this.onChange(val);
    }

    handleBlur(): void {
        this.onTouched();
    }

    onScroll(event: Event): void {
        const target = event.target as HTMLTextAreaElement;
        const highlight = this.highlightRef()?.nativeElement;
        const gutter = this.gutterRef()?.nativeElement;
        if (highlight) {
            highlight.scrollTop = target.scrollTop;
            highlight.scrollLeft = target.scrollLeft;
        }
        if (gutter) {
            gutter.scrollTop = target.scrollTop;
        }
    }

    onResizeStart(event: PointerEvent): void {
        if (this.isDisabled() || !this.resizable()) return;
        const textarea = this.textareaRef()?.nativeElement;
        if (!textarea) return;
        event.preventDefault();
        this.resizing = true;
        this.dragStartY = event.clientY;
        this.dragStartHeight = textarea.offsetHeight;
        (event.target as HTMLElement).setPointerCapture(event.pointerId);
    }

    onResizeMove(event: PointerEvent): void {
        if (!this.resizing) return;
        const textarea = this.textareaRef()?.nativeElement;
        if (!textarea) return;
        const delta = event.clientY - this.dragStartY;
        const newHeight = Math.max(this.minHeightPx, this.dragStartHeight + delta);
        textarea.style.height = `${newHeight}px`;
    }

    onResizeEnd(event: PointerEvent): void {
        if (!this.resizing) return;
        this.resizing = false;
        (event.target as HTMLElement).releasePointerCapture(event.pointerId);
    }
}
