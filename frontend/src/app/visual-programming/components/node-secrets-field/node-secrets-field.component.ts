import {
    ChangeDetectionStrategy,
    Component,
    computed,
    DestroyRef,
    ElementRef,
    inject,
    input,
    model,
    viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { SecretDeclarationIndexService, SecretsStorageService } from '@shared/services';

import { ToastService } from '../../../services/notifications';
import { AppSvgIconComponent } from '../../../shared/components/app-svg-icon/app-svg-icon.component';
import { HelpTooltipComponent } from '../../../shared/components/help-tooltip/help-tooltip.component';
import { MultiSelectComponent } from '../../../shared/components/multi-select/multi-select.component';
import { SelectItem } from '../../../shared/components/select/select.component';

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
    private readonly secretDeclarationIndexService = inject(SecretDeclarationIndexService);
    private readonly destroyRef = inject(DestroyRef);
    private readonly toastService = inject(ToastService);

    public readonly activeColor = input<string>('#685fff');
    public readonly value = model<number[]>([]);
    public readonly tooltipText = input<string>(
        "Secrets this node can access at runtime — create and manage secrets under Settings → Secrets. Press Ctrl+Space in the code editor to insert get_secret('name')."
    );
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

    public readonly selectionUnknown = computed(
        () => !this.readForbidden() && this.secretDeclarationIndexService.indexUnavailable()
    );

    public readonly triggerLabel = computed(() => {
        if (this.readForbidden()) {
            const declared = this.value().length;
            return declared > 0 ? `${declared} selected — no access` : 'No access to secrets';
        }
        if (this.selectionUnknown() && this.value().length === 0) {
            return 'Selection hidden — pick to overwrite';
        }
        // Count only ids that still resolve to an existing secret — a since-deleted secret's id
        // can still be sitting in value() (nothing prunes it), and counting it here would show a
        // number the dropdown's checked rows can't match.
        const existingIds = new Set(this.secretsStorageService.secrets().map((secret) => secret.id));
        const count = this.value().filter((id) => existingIds.has(id)).length;
        return count > 0 ? `${count} selected` : 'Select a secret';
    });

    constructor() {
        this.loadSecrets();
    }

    public openDropdown(): void {
        if (this.readForbidden()) return;
        const el = this.trigger()?.nativeElement;
        if (!el) return;
        this.loadSecrets();
        this.multiSelectRef()?.openAt(el, this.value());
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
