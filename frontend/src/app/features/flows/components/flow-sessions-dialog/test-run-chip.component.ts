import { Component } from '@angular/core';
import { MatTooltipModule } from '@angular/material/tooltip';

/** Accessible name and tooltip of the chip. */
const TEST_RUN_CHIP_LABEL = 'Test run';
const TEST_RUN_CHIP_ICON = 'ti ti-flask';

/** Icon-only marker of a test-run session; the parent decides when to render it (see `isTestRunTrigger`). */
@Component({
    selector: 'app-test-run-chip',
    imports: [MatTooltipModule],
    template: `
        <span
            class="test-run-chip"
            role="img"
            [attr.aria-label]="label"
            [matTooltip]="label"
        >
            <i
                [class]="icon"
                aria-hidden="true"
            ></i>
        </span>
    `,
    styleUrls: ['./test-run-chip.component.scss'],
})
export class TestRunChipComponent {
    protected readonly label = TEST_RUN_CHIP_LABEL;
    protected readonly icon = TEST_RUN_CHIP_ICON;
}
