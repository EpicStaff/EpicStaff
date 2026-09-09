import { ChangeDetectionStrategy, Component } from '@angular/core';
import { FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import {
    ChipsSelectComponent,
    InputNumberComponent,
    SelectItem,
    ToggleSwitchComponent,
    ValidationErrorsComponent,
} from '@shared/components';
import { DEFAULT_STEP_SIZE } from '@shared/constants';
import { MATERIAL_FORMS } from '@shared/material-forms';

import { HelpTooltipComponent } from '../../../../../../../shared/components/help-tooltip/help-tooltip.component';
import { MarkdownStrategyModel } from '../../../../../models/strategy.model';
import { StrategyForm } from '../strategy-config-form.abstract';

@Component({
    selector: 'app-markdown-form',
    templateUrl: './markdown-form.component.html',
    styleUrls: ['../../document-config.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        HelpTooltipComponent,
        ChipsSelectComponent,
        ToggleSwitchComponent,
        MATERIAL_FORMS,
        InputNumberComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent,
    ],
})
export class MarkdownFormComponent extends StrategyForm<MarkdownStrategyModel> {
    protected readonly DEFAULT_STEP_SIZE = DEFAULT_STEP_SIZE;

    headerItems: SelectItem[] = [
        {
            name: '# Header 1',
            value: '#',
        },
        {
            name: '## Header 2',
            value: '##',
        },
        {
            name: '### Header 3',
            value: '###',
        },
        {
            name: '#### Header 4',
            value: '####',
        },
        {
            name: '##### Header 5',
            value: '#####',
        },
        {
            name: '###### Header 6',
            value: '######',
        },
    ];

    initializeForm(config: MarkdownStrategyModel): FormGroup {
        return this.fb.group({
            mainParams: this.fb.group({
                chunk_size: [config.chunk_size || 20, [Validators.required, Validators.min(20), Validators.max(8000)]],
                chunk_overlap: [
                    config.chunk_overlap || 0,
                    [Validators.required, Validators.min(0), Validators.max(1000)],
                ],
            }),
            additionalParams: this.fb.group({
                headers_to_split_on: [config.headers_to_split_on || []],
                return_each_line: [config.return_each_line || false],
                strip_headers: [config.strip_headers || false],
            }),
        });
    }
}
