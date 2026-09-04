import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import {
    CustomFilterCondition,
    FILTER_OPERATOR_LABELS,
    FILTER_OPERATOR_ORDER,
    FilterOperator,
    LogicalCombinator,
} from '@shared/models';

import { AppSvgIconComponent } from '../../app-svg-icon/app-svg-icon.component';
import { ButtonComponent } from '../../buttons/button/button.component';

export interface CustomFilterScopeConfig {
    /** Scope identifier written into `CustomFilterCondition.scope`. */
    key: string;
    /** Scope tab label. */
    label: string;
    /** Scope tab icon name. */
    icon: string;
    /** Heading rendered above the condition rows for this scope. */
    heading: string;
}

export interface AppCustomFilterDialogData {
    /** Dialog title (default 'Custom filter'). */
    title?: string;
    /** Scope tabs (order preserved). Must contain at least one entry. */
    scopes: readonly CustomFilterScopeConfig[];
    initialCondition: CustomFilterCondition | null;
}

export interface AppCustomFilterDialogResult {
    condition: CustomFilterCondition | null;
}

/**
 * Generic "custom filter" builder — primary/secondary clause with AND/OR
 * combinator, scoped to one of the caller-supplied scopes. Each consumer only
 * needs to pass the scope config;
 */
@Component({
    selector: 'app-custom-filter-dialog',
    imports: [FormsModule, ButtonComponent, AppSvgIconComponent],
    templateUrl: './app-custom-filter-dialog.component.html',
    styleUrls: ['./app-custom-filter-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppCustomFilterDialogComponent {
    private readonly dialogRef = inject<DialogRef<AppCustomFilterDialogResult | undefined>>(DialogRef);
    private readonly data = inject<AppCustomFilterDialogData>(DIALOG_DATA);

    public readonly operatorOptions = FILTER_OPERATOR_ORDER;
    public readonly operatorLabels = FILTER_OPERATOR_LABELS;

    public readonly title = this.data.title ?? 'Custom filter';
    public readonly scopes = this.data.scopes;

    public readonly scopeKey = signal<string>(this.data.initialCondition?.scope ?? this.data.scopes[0].key);
    public readonly primaryOperator = signal<FilterOperator>(this.data.initialCondition?.primary.operator ?? 'equals');
    public readonly primaryValue = signal<string>(this.data.initialCondition?.primary.value ?? '');
    public readonly combinator = signal<LogicalCombinator>(this.data.initialCondition?.combinator ?? 'OR');
    public readonly secondaryOperator = signal<FilterOperator>(
        this.data.initialCondition?.secondary?.operator ?? 'equals'
    );
    public readonly secondaryValue = signal<string>(this.data.initialCondition?.secondary?.value ?? '');

    public readonly operatorOpenFor = signal<'primary' | 'secondary' | null>(null);

    public readonly activeScope = computed(() => this.scopes.find((s) => s.key === this.scopeKey()) ?? this.scopes[0]);

    public readonly headingText = computed(() => this.activeScope().heading);

    public setScope(key: string): void {
        this.scopeKey.set(key);
    }

    public toggleOperator(target: 'primary' | 'secondary'): void {
        this.operatorOpenFor.update((current) => (current === target ? null : target));
    }

    public selectOperator(target: 'primary' | 'secondary', operator: FilterOperator): void {
        if (target === 'primary') this.primaryOperator.set(operator);
        else this.secondaryOperator.set(operator);
        this.operatorOpenFor.set(null);
    }

    public setCombinator(value: LogicalCombinator): void {
        this.combinator.set(value);
    }

    public cancel(): void {
        this.dialogRef.close(undefined);
    }

    public clearAll(): void {
        this.dialogRef.close({ condition: null });
    }

    public apply(): void {
        const primaryValue = this.primaryValue().trim();
        if (!primaryValue) {
            this.dialogRef.close({ condition: null });
            return;
        }

        const primary = { operator: this.primaryOperator(), value: primaryValue };
        const secondaryValue = this.secondaryValue().trim();
        const secondary = secondaryValue ? { operator: this.secondaryOperator(), value: secondaryValue } : undefined;

        const condition: CustomFilterCondition = {
            scope: this.scopeKey(),
            primary,
            combinator: this.combinator(),
            secondary,
        };
        this.dialogRef.close({ condition });
    }
}
