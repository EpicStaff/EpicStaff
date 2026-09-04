import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { ComponentPortal } from '@angular/cdk/portal';
import {
    AfterViewInit,
    ChangeDetectionStrategy,
    Component,
    computed,
    effect,
    ElementRef,
    forwardRef,
    inject,
    input,
    OnDestroy,
    output,
    OutputRefSubscription,
    signal,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { TooltipComponent } from '@shared/components';

import { VariableDropdownOverlayComponent } from './variable-dropdown-overlay/variable-dropdown-overlay.component';

const DROPDOWN_NAV_KEYS = new Set(['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape']);

/**
 * Textarea that highlights `{key}` tokens in the app's accent color whenever `key` matches
 * one of the `variables()` supplied by the host panel (typically the node's `input_map` keys).
 * Unmatched `{anything}` renders as plain text — no error styling.
 *
 * Mechanism mirrors `expression-editor.component.ts`'s backdrop trick: an opaque
 * `.vht-backdrop` div (rendered HTML, `pointer-events: none`) sits behind a real
 * `<textarea>` whose text is transparent (only the caret is visible). Both layers share
 * identical font metrics/padding via the `vht-text-metrics` mixin so the overlay never
 * drifts from the real text.
 *
 * Dual binding support:
 * - Reactive forms: implements `ControlValueAccessor` — drop in with `formControlName`.
 * - Plain binding: `[value]` + `(valueChange)` for native/non-form call sites.
 * Once `writeValue()` is called at least once (i.e. a `NG_VALUE_ACCESSOR` consumer registered
 * this instance), the `value` input is ignored so the two paths never fight over
 * `displayValue`.
 *
 * `{`-trigger variable dropdown:
 * Typing `{` opens a small flat suggestion list (CDK Overlay, portalled to the body — this
 * component is used inside `.att { overflow: hidden }` cells in the agent tasks table, so an
 * in-place/`position: absolute` dropdown would get clipped there). The approach mirrors
 * `expression-editor.component.ts`'s `@`-trigger handling: `checkForTrigger()` plays the role
 * of its `checkForAutocompleteTrigger()`, and `getCaretCoordinates()` plays the role of its
 * mirror-div cursor-coordinate hack — both retargeted from `@` to `{`.
 */
@Component({
    selector: 'app-variable-highlight-textarea',
    imports: [TooltipComponent],
    templateUrl: './variable-highlight-textarea.component.html',
    styleUrls: ['./variable-highlight-textarea.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => VariableHighlightTextareaComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VariableHighlightTextareaComponent implements ControlValueAccessor, AfterViewInit, OnDestroy {
    public readonly value = input<string>('');
    public readonly valueChange = output<string>();
    public readonly variables = input<string[]>([]);

    public readonly placeholder = input<string>('');
    public readonly rows = input<number>(3);
    public readonly disabled = input<boolean>(false);
    public readonly invalid = input<boolean>(false);

    public readonly label = input<string>('');
    public readonly tooltipText = input<string>('');
    public readonly icon = input<string>('help_outline');
    public readonly required = input<boolean>(false);

    @ViewChild('backdrop', { static: true })
    private backdropRef!: ElementRef<HTMLDivElement>;

    @ViewChild('textareaRef', { static: true })
    private textareaRef!: ElementRef<HTMLTextAreaElement>;

    public readonly displayValue = signal<string>('');

    private readonly controlDisabled = signal(false);
    public readonly isDisabled = computed(() => this.disabled() || this.controlDisabled());

    private readonly viewReady = signal(false);
    private cvaActive = false;

    private onChange: (value: string) => void = () => {};
    private onTouched: () => void = () => {};

    private readonly dropdownOpen = signal(false);
    private readonly triggerIndex = signal<number | null>(null);
    private readonly dropdownFilter = signal('');
    private readonly activeIndex = signal(0);
    private lastCursorPosition = 0;
    private readonly dismissedTriggerIndex = signal<number | null>(null);

    private readonly filteredVariables = computed<string[]>(() => {
        const filter = this.dropdownFilter().toLowerCase();
        const names = this.variables();
        if (!filter) return names;
        return names.filter((name) => name.toLowerCase().includes(filter));
    });

    private overlayRef: OverlayRef | null = null;
    private dropdownInstance: VariableDropdownOverlayComponent | null = null;
    private dropdownSelectSubscription: OutputRefSubscription | null = null;

    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);

    constructor() {
        effect(() => {
            const incoming = this.value();
            if (this.cvaActive) return;
            this.displayValue.set(incoming);
        });

        effect(() => {
            const text = this.displayValue();
            const vars = this.variables();
            if (!this.viewReady()) return;
            this.renderHighlight(text, vars);
        });

        effect(() => {
            if (this.dropdownOpen()) {
                this.openOverlay();
            } else {
                this.closeOverlay();
            }
        });

        effect(() => {
            const items = this.filteredVariables();
            const active = this.activeIndex();
            this.dropdownInstance?.updateItems(items, active);
        });
    }

    ngAfterViewInit(): void {
        this.viewReady.set(true);
    }

    ngOnDestroy(): void {
        this.closeOverlay();
    }

    writeValue(value: string | null): void {
        this.cvaActive = true;
        this.displayValue.set(value ?? '');
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

    onInput(event: Event): void {
        if (this.isDisabled()) return;
        const textarea = event.target as HTMLTextAreaElement;
        const newValue = textarea.value;
        this.displayValue.set(newValue);
        this.onChange(newValue);
        this.valueChange.emit(newValue);
        this.lastCursorPosition = textarea.selectionStart;

        this.dismissedTriggerIndex.set(null);
        this.checkForTrigger(textarea.selectionStart);
    }

    onBlur(): void {
        this.onTouched();
        this.closeDropdown();
    }

    onScroll(): void {
        if (!this.backdropRef || !this.textareaRef) return;
        this.backdropRef.nativeElement.scrollTop = this.textareaRef.nativeElement.scrollTop;
        this.backdropRef.nativeElement.scrollLeft = this.textareaRef.nativeElement.scrollLeft;
    }

    onClick(event: MouseEvent): void {
        const textarea = event.target as HTMLTextAreaElement;
        this.lastCursorPosition = textarea.selectionStart;
        this.checkForTrigger(textarea.selectionStart);
    }

    onKeyUp(event: KeyboardEvent): void {
        const textarea = event.target as HTMLTextAreaElement;
        this.lastCursorPosition = textarea.selectionStart;
        this.checkForTrigger(textarea.selectionStart);
    }

    onKeyDown(event: KeyboardEvent): void {
        if (!this.dropdownOpen() || !DROPDOWN_NAV_KEYS.has(event.key)) return;

        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                this.moveActive(1);
                break;
            case 'ArrowUp':
                event.preventDefault();
                this.moveActive(-1);
                break;
            case 'Enter':
            case 'Tab':
                if (this.filteredVariables().length === 0) return;
                event.preventDefault();
                this.acceptActive();
                break;
            case 'Escape':
                event.preventDefault();
                event.stopPropagation();
                this.dismissedTriggerIndex.set(this.triggerIndex());
                this.closeDropdown();
                break;
        }
    }

    private moveActive(delta: number): void {
        const count = this.filteredVariables().length;
        if (count === 0) return;
        this.activeIndex.update((current) => (current + delta + count) % count);
    }

    private acceptActive(): void {
        const items = this.filteredVariables();
        const name = items[this.activeIndex()];
        if (name === undefined) return;
        this.insertVariable(name);
    }

    private checkForTrigger(cursorPosition: number): void {
        const text = this.displayValue();
        const textBeforeCursor = text.substring(0, cursorPosition);
        const openIndex = textBeforeCursor.lastIndexOf('{');

        if (this.dismissedTriggerIndex() !== null && this.dismissedTriggerIndex() !== openIndex) {
            this.dismissedTriggerIndex.set(null);
        }

        if (openIndex === -1) {
            this.closeDropdown();
            return;
        }

        const partial = textBeforeCursor.substring(openIndex + 1);
        if (partial.includes('}') || /\s/.test(partial)) {
            this.closeDropdown();
            return;
        }

        if (this.variables().length === 0) {
            this.closeDropdown();
            return;
        }

        if (this.dismissedTriggerIndex() === openIndex) {
            return;
        }

        this.triggerIndex.set(openIndex);
        this.dropdownFilter.set(partial);
        this.activeIndex.set(0);
        this.dropdownOpen.set(true);
    }

    private closeDropdown(): void {
        this.dropdownOpen.set(false);
        this.triggerIndex.set(null);
        this.dropdownFilter.set('');
    }

    private insertVariable(name: string): void {
        const openIndex = this.triggerIndex();
        if (openIndex == null) return;

        const textarea = this.textareaRef.nativeElement;
        const text = this.displayValue();
        const before = text.substring(0, openIndex);
        const after = text.substring(this.lastCursorPosition);
        const inserted = `{${name}}`;
        const newValue = `${before}${inserted}${after}`;
        const newCursorPosition = before.length + inserted.length;

        textarea.value = newValue;
        textarea.setSelectionRange(newCursorPosition, newCursorPosition);
        textarea.focus();
        this.lastCursorPosition = newCursorPosition;

        this.displayValue.set(newValue);
        this.onChange(newValue);
        this.valueChange.emit(newValue);

        this.closeDropdown();
    }

    private openOverlay(): void {
        if (this.overlayRef?.hasAttached()) return;

        const coords = this.getCaretCoordinates();

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(this.textareaRef)
            .withPositions([
                {
                    originX: 'start',
                    originY: 'top',
                    overlayX: 'start',
                    overlayY: 'top',
                    offsetX: coords.left,
                    offsetY: coords.top + 4,
                },
                {
                    originX: 'start',
                    originY: 'top',
                    overlayX: 'start',
                    overlayY: 'bottom',
                    offsetX: coords.left,
                    offsetY: coords.top - 4,
                },
            ])
            .withPush(true)
            .withViewportMargin(8)
            .withFlexibleDimensions(false);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: false,
        });

        const portal = new ComponentPortal(VariableDropdownOverlayComponent, this.viewContainerRef);
        const componentRef = this.overlayRef.attach(portal);
        this.dropdownInstance = componentRef.instance;

        this.dropdownSelectSubscription = this.dropdownInstance.itemSelected.subscribe((name: string) => {
            this.insertVariable(name);
        });

        this.dropdownInstance.updateItems(this.filteredVariables(), this.activeIndex());
    }

    private closeOverlay(): void {
        this.dropdownSelectSubscription?.unsubscribe();
        this.dropdownSelectSubscription = null;
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
            this.dropdownInstance = null;
        }
    }

    private getCaretCoordinates(): { top: number; left: number } {
        const textarea = this.textareaRef.nativeElement;
        const openIndex = this.triggerIndex();
        if (openIndex == null) return { top: 0, left: 0 };

        const textToMeasure = this.displayValue().substring(0, openIndex);

        const mirror = document.createElement('div');
        const style = getComputedStyle(textarea);

        mirror.style.fontFamily = style.fontFamily;
        mirror.style.fontSize = style.fontSize;
        mirror.style.lineHeight = style.lineHeight;
        mirror.style.fontWeight = style.fontWeight;
        mirror.style.letterSpacing = style.letterSpacing;
        mirror.style.whiteSpace = 'pre-wrap';
        mirror.style.wordBreak = 'break-word';
        mirror.style.width = style.width;
        mirror.style.padding = style.padding;
        mirror.style.boxSizing = style.boxSizing;
        mirror.style.position = 'fixed';
        mirror.style.visibility = 'hidden';

        const textareaRect = textarea.getBoundingClientRect();
        mirror.style.top = `${textareaRect.top}px`;
        mirror.style.left = `${textareaRect.left}px`;

        mirror.textContent = textToMeasure;
        const span = document.createElement('span');
        span.textContent = '{';
        mirror.appendChild(span);

        document.body.appendChild(mirror);
        const spanRect = span.getBoundingClientRect();
        document.body.removeChild(mirror);

        return {
            top: spanRect.bottom - textareaRect.top - textarea.scrollTop,
            left: spanRect.left - textareaRect.left - textarea.scrollLeft,
        };
    }

    private renderHighlight(text: string, variableNames: string[]): void {
        if (!this.backdropRef) return;

        const escaped = this.escapeHtml(text ?? '');
        const validNames = new Set(variableNames);

        let highlighted = escaped.replace(/\{([^{}\s]+)\}/g, (match, name: string) =>
            validNames.has(name) ? `<span class="vht-variable">${match}</span>` : match
        );

        if (highlighted.endsWith('\n')) {
            highlighted += '<br>';
        }

        const backdrop = this.backdropRef.nativeElement;
        backdrop.innerHTML = highlighted;
        backdrop.scrollTop = this.textareaRef.nativeElement.scrollTop;
        backdrop.scrollLeft = this.textareaRef.nativeElement.scrollLeft;
    }

    private escapeHtml(text: string): string {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
}
