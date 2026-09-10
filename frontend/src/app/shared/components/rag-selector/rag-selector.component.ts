import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    signal,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

import { AppSvgIconComponent } from '../app-svg-icon/app-svg-icon.component';
import { TooltipComponent } from '../tooltip/tooltip.component';

export type RagSelectorStatus = 'new' | 'processing' | 'completed' | 'warning' | 'failed';

export interface RagSelectorItem {
    rag_id: number;
    rag_type: string;
    rag_status: string;
}

export interface RagSelectorValue {
    rag_id: number;
    rag_type: string;
}

interface RagStatusDisplay {
    text: string;
    icon: string;
    color: string;
}

const RAG_STATUS_DISPLAY: Record<RagSelectorStatus, RagStatusDisplay> = {
    new: { text: 'Indexing', icon: 'processing', color: 'var(--color-ks-status-blue)' },
    processing: { text: 'Indexing', icon: 'processing', color: 'var(--color-ks-status-blue)' },
    completed: { text: 'Ready', icon: 'check', color: 'var(--color-ks-status-completed)' },
    warning: { text: 'Warning', icon: 'warning', color: 'var(--color-ks-status-warning)' },
    failed: { text: 'Failed', icon: 'x', color: 'var(--color-ks-status-failed)' },
};

@Component({
    selector: 'app-rag-selector',
    imports: [OverlayModule, TooltipComponent, AppSvgIconComponent],
    templateUrl: './rag-selector.component.html',
    styleUrls: ['./rag-selector.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: RagSelectorComponent,
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RagSelectorComponent implements ControlValueAccessor {
    rags = input<RagSelectorItem[]>([]);
    label = input<string>('');
    tooltipText = input<string>('');
    placeholder = input<string>('Select RAG');
    loading = input<boolean>(false);
    invalid = input<boolean>(false);
    required = input<boolean>(false);

    readonly value = signal<RagSelectorValue | null>(null);
    readonly open = signal(false);
    readonly disabled = signal(false);

    readonly selectedRag = computed<RagSelectorItem | null>(() => {
        const current = this.value();
        if (!current) return null;
        return this.rags().find((r) => r.rag_id === current.rag_id && r.rag_type === current.rag_type) ?? null;
    });

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: TemplateRef<unknown>;

    private overlayRef: OverlayRef | null = null;

    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);
    private destroyRef = inject(DestroyRef);

    private onChange: (value: RagSelectorValue | null) => void = () => {};
    private onTouched: () => void = () => {};

    getRagTypeName(ragType: string): string {
        return ragType ? ragType.charAt(0).toUpperCase() + ragType.slice(1) : ragType;
    }

    getStatusDisplay(status: string): RagStatusDisplay | null {
        return RAG_STATUS_DISPLAY[status as RagSelectorStatus] ?? null;
    }

    toggle(): void {
        if (this.disabled() || this.loading()) return;
        this.open() ? this.close() : this.openDropdown();
    }

    openDropdown(): void {
        if (!this.overlayRef) {
            const positionStrategy = this.overlayPositionBuilder
                .flexibleConnectedTo(this.triggerBtn)
                .withPositions([
                    {
                        originX: 'start',
                        originY: 'bottom',
                        overlayX: 'start',
                        overlayY: 'top',
                        offsetY: 4,
                    },
                    {
                        originX: 'start',
                        originY: 'top',
                        overlayX: 'start',
                        overlayY: 'bottom',
                        offsetY: -4,
                    },
                ])
                .withPush(false);

            this.overlayRef = this.overlay.create({
                positionStrategy,
                scrollStrategy: this.overlay.scrollStrategies.reposition(),
                hasBackdrop: true,
                backdropClass: 'transparent-backdrop',
                width: this.triggerBtn.nativeElement.offsetWidth,
            });

            this.overlayRef
                .backdropClick()
                .pipe(takeUntilDestroyed(this.destroyRef))
                .subscribe(() => this.close());
        }

        const portal = new TemplatePortal(this.dropdownTemplate, this.vcr);
        this.overlayRef.attach(portal);
        this.open.set(true);
    }

    close(): void {
        this.overlayRef?.detach();
        this.onTouched();
        this.open.set(false);
    }

    select(rag: RagSelectorItem | null): void {
        if (this.disabled()) return;
        const next: RagSelectorValue | null = rag ? { rag_id: rag.rag_id, rag_type: rag.rag_type } : null;
        this.value.set(next);
        this.onChange(next);
        this.onTouched();
        this.close();
    }

    writeValue(value: RagSelectorValue | null): void {
        this.value.set(value ?? null);
    }

    registerOnChange(fn: (value: RagSelectorValue | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.disabled.set(isDisabled);
    }
}
