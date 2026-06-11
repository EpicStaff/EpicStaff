import { Pipe, PipeTransform } from '@angular/core';

@Pipe({
    name: 'aprilFoolsOrgName',
})
export class AprilFoolsOrgNamePipe implements PipeTransform {
    transform(name: string): string {
        const now = new Date();
        if (now.getUTCMonth() === 3 && now.getUTCDate() === 1) {
            return `${name}🤡`;
        }
        return name;
    }
}
