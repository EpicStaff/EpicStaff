import { Dialog } from '@angular/cdk/dialog';
import { Overlay, OverlayModule, OverlayPositionBuilder, OverlayRef } from '@angular/cdk/overlay';
import { TemplatePortal } from '@angular/cdk/portal';
import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    forwardRef,
    inject,
    input,
    OnInit,
    output,
    signal,
    TemplateRef,
    ViewChild,
    ViewContainerRef,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ControlValueAccessor, FormsModule, NG_VALUE_ACCESSOR } from '@angular/forms';

import { WebhookTriggerModel } from '../../../visual-programming/core/models/webhook-trigger.model';
import { WebhookTriggerService } from '../../services/webhook-trigger/webhook-trigger.service';
import { TooltipComponent } from '../tooltip/tooltip.component';
import {
    WebhookTriggerDialogComponent,
    WebhookTriggerDialogData,
} from '../webhook-trigger-dialog/webhook-trigger-dialog.component';

@Component({
    selector: 'app-webhook-trigger-select',
    templateUrl: './webhook-trigger-select.component.html',
    styleUrls: ['./webhook-trigger-select.component.scss'],
    imports: [FormsModule, OverlayModule, TooltipComponent],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => WebhookTriggerSelectComponent),
            multi: true,
        },
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WebhookTriggerSelectComponent implements ControlValueAccessor, OnInit {
    private service = inject(WebhookTriggerService);
    private dialog = inject(Dialog);
    private overlay = inject(Overlay);
    private overlayPositionBuilder = inject(OverlayPositionBuilder);
    private vcr = inject(ViewContainerRef);
    private destroyRef = inject(DestroyRef);

    icon = input<string>('help_outline');
    label = input<string>('Webhook Trigger');
    required = input<boolean>(false);
    tooltipText = input<string>('Pick an existing webhook trigger, or create a new one.');
    placeholder = input<string>('Select a trigger');
    /** Allow the localhost provider. Off for Telegram (bot API can't reach localhost webhooks). */
    allowLocalhost = input<boolean>(true);
    /** Message shown when the currently selected trigger uses a disallowed provider. */
    disallowedProviderMessage = input<string>('This provider is not supported here.');

    /** Emits the resolved trigger model (or null when cleared). */
    triggerResolved = output<WebhookTriggerModel | null>();

    triggers = signal<WebhookTriggerModel[]>([]);
    private triggersLoaded = signal<boolean>(false);
    selectedId = signal<number | null>(null);
    searchTerm = signal<string>('');
    open = signal<boolean>(false);
    controlDisabled = signal<boolean>(false);

    selectedTrigger = computed<WebhookTriggerModel | null>(() => {
        const id = this.selectedId();
        if (id == null) return null;
        return this.triggers().find((t) => t.id === id) ?? null;
    });

    isTriggerDisallowed = (t: WebhookTriggerModel): boolean =>
        !this.allowLocalhost() && t.provider_type === 'localhost';

    selectedIsDisallowed = computed<boolean>(() => {
        const t = this.selectedTrigger();
        return t != null && this.isTriggerDisallowed(t);
    });

    filteredTriggers = computed<WebhookTriggerModel[]>(() => {
        const term = this.searchTerm().trim().toLowerCase();
        const list = this.triggers();
        if (!term) return list;
        return list.filter((t) => this.triggerName(t).toLowerCase().includes(term));
    });

    private triggerName(t: WebhookTriggerModel): string {
        switch (t.provider_type) {
            case 'ngrok':
                return t.ngrok_config?.name ?? '';
            case 'localhost':
                return t.localhost_config?.name ?? '';
            default:
                return t.path ?? '';
        }
    }

    private onChange: (value: number | null) => void = () => {};
    private onTouched: () => void = () => {};

    @ViewChild('triggerBtn') triggerBtn!: ElementRef<HTMLButtonElement>;
    @ViewChild('dropdownTemplate') dropdownTemplate!: TemplateRef<unknown>;

    private overlayRef: OverlayRef | null = null;

    ngOnInit(): void {
        this.loadTriggers();
        this.service.changed$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.loadTriggers());
    }

    private loadTriggers(): void {
        this.service
            .list()
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (triggers) => {
                    this.triggers.set(triggers);
                    this.triggersLoaded.set(true);
                    // Only clear when we started with a bare id (no embedded snapshot) and it's not in the list.
                    const id = this.selectedId();
                    if (id != null && !triggers.some((t) => t.id === id)) {
                        this.selectedId.set(null);
                        this.onChange(null);
                    }
                    this.triggerResolved.emit(this.selectedTrigger());
                },
            });
    }

    displayLabel(t: WebhookTriggerModel): string {
        return `${this.triggerName(t)} (${t.provider_type ?? 'none'})`;
    }

    toggle(): void {
        if (this.controlDisabled()) return;
        this.open() ? this.close() : this.openDropdown();
    }

    openDropdown(): void {
        if (!this.overlayRef) {
            const positionStrategy = this.overlayPositionBuilder
                .flexibleConnectedTo(this.triggerBtn)
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
        if (this.overlayRef) this.overlayRef.detach();
        this.searchTerm.set('');
        this.onTouched();
        this.open.set(false);
    }

    onSearchInput(value: string): void {
        this.searchTerm.set(value);
    }

    onSelect(trigger: WebhookTriggerModel): void {
        if (this.controlDisabled()) return;
        if (this.isTriggerDisallowed(trigger)) return;
        const id = trigger.id ?? null;
        this.selectedId.set(id);
        this.onChange(id);
        this.triggerResolved.emit(trigger);
        this.close();
    }

    onCreate(): void {
        if (this.controlDisabled()) return;
        this.close();
        this.dialog
            .open<WebhookTriggerModel | null, WebhookTriggerDialogData>(WebhookTriggerDialogComponent, {
                disableClose: true,
                data: { trigger: null },
            })
            .closed.pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((created) => {
                if (!created || created.id == null) return;
                // Ensure the newly created trigger is in the local list before selecting.
                this.triggers.update((list) => (list.some((t) => t.id === created.id) ? list : [...list, created]));
                this.selectedId.set(created.id);
                this.onChange(created.id);
                this.triggerResolved.emit(created);
            });
    }

    // --- ControlValueAccessor ---
    writeValue(value: number | null): void {
        if (value == null) {
            this.selectedId.set(null);
        } else {
            this.selectedId.set(value);
        }
        if (this.triggersLoaded()) {
            const id = this.selectedId();
            if (id != null && !this.triggers().some((t) => t.id === id)) {
                this.selectedId.set(null);
            }
        }
        this.triggerResolved.emit(this.selectedTrigger());
    }

    registerOnChange(fn: (value: number | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(isDisabled: boolean): void {
        this.controlDisabled.set(isDisabled);
    }
}
