import { ChangeDetectionStrategy, Component } from "@angular/core";
import { StrategyForm } from "../strategy-config-form.abstract";
import { FormGroup, ReactiveFormsModule, Validators } from "@angular/forms";
import {
    ChipsInputComponent,
    InputNumberComponent,
    SelectItem,
    ToggleSwitchComponent,
    ValidationErrorsComponent
} from "@shared/components";
import { MATERIAL_FORMS } from "@shared/material-forms";
import { MarkdownStrategyModel } from "../../../../../models/strategy.model";

@Component({
    selector: 'app-markdown-form',
    templateUrl: './markdown-form.component.html',
    styleUrls: ['../../document-config.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ChipsInputComponent,
        ToggleSwitchComponent,
        MATERIAL_FORMS,
        InputNumberComponent,
        ReactiveFormsModule,
        ValidationErrorsComponent
    ]
})
export class MarkdownFormComponent extends StrategyForm<MarkdownStrategyModel> {
    headerItems: SelectItem[] = [
        {
            name: '# Header 1',
            value: '#'
        },
        {
            name: '## Header 2',
            value: '##'
        },
        {
            name: '### Header 3',
            value: '###'
        },
        {
            name: '#### Header 4',
            value: '####'
        },
        {
            name: '##### Header 5',
            value: '#####'
        },
        {
            name: '###### Header 6',
            value: '######'
        },
    ]

    initializeForm(config: MarkdownStrategyModel): FormGroup {
        return this.fb.group({
            mainParams: this.fb.group({
                chunk_size: [config.chunk_size || 20, [Validators.required, Validators.min(20), Validators.max(8000)]],
                chunk_overlap: [config.chunk_overlap || 0, [Validators.required, Validators.min(0), Validators.max(1000)]],
            }),
            additionalParams: this.fb.group({
                headers_to_split_on: [config.headers_to_split_on || []],
                return_each_line: [config.return_each_line || false],
                strip_headers: [config.strip_headers || false],
            })
        });
    }
}
