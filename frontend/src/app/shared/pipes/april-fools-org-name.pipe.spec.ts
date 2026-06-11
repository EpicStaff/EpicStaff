import { AprilFoolsOrgNamePipe } from './april-fools-org-name.pipe';

describe('AprilFoolsOrgNamePipe', () => {
    let pipe: AprilFoolsOrgNamePipe;

    beforeEach(() => {
        pipe = new AprilFoolsOrgNamePipe();
        jasmine.clock().install();
    });

    afterEach(() => {
        jasmine.clock().uninstall();
    });

    it('appends 🤡 when UTC date is April 1st', () => {
        jasmine.clock().mockDate(new Date(Date.UTC(2024, 3, 1)));
        expect(pipe.transform('Acme')).toBe('Acme🤡');
    });

    it('returns name unchanged when UTC date is April 2nd', () => {
        jasmine.clock().mockDate(new Date(Date.UTC(2024, 3, 2)));
        expect(pipe.transform('Acme')).toBe('Acme');
    });
});
