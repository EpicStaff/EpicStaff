import { ChangeDetectionStrategy, Component } from "@angular/core";
import { jsonValidator } from "@shared/form-validators";
import { StrategyForm } from "../strategy-config-form.abstract";
import { FormGroup, ReactiveFormsModule, Validators } from "@angular/forms";
import { HtmlStrategyModel } from "../../../../../models/strategy.model";
import {
    CustomInputComponent, InputNumberComponent,
    JsonEditorComponent,
    ToggleSwitchComponent, ValidationErrorsComponent
} from "@shared/components";
import { MATERIAL_FORMS } from "@shared/material-forms";

@Component({
    selector: 'app-html-form',
    templateUrl: './html-form.component.html',
    styleUrls: ['../../document-config.component.scss'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    imports: [
        ToggleSwitchComponent,
        MATERIAL_FORMS,
        CustomInputComponent,
        ReactiveFormsModule,
        JsonEditorComponent,
        InputNumberComponent,
        ValidationErrorsComponent
    ]
})
export class HtmlFormComponent extends StrategyForm<HtmlStrategyModel> {
    jsonData: string = '{}';
    editorOptions: any = {
        lineNumbers: 'off',
        theme: 'vs-dark',
        language: 'json',
        automaticLayout: true,
        minimap: {enabled: false},
        scrollBeyondLastLine: false,
        wordWrap: 'on',
        wrappingIndent: 'indent',
        wordWrapBreakAfterCharacters: ',',
        wordWrapBreakBeforeCharacters: '}]',
        tabSize: 2,
    };

    additionalParamsFG!: FormGroup;

    onJsonChange(value: string) {
        const control = this.additionalParamsFG.get('external_metadata');

        control?.setValue(value);
    }

    initializeForm(config: HtmlStrategyModel): FormGroup {
        this.additionalParamsFG = this.fb.group({
            preserve_links: [config.preserve_links || false],
            normalize_text: [config.normalize_text || false],
            external_metadata: [config.external_metadata || '{}', jsonValidator()],
            denylist_tags: [config.denylist_tags || ''],
        });

        this.jsonData = config.external_metadata || '{}';
        return this.fb.group({
            mainParams: this.fb.group({
                chunk_size: [config.chunk_size || 20, [Validators.required, Validators.min(20), Validators.max(8000)]],
                chunk_overlap: [config.chunk_overlap || 0, [Validators.required, Validators.min(0), Validators.max(1000)]],
            }),
            additionalParams: this.additionalParamsFG,
        });
    }
}
