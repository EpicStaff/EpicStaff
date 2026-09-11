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
import { SecretsStorageService } from '@shared/services';

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
    private readonly destroyRef = inject(DestroyRef);
    private readonly toastService = inject(ToastService);

    public readonly activeColor = input<string>('#685fff');
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

    public readonly readonlyItems = computed<SelectItem[]>(() => this.names().map((name) => ({ name, value: name })));

    public readonly triggerLabel = computed(() => {
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
