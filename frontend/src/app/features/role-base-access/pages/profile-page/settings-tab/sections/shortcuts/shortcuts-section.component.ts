import { Component, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { ButtonComponent } from '@shared/components';
import { catchError, of } from 'rxjs';

import { ActiveOrgService } from '../../../../../../../services/auth/active-org.service';
import { ShortcutsEditorComponent } from '../../../../../../../visual-programming/components/shortcuts-editor/shortcuts-editor.component';
import { GetGraphLightRequest } from '../../../../../../flows/models/graph.model';
import { FlowsApiService } from '../../../../../../flows/services/flows-api.service';
import { SettingsSectionComponent } from '../../settings-section/settings-section.component';

/**
 * Settings → Shortcuts: the flow editor's shortcuts, edited outside any flow. "Reset to defaults" and "Add shortcut"
 * sit in the section header and call the editor, which owns what they do.
 */
@Component({
    selector: 'app-shortcuts-section',
    templateUrl: './shortcuts-section.component.html',
    styleUrls: ['./shortcuts-section.component.scss'],
    imports: [ButtonComponent, ShortcutsEditorComponent, SettingsSectionComponent],
})
export class ShortcutsSectionComponent {
    private readonly flowsApi = inject(FlowsApiService);
    private readonly activeOrgService = inject(ActiveOrgService);

    // Subgraph shortcuts name a flow of the active org; reloaded when the user switches org.
    private readonly flowsResource = rxResource({
        params: () => this.activeOrgService.activeOrgId() ?? undefined,
        stream: () => this.flowsApi.getGraphsLight().pipe(catchError(() => of([] as GetGraphLightRequest[]))),
    });

    protected readonly flows = computed<readonly GetGraphLightRequest[]>(() =>
        this.flowsResource.hasValue() ? this.flowsResource.value() : []
    );
}
