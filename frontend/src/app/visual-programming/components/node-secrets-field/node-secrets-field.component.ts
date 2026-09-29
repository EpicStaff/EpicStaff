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
import { AppSvgIconComponent, HelpTooltipComponent, MultiSelectComponent, SelectItem } from '@shared/components';
import { SecretsStorageService } from '@shared/services';

import { ToastService } from '../../../services/notifications';

/** A "Secrets" field (label + input-styled trigger + multi-select dropdown) for node side
 *  panels — lets a node reference multiple secrets by id. Reused across Python/Webhook/CDT/
 *  Telegram node panels instead of duplicating the trigger+dropdown wiring in each one. */
@Component({
    selector: 'app-node-secrets-field',
    imports: [AppSvgIconComponent, HelpTooltipComponent, MultiSelectComponent],
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

    public readonly secretItems = computed<SelectItem[]>(() =>
        this.secretsStorageService.secrets().map((secret) => ({
            name: secret.name,
            value: secret.id,
            tip: this.secretsStorageService.maskTail(secret.tail),
        }))
    );

    public readonly readForbidden = computed(() => this.secretsStorageService.readForbidden());

    public readonly readonlyItems = computed<SelectItem[]>(() => this.names().map((name) => ({ name, value: name })));

    public readonly triggerLabel = computed(() => {
        if (this.readForbidden()) {
            const declared = this.value().length;
            return declared > 0 ? `${declared} selected — no access` : 'No access to secrets';
        }
        if (this.readonly()) {
            const count = this.names().length;
            return count > 0 ? `${count} selected` : 'No secrets assigned';
        }
        // Count only ids that still resolve to an existing secret — a since-deleted secret's id
        // can still be sitting in value() (nothing prunes it), and counting it here would show a
        // number the dropdown's checked rows can't match.
        const existingIds = new Set(this.secretsStorageService.secrets().map((secret) => secret.id));
        const count = this.value().filter((id) => existingIds.has(id)).length;
        return count > 0 ? `${count} selected` : 'Select a secret';
    });

    private readonly refetchedForUnknownIds = new Set<number>();

    constructor() {
        effect(() => {
            if (this.readonly()) return;
            untracked(() => this.loadSecrets());
        });

        // EST-3922: prune ids of secrets deleted since the node was saved. Refetch once per unknown
        // id first, so a secret created in another tab is not dropped by a stale cache.
        effect(() => {
            if (this.readonly() || this.readForbidden()) return;
            const knownIds = new Set(this.secretsStorageService.secrets().map((secret) => secret.id));
            const missing = this.value().filter((id) => !knownIds.has(id));
            if (missing.length === 0) return;

            const unchecked = missing.filter((id) => !this.refetchedForUnknownIds.has(id));
            if (unchecked.length > 0) {
                unchecked.forEach((id) => this.refetchedForUnknownIds.add(id));
                untracked(() => this.loadSecrets());
                return;
            }

            this.value.set(this.value().filter((id) => knownIds.has(id)));
            this.toastService.error(
                'Some selected secrets no longer exist and were removed from this node.',
                5000,
                'bottom-right'
            );
        });
    }

    public openDropdown(): void {
        if (this.readForbidden() && !this.readonly()) return;
        const el = this.trigger()?.nativeElement;
        if (!el) return;
        if (!this.readonly()) this.loadSecrets();
        this.multiSelectRef()?.openAt(el, this.readonly() ? this.names() : this.value());
    }

    private loadSecrets(): void {
        this.secretsStorageService
            .getSecrets(true)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                error: () => this.toastService.error('Failed to load secrets.'),
            });
    }

    public onSelectionChange(values: unknown[]): void {
        this.value.set(values as number[]);
    }
}
