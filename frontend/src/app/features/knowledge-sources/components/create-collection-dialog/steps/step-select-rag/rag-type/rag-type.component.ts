import { ChangeDetectionStrategy, Component, input } from "@angular/core";
import { AppIconComponent } from "@shared/components";
import { Rag } from "../../../../../models/naive-rag.model";

@Component({
    selector: 'app-rag-type',
    templateUrl: './rag-type.component.html',
    styleUrls: ['./rag-type.component.scss'],
    imports: [
        AppIconComponent
    ],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class RagTypeComponent {
    rag = input.required<Rag>();
    selected = input<boolean>(false);
}
