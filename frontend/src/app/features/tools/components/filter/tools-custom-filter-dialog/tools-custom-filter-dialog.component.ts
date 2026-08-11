import { DIALOG_DATA, DialogRef } from '@angular/cdk/dialog';
import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppSvgIconComponent, ButtonComponent } from '@shared/components';

import {
    CustomFilterClause,
    CustomFilterCondition,
    CustomFilterScope,
    FILTER_OPERATOR_LABELS,
    FILTER_OPERATOR_ORDER,
    FilterOperator,
    LogicalCombinator,
} from '../../../models/tool-filter.model';

export interface ToolsCustomFilterDialogData {
    initialCondition: CustomFilterCondition | null;
}

export type ToolsCustomFilterDialogResult = { condition: CustomFilterCondition | null };

/**
 * Tools custom filter dialog. Mirrors the flows equivalent — kept feature-local
 * for now (may be lifted once the two features converge on a shared primitive).
 */
@Component({
    selector: 'app-tools-custom-filter-dialog',
    standalone: true,
    imports: [CommonModule, FormsModule, ButtonComponent, AppSvgIconComponent],
    templateUrl: './tools-custom-filter-dialog.component.html',
    styleUrls: ['./tools-custom-filter-dialog.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ToolsCustomFilterDialogComponent {
    private readonly dialogRef = inject<DialogRef<ToolsCustomFilterDialogResult | undefined>>(DialogRef);
    private readonly data = inject<ToolsCustomFilterDialogData>(DIALOG_DATA);

    public readonly operatorOptions = FILTER_OPERATOR_ORDER;
    public readonly operatorLabels = FILTER_OPERATOR_LABELS;

    public readonly scope = signal<CustomFilterScope>(this.data.initialCondition?.scope ?? 'tool_name');
    public readonly primaryOperator = signal<FilterOperator>(this.data.initialCondition?.primary.operator ?? 'equals');
    public readonly primaryValue = signal<string>(this.data.initialCondition?.primary.value ?? '');
    public readonly combinator = signal<LogicalCombinator>(this.data.initialCondition?.combinator ?? 'OR');
    public readonly secondaryOperator = signal<FilterOperator>(
        this.data.initialCondition?.secondary?.operator ?? 'equals'
    );
    public readonly secondaryValue = signal<string>(this.data.initialCondition?.secondary?.value ?? '');

    public readonly operatorOpenFor = signal<'primary' | 'secondary' | null>(null);

    public readonly headingText = computed(() =>
        this.scope() === 'tool_name'
            ? 'Show tools matching the name conditions'
            : 'Show tools matching the label conditions'
    );

    public setScope(scope: CustomFilterScope): void {
        this.scope.set(scope);
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

        const primary: CustomFilterClause = {
            operator: this.primaryOperator(),
            value: primaryValue,
        };

        const secondaryValue = this.secondaryValue().trim();
        const secondary: CustomFilterClause | undefined = secondaryValue
            ? { operator: this.secondaryOperator(), value: secondaryValue }
            : undefined;

        const condition: CustomFilterCondition = {
            scope: this.scope(),
            primary,
            combinator: this.combinator(),
            secondary,
        };

        this.dialogRef.close({ condition });
    }
}
