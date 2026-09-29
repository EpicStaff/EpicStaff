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
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';
import { MatTooltipModule } from '@angular/material/tooltip';
import { SecretsStorageService } from '@shared/services';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { SelectItem } from '../select/select.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

interface KeyValueItem {
    name: string;
    value: string;
}

type SecretPickerTarget = number | 'draft';

/** Whole value is exactly an `epicstaff_secret(<name>)` marker — see secret_resolver.py. */
const SECRET_MARKER_RE = /^epicstaff_secret\(([^)]*)\)$/;
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
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KeyValueListComponent implements ControlValueAccessor {
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly overlay = inject(Overlay);
    private readonly viewContainerRef = inject(ViewContainerRef);

    label = input<string>('');
    tooltipText = input<string>('');
    icon = input<string>('help_outline');
    required = input<boolean>(false);
    namePlaceholder = input<string>('Name');
    valuePlaceholder = input<string>('Value');

    items = signal<KeyValueItem[]>([]);
    draftName = signal<string>('');
    draftValue = signal<string>('');
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

        const text = target === 'draft' ? this.draftValue() : (this.items()[target]?.value ?? '');
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

    isDuplicateName = computed<boolean>(() => {
        const name = this.draftName().trim().toLowerCase();
        if (!name) return false;

        return this.items().some((item) => item.name.trim().toLowerCase() === name);
    });

    private onChange: (value: Record<string, string>) => void = () => {};
    private onTouched: () => void = () => {};

    constructor() {
        this.secretsStorageService
            .getSecrets()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({ error: () => {} });

        this.destroyRef.onDestroy(() => this.disposeOverlay());
    }

    confirm(): void {
        const name = this.draftName().trim();
        if (!name || this.isDuplicateName()) return;

        const value = this.draftValue();
        this.items.update((items) => [...items, { name, value }]);

        this.draftName.set('');
        this.draftValue.set('');
        this.emit();
    }

    isRowDuplicate(index: number): boolean {
        const name = this.items()[index]?.name.trim().toLowerCase();
        if (!name) return false;

        return this.items().some((item, i) => i !== index && item.name.trim().toLowerCase() === name);
    }

    updateName(index: number, name: string): void {
        this.items.update((items) => items.map((item, i) => (i === index ? { ...item, name } : item)));
        this.emit();
    }

    onNameBlur(index: number): void {
        this.items.update((items) =>
            items.map((item, i) => (i === index ? { ...item, name: item.name.trim() } : item))
        );
        this.emit();
    }

    updateValue(index: number, value: string): void {
        this.items.update((items) => items.map((item, i) => (i === index ? { ...item, value } : item)));
        this.emit();
    }

    removeCard(index: number): void {
        this.items.update((items) => items.filter((_, i) => i !== index));
        this.emit();
    }

    handleKeydown(event: KeyboardEvent): void {
        if (event.key === 'Enter') {
            event.preventDefault();
            this.confirm();
        }
        if (event.key === 'Escape') {
            this.draftName.set('');
            this.draftValue.set('');
        }
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
        if (target === 'draft') {
            this.draftValue.set(marker);
        } else {
            this.updateValue(target, marker);
        }
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

    private emit(): void {
        const record = Object.fromEntries(this.items().map((i) => [i.name, i.value]));
        this.onChange(record);
        this.onTouched();
    }

    writeValue(value: Record<string, string> | null): void {
        const record = value ?? {};
        const items: KeyValueItem[] = Object.entries(record).map(([name, val]) => ({ name, value: val }));
        this.items.set(items);
    }

    registerOnChange(fn: (value: Record<string, string>) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.isDisabled.set(isDisabled);
    }
}
