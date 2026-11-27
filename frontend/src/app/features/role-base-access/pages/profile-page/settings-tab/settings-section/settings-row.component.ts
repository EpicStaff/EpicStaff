import { Component, computed, input } from '@angular/core';

let nextRowId = 0;

/** One setting: its label and optional hint on the left, its control (projected) on the right. */
@Component({
    selector: 'app-settings-row',
    templateUrl: './settings-row.component.html',
    styleUrls: ['./settings-row.component.scss'],
})
export class SettingsRowComponent {
    readonly label = input.required<string>();
    readonly hint = input<string>();
    /**
     * Wraps the control in a group named by the label and described by the hint. Turn it off for a control that
     * carries the same name itself (a toggle with its own `ariaLabel`), so it is not read out twice.
     */
    readonly labelsControl = input(true);

    protected readonly groupRole = computed(() => (this.labelsControl() ? 'group' : null));
    protected readonly groupLabelledBy = computed(() => (this.labelsControl() ? this.labelId : null));
    protected readonly groupDescribedBy = computed(() => (this.labelsControl() && this.hint() ? this.hintId : null));

    protected readonly labelId = `settings-row-label-${++nextRowId}`;
    protected readonly hintId = `settings-row-hint-${nextRowId}`;
}
