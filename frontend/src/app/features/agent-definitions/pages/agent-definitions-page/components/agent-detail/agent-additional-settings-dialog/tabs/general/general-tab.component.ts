import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormGroup, FormsModule, ReactiveFormsModule } from '@angular/forms';
import {
    LlmModelSelectorComponent,
    ToggleSwitchComponent,
    TOOLS_SOURCE,
    ToolsSelectorComponent,
    TooltipComponent,
} from '@shared/components';
import { FullLLMConfig } from '@shared/services';

import { ToolsSourceService } from '../../../../../../../../tools/services/tools-source.service';
@Component({
    selector: 'app-general-tab',
    templateUrl: './general-tab-component.html',
    styleUrls: ['../tab.component.scss'],
    imports: [
        LlmModelSelectorComponent,
        ReactiveFormsModule,
        FormsModule,
        TooltipComponent,
        ToolsSelectorComponent,
        ToggleSwitchComponent,
    ],
    changeDetection: ChangeDetectionStrategy.OnPush,
    providers: [{ provide: TOOLS_SOURCE, useExisting: ToolsSourceService }],
})
export class GeneralTabComponent {
    form = input.required<FormGroup>();
    combinedLLMs = input.required<FullLLMConfig[]>();
    loadingLLMs = input<boolean>(false);
    mergedToolsChange = output<{ id: number; configName: string; toolName: string; type: string }[]>();

    public onPythonToolsChange(pythonToolIds: number[]): void {
        this.form().patchValue({ python_code_tools: pythonToolIds });
    }

    public onMcpToolsChange(mcpToolIds: number[]): void {
        this.form().patchValue({ mcp_tools: mcpToolIds });
    }
}
