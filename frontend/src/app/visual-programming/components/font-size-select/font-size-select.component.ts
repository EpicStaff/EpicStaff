import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    effect,
    ElementRef,
    forwardRef,
    inject,
    input,
    output,
    signal,
    TemplateRef,
    viewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

const DEFAULT_FONT_SIZES: number[] = Array.from({ length: 24 }, (_, i) => 10 + i * 2);

@Component({
    selector: 'app-font-size-select',
    imports: [OverlayModule],
    templateUrl: './font-size-select.component.html',
    styleUrls: ['./font-size-select.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => FontSizeSelectComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class FontSizeSelectComponent implements ControlValueAccessor {
    readonly sizes = input<number[]>(DEFAULT_FONT_SIZES);

    /** Initial value when used without ngModel. Synced into the internal signal on change. */
    readonly initialValue = input<number | undefined>(undefined, { alias: 'value' });
    readonly valueChange = output<number>();

    readonly selectedValue = signal<number>(14);
    protected readonly controlDisabled = signal(false);
    protected readonly open = signal(false);

    private readonly triggerButton = viewChild.required<ElementRef<HTMLButtonElement>>('triggerButton');
    private readonly dropdownTemplate = viewChild.required<TemplateRef<unknown>>('dropdownTemplate');

    private readonly overlay = inject(Overlay);
    private readonly overlayPositionBuilder = inject(OverlayPositionBuilder);
    private readonly viewContainerRef = inject(ViewContainerRef);
    private readonly destroyRef = inject(DestroyRef);

    private overlayRef: OverlayRef | null = null;
    private onChange: (value: number) => void = () => {};
    private onTouched: () => void = () => {};

    constructor() {
        effect(() => {
            const v = this.initialValue();
            if (v != null) {
                this.selectedValue.set(v);
            }
        });
    }

    protected toggle(): void {
        this.open() ? this.close() : this.openDropdown();
    }

    protected selectSize(size: number): void {
        this.selectedValue.set(size);
        this.onChange(size);
        this.valueChange.emit(size);
        this.onTouched();
        this.close();
    }

    writeValue(value: number): void {
        if (value != null) {
            this.selectedValue.set(value);
        }
    }

    registerOnChange(fn: (value: number) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.controlDisabled.set(isDisabled);
    }

    private openDropdown(): void {
        const origin = this.triggerButton().nativeElement;

        const positionStrategy = this.overlayPositionBuilder
            .flexibleConnectedTo(origin)
            .withPositions([
                { originX: 'start', originY: 'bottom', overlayX: 'start', overlayY: 'top', offsetY: 4 },
                { originX: 'start', originY: 'top', overlayX: 'start', overlayY: 'bottom', offsetY: -4 },
            ])
            .withPush(false);

        this.overlayRef = this.overlay.create({
            positionStrategy,
            scrollStrategy: this.overlay.scrollStrategies.reposition(),
            hasBackdrop: true,
            backdropClass: 'transparent-backdrop',
            minWidth: 200,
        });

        this.overlayRef
            .backdropClick()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => this.close());

        const portal = new TemplatePortal(this.dropdownTemplate(), this.viewContainerRef);
        this.overlayRef.attach(portal);
        this.open.set(true);
    }

    private close(): void {
        if (this.overlayRef) {
            this.overlayRef.detach();
            this.overlayRef.dispose();
            this.overlayRef = null;
        }
        this.onTouched();
        this.open.set(false);
    }
}
