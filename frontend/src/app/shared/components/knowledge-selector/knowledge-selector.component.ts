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

export interface KnowledgeSelectorRagConfig {
    rag_type: string;
}

export interface KnowledgeSelectorCollection {
    collection_id: number;
    collection_name: string;
    document_count: number;
    rag_configurations: KnowledgeSelectorRagConfig[];
}

const RAG_TYPE_LABELS: Record<string, string> = {
    naive: 'Naive RAG',
    graph: 'Graph RAG',
    hybrid: 'Hybrid RAG',
};

@Component({
    selector: 'app-knowledge-selector',
    imports: [OverlayModule, TooltipComponent, AppSvgIconComponent],
    templateUrl: './knowledge-selector.component.html',
    styleUrls: ['./knowledge-selector.component.scss'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: KnowledgeSelectorComponent,
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class KnowledgeSelectorComponent implements ControlValueAccessor {
    collections = input<KnowledgeSelectorCollection[]>([]);
    label = input<string>('');
    tooltipText = input<string>('');
    placeholder = input<string>('Select knowledge source');
    loading = input<boolean>(false);
    invalid = input<boolean>(false);
    required = input<boolean>(false);

    readonly value = signal<number | null>(null);
    readonly open = signal(false);
    readonly disabled = signal(false);

    readonly selectedCollection = computed<KnowledgeSelectorCollection | null>(() => {
        const id = this.value();
        if (id === null) return null;
        return this.collections().find((c) => c.collection_id === id) ?? null;
    });

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: TemplateRef<unknown>;

    private overlayRef: OverlayRef | null = null;

    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);
    private destroyRef = inject(DestroyRef);

    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    formatRagConfigurations(configs: KnowledgeSelectorRagConfig[]): string {
        return configs.map((c) => RAG_TYPE_LABELS[c.rag_type] ?? c.rag_type).join(' / ');
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

    select(id: number | null): void {
        if (this.disabled()) return;
        this.value.set(id);
        this.onChange(id);
        this.onTouched();
        this.close();
    }

    writeValue(value: number | null): void {
        this.value.set(value ?? null);
    }

    registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.disabled.set(isDisabled);
    }
}
