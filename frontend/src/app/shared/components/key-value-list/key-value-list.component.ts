import { Overlay, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    forwardRef,
    inject,
    input,
    signal,
    TemplateRef,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ControlValueAccessor,
    FormsModule,
    NG_VALIDATORS,
    NG_VALUE_ACCESSOR,
    ValidationErrors,
    Validator,
} from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SecretsStorageService } from '@shared/services';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { SelectItem } from '../select/select.component';
import { TooltipComponent } from '../tooltip/tooltip.component';
import {
    getHeaderRowError,
    HEADER_VALUE_LINE_BREAK_ERROR,
    HEADER_VALUE_REQUIRED_ERROR,
} from './header-validation.util';

interface KeyValueItem {
    name: string;
    value: string;
}

type SecretPickerTarget = number;

/** Whole value is exactly an `epicstaff_secret(<name>)` marker — see secret_resolver.py. */
const SECRET_MARKER_RE = /^epicstaff_secret\(([^)]*)\)$/;
let nextInstanceId = 0;
const toSecretMarker = (name: string): string => `epicstaff_secret(${name})`;

@Component({
    selector: 'app-key-value-list',
    imports: [TooltipComponent, FormsModule, MatTooltipModule, AppSvgIconComponent],
    templateUrl: './key-value-list.component.html',
    styleUrls: ['./key-value-list.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => KeyValueListComponent),
            multi: true,
        },
        {
            provide: NG_VALIDATORS,
            useExisting: forwardRef(() => KeyValueListComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KeyValueListComponent implements ControlValueAccessor, Validator {
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);

    readonly instanceId = nextInstanceId++;

    label = input<string>('');
    tooltipText = input<string>('');
    icon = input<string>('help_outline');
    required = input<boolean>(false);
    namePlaceholder = input<string>('Name');
    valuePlaceholder = input<string>('Value');

    items = signal<KeyValueItem[]>([]);
    isDisabled = signal<boolean>(false);

    private readonly suggestionsTemplate = viewChild.required<TemplateRef<unknown>>('suggestionsTemplate');
    private readonly activeTarget = signal<SecretPickerTarget | null>(null);
    private overlayRef: OverlayRef | null = null;
    private activeAnchor: HTMLElement | null = null;
    // CDK's scroll strategies need cdkScrollable on the container to fire; the dialog's
    // `.form` lacks it, so we reposition (or close if the anchor got clipped) ourselves.
    private readonly onAncestorScroll = (): void => {
        if (!this.overlayRef || !this.activeAnchor) return;
        if (this.isClipped(this.activeAnchor)) {
            this.closeSuggestions();
            return;
        }
        this.overlayRef.updatePosition();
    };

    secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({ name: secret.name, value: secret.name }))
    );

    /** Secrets filtered by whatever text currently sits in the value field being edited. */
    activeSuggestions = computed<SelectItem[]>(() => {
        const target = this.activeTarget();
        if (target === null) return [];

        const text = this.items()[target]?.value ?? '';
        const q = text.trim().toLowerCase();
        const all = this.secretItems();
        return q ? all.filter((item) => item.name.toLowerCase().includes(q)) : all;
    });

    /** Secret name if `value` is exactly an `epicstaff_secret(<name>)` marker, else null. */
    private secretNameOf(value: string): string | null {
        return value.trim().match(SECRET_MARKER_RE)?.[1] ?? null;
    }

    isSecretValue(value: string): boolean {
        return this.secretNameOf(value) !== null;
    }

    /** What the user sees: the secret's plain name, never the `epicstaff_secret(...)` payload syntax. */
    displayValue(value: string): string {
        return this.secretNameOf(value) ?? value;
    }

    /** Error text per row, null when the row is valid or entirely empty (empty rows are ignored). */
    rowErrors = computed<(string | null)[]>(() => {
        const items = this.items();
        return items.map((item, index) =>
            getHeaderRowError(
                item.name,
                item.value,
                items.filter((_, other) => other !== index).map((other) => other.name)
            )
        );
    });

    private readonly hasErrors = computed<boolean>(() => this.rowErrors().some((error) => error !== null));

    private onChange: (value: Record<string, string>) => void = () => {};
    private onTouched: () => void = () => {};

    constructor() {
        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });

        this.destroyRef.onDestroy(() => this.disposeOverlay());
    }

    updateName(index: number, name: string): void {
        this.updateItems((items) => items.map((item, i) => (i === index ? { ...item, name } : item)));
    }

    onNameBlur(index: number): void {
        const current = this.items()[index];
        if (!current || current.name.trim() === current.name) return;
        this.updateItems((items) => items.map((item, i) => (i === index ? { ...item, name: item.name.trim() } : item)));
    }

    updateValue(index: number, value: string): void {
        this.updateItems((items) => items.map((item, i) => (i === index ? { ...item, value } : item)));
    }

    removeCard(index: number): void {
        this.updateItems((items) => items.filter((_, i) => i !== index));
    }

    /** The always-present empty row at the end, where the next header is typed. */
    isSpareRow(index: number): boolean {
        return index === this.items().length - 1 && this.isBlank(this.items()[index]);
    }

    errorId(index: number): string {
        return `kv-list-${this.instanceId}-error-${index}`;
    }

    hasNameError(index: number): boolean {
        const error = this.rowErrors()[index];
        return error !== null && error !== HEADER_VALUE_REQUIRED_ERROR && error !== HEADER_VALUE_LINE_BREAK_ERROR;
    }

    hasValueError(index: number): boolean {
        const error = this.rowErrors()[index];
        return error === HEADER_VALUE_REQUIRED_ERROR || error === HEADER_VALUE_LINE_BREAK_ERROR;
    }

    onValueFocus(event: FocusEvent, target: SecretPickerTarget): void {
        if (this.isDisabled()) return;
        this.activeTarget.set(target);
        this.openSuggestions(event.target as HTMLElement);
    }

    selectSuggestion(item: SelectItem): void {
        const target = this.activeTarget();
        if (target === null || typeof item.value !== 'string') return;

        const marker = toSecretMarker(item.value);
        this.updateValue(target, marker);
        this.closeSuggestions();
    }

    closeSuggestions(): void {
        this.disposeOverlay();
        this.activeTarget.set(null);
    }

    /** True once `el` has scrolled (even partially) out of any ancestor that clips it. */
    private isClipped(el: HTMLElement): boolean {
        const rect = el.getBoundingClientRect();
        for (let node = el.parentElement; node; node = node.parentElement) {
            const style = getComputedStyle(node);
            if (!/(auto|scroll|hidden)/.test(style.overflowY)) continue;

            const ancestorRect = node.getBoundingClientRect();
            if (rect.top < ancestorRect.top || rect.bottom > ancestorRect.bottom) return true;
        }
        return false;
    }

    private openSuggestions(anchor: HTMLElement): void {
        this.disposeOverlay();
        this.activeAnchor = anchor;

        const positionStrategy = this.overlay
            .position()
            .flexibleConnectedTo(anchor)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(true)
            .withViewportMargin(8);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.noop(),
            hasBackdrop: false,
            width: anchor.offsetWidth,
        });

        this.overlayRef
            .outsidePointerEvents()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((event) => {
                if (event.target === anchor) return;
                this.closeSuggestions();
            });

        window.addEventListener('scroll', this.onAncestorScroll, { capture: true, passive: true });

        this.overlayRef.attach(new TemplatePortal(this.suggestionsTemplate(), this.viewContainerRef));
    }

    private disposeOverlay(): void {
        window.removeEventListener('scroll', this.onAncestorScroll, true);
        this.activeAnchor = null;
        if (this.overlayRef) {
            this.overlayRef.dispose();
            this.overlayRef = null;
        }
    }

    private isBlank(item: KeyValueItem): boolean {
        return !item.name.trim() && !item.value.trim();
    }

    private updateItems(update: (items: KeyValueItem[]) => KeyValueItem[]): void {
        this.items.set(this.withSpareRow(update(this.items())));
        this.emit();
    }

    private withSpareRow(items: KeyValueItem[]): KeyValueItem[] {
        let end = items.length;
        while (end > 0 && this.isBlank(items[end - 1])) end--;
        const spare = items[end] ?? { name: '', value: '' };
        return [...items.slice(0, end), spare];
    }

    /** Emits complete rows only; empty rows are ignored and half-filled rows are reported by validate(). */
    private emit(): void {
        const record = Object.fromEntries(
            this.items()
                .filter((item) => item.name.trim() && item.value.trim())
                .map((item) => [item.name.trim(), item.value])
        );
        this.onChange(record);
        this.onTouched();
    }

    writeValue(value: Record<string, string> | null): void {
        const record = value ?? {};
        const items: KeyValueItem[] = Object.entries(record).map(([name, val]) => ({ name, value: val }));
        this.items.set(this.withSpareRow(items));
    }

    registerOnChange(fn: (value: Record<string, string>) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    validate(): ValidationErrors | null {
        return this.hasErrors() ? { keyValueList: true } : null;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
