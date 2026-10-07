import { Component, computed, input, model, output } from '@angular/core';
import { AppSvgIconComponent, JsonEditorComponent } from '@shared/components';

import { TestPayloadTextCheck } from '../../../../utils/test-run';

export const TEST_PAYLOAD_SECTION_TITLE = 'Test Input Payload';

/**
 * The "Test Input Payload" JSON editor of a trigger node panel. Lists why the text cannot be run
 * (`check`: invalid JSON, a payload the backend rejects, the node-specific rule messages) and the
 * `serverErrors` of the last run; rule hints are listed apart, muted, as they are not payload errors.
 * It decides neither what is saved nor whether Run is enabled: the panel derives those from the
 * same `check` (`TriggerTestPayloadState`), computed once per text.
 */
@Component({
    selector: 'app-test-payload-section',
    imports: [AppSvgIconComponent, JsonEditorComponent],
    templateUrl: './test-payload-section.component.html',
    styleUrls: ['./test-payload-section.component.scss'],
    host: {
        '[class.full-height]': 'fullHeight()',
    },
})
export class TestPayloadSectionComponent {
    /** The editor text. Owned by the panel so it survives this section being re-created. */
    public readonly text = model.required<string>();
    public readonly readonly = input(false);
    /** `checkTestPayloadText` of `text`, computed by the panel. */
    public readonly check = input.required<TestPayloadTextCheck>();
    public readonly serverErrors = input<readonly string[]>([]);
    public readonly editorHeight = input(220);
    /** A chevron + title toggle above the editor; without it the title moves into the editor header. */
    public readonly collapsible = input(true);
    public readonly open = model(true);
    public readonly fullHeight = input(false);
    public readonly allowExpand = input(true);
    /** Label of the editor's expand icon; name what it does when it swaps panes instead. */
    public readonly expandLabel = input('Expand editor');
    public readonly expand = output<void>();
    /**
     * Optional action (e.g. "Insert example") shown as an icon in the editor header, before the copy
     * icon; without an icon there is none. Hidden while `readonly`, as it would change the text.
     */
    public readonly actionIcon = input<string | null>(null);
    /** The action's aria-label and tooltip. */
    public readonly actionLabel = input('');
    /** Why the action cannot be used right now (its tooltip then); null enables it. */
    public readonly actionDisabledReason = input<string | null>(null);
    public readonly action = output<void>();

    protected readonly editorActionIcon = computed(() => (this.readonly() ? null : this.actionIcon()));
    protected readonly hints = computed(() => (this.check().parseError === null ? this.check().hints : []));
    protected readonly errors = computed(() => {
        const check = this.check();
        const clientErrors = check.parseError === null ? check.ruleErrors : [check.parseError];
        return [...clientErrors, ...this.serverErrors()];
    });

    protected readonly title = TEST_PAYLOAD_SECTION_TITLE;

    protected toggleOpen(): void {
        this.open.update((isOpen) => !isOpen);
    }

    protected onTextChange(text: string): void {
        this.text.set(text);
    }
}
