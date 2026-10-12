import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    effect,
    ElementRef,
    inject,
    input,
    model,
    untracked,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    AppSvgIconComponent,
    BinnedSecretNoteComponent,
    HelpTooltipComponent,
    MultiSelectComponent,
    SelectItem,
} from '@shared/components';
import { SecretsStorageService } from '@shared/services';

import { ToastService } from '../../../services/notifications';

/** A "Secrets" field (label + input-styled trigger + multi-select dropdown) for node side
 *  panels — lets a node reference multiple secrets by id. Reused across Python/Webhook/CDT/
 *  Telegram node panels instead of duplicating the trigger+dropdown wiring in each one. */
@Component({
    selector: 'app-node-secrets-field',
    imports: [AppSvgIconComponent, BinnedSecretNoteComponent, HelpTooltipComponent, MultiSelectComponent],
    templateUrl: './node-secrets-field.component.html',
    styleUrls: ['./node-secrets-field.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NodeSecretsFieldComponent {
    private readonly secretsStorageService = inject(SecretsStorageService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly toastService = inject(ToastService);

    public readonly activeColor = input<string>('var(--accent-color)');
    public readonly value = model<number[]>([]);
    public readonly tooltipText = input<string>(
        "Secrets this node can access at runtime — create and manage secrets under Settings → Secrets. Press Ctrl+Space in the code editor to insert get_secret('name')."
    );
    public readonly readonly = input<boolean>(false);
    public readonly names = input<string[]>([]);
    /** Dropdown width — narrow panels (e.g. CDT's 350px sidebar) need a smaller value than
     *  the 390px default so the panel doesn't overflow past the field's own column. */
    public readonly panelWidth = input<string>('390px');

    private readonly trigger = viewChild<ElementRef<HTMLButtonElement>>('trigger');
    public readonly multiSelectRef = viewChild<MultiSelectComponent>('multiSelect');

    /** The live secrets, plus a picked one in the recycle bin: it stays checked, so saving keeps it. */
    public readonly secretItems = computed<SelectItem[]>(() => this.secretsStorageService.selectItems(this.value()));

    public readonly readonlyItems = computed<SelectItem[]>(() => this.names().map((name) => ({ name, value: name })));

    public readonly triggerLabel = computed(() => {
        if (this.readonly()) {
            const count = this.names().length;
            return count > 0 ? `${count} selected` : 'No secrets assigned';
        }
        // Count only ids the dropdown can show checked: live secrets and binned ones. An id of a
        // secret deleted for good can still sit in value() (nothing prunes it), and counting it
        // would show a number the checked rows can't match.
        const existingIds = new Set(this.secretItems().map((item) => item.value));
        const count = this.value().filter((id) => existingIds.has(id)).length;
        return count > 0 ? `${count} selected` : 'Select a secret';
    });

    constructor() {
        effect(() => {
            if (this.readonly()) return;
            untracked(() =>
                this.secretsStorageService
                    .getSecrets()
                    .pipe(takeUntilDestroyed(this.destroyRef))
                    .subscribe({
                        error: () => this.toastService.error('Failed to load secrets.'),
                    })
            );
        });
    }

    public openDropdown(): void {
        const el = this.trigger()?.nativeElement;
        if (!el) return;
        this.multiSelectRef()?.openAt(el, this.readonly() ? this.names() : this.value());
    }

    public onSelectionChange(values: unknown[]): void {
        this.value.set(values as number[]);
    }
}
