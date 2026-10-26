import { Pipe, PipeTransform } from '@angular/core';
import { runtimeNodeNameToLabel } from '@shared/utils';

/** Shows a session message's runtime node name ("Fetch #3 #1742") as its label ("Fetch #3"). */
@Pipe({
    name: 'runtimeNodeLabel',
})
export class RuntimeNodeLabelPipe implements PipeTransform {
    transform(runtimeNodeName: string): string {
        return runtimeNodeNameToLabel(runtimeNodeName);
    }
}
