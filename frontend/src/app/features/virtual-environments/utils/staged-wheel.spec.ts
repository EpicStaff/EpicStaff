import {
    canonicalizeDistribution,
    detectedLibraryName,
    diagnoseStagedWheels,
    MAX_WHEEL_FILE_BYTES,
    readWheelFilename,
    StagedWheelIssue,
} from './staged-wheel';

/** A chosen file of a given name, and of a size only the size check ever looks at. */
function chosen(name: string, size = 1_024): File {
    const file = new File(['payload'], name);
    Object.defineProperty(file, 'size', { value: size });
    return file;
}

function issues(files: File[]): (StagedWheelIssue | null)[] {
    return diagnoseStagedWheels(files).map((wheel) => wheel.issue);
}

describe('readWheelFilename', () => {
    it.each([
        ['print_hello_world-0.3.0-py3-none-any.whl', 'print-hello-world', '0.3.0'],
        ['print_hello_world-0.3.0-1-py3-none-any.whl', 'print-hello-world', '0.3.0'],
        ['Print_Hello_World-1.0-py3-none-any.whl', 'print-hello-world', '1.0'],
        ['requests-2.32.3-py3-none-any.whl', 'requests', '2.32.3'],
    ])('reads %s as %s %s', (filename, distribution, version) => {
        expect(readWheelFilename(filename)).toEqual({ distribution, version });
    });

    it.each([
        ['setup.exe'],
        ['print_hello_world.whl'],
        ['print_hello_world-py3-none-any.whl'],
        // A source archive is stored under a name the service picks itself, so its own says nothing.
        ['print-hello-world-0.4.0.tar.gz'],
        ['lib_pyproject.tar.gz'],
    ])('reads nothing out of %s', (filename) => {
        expect(readWheelFilename(filename)).toBeNull();
    });
});

describe('canonicalizeDistribution', () => {
    it.each([
        ['Print_Hello_World', 'print-hello-world'],
        ['zope.interface', 'zope-interface'],
        ['ruamel__yaml', 'ruamel-yaml'],
    ])('spells %s as %s', (name, canonical) => {
        expect(canonicalizeDistribution(name)).toBe(canonical);
    });
});

describe('diagnoseStagedWheels', () => {
    it('accepts a wheel and a source archive together', () => {
        const staged = diagnoseStagedWheels([
            chosen('print_hello_world-0.3.0-py3-none-any.whl'),
            chosen('print-hello-world-0.4.0.tar.gz'),
        ]);

        expect(staged.map((wheel) => wheel.issue)).toEqual([null, null]);
        // Only the wheel says what it holds; an archive's version comes out of its build.
        expect(staged.map((wheel) => wheel.version)).toEqual(['0.3.0', null]);
    });

    it.each([['lib_pyproject.tar.gz'], ['whatever.zip'], ['requests-2.32.3.tar.gz']])(
        'takes the source archive %s whatever it is called',
        (filename) => {
            const staged = diagnoseStagedWheels([chosen(filename)], { libraryName: 'print-hello-world' });

            expect(staged[0].issue).toBeNull();
        }
    );

    it('holds every later wheel to the distribution the first one named', () => {
        expect(
            issues([chosen('print_hello_world-0.3.0-py3-none-any.whl'), chosen('requests-2.32.3-py3-none-any.whl')])
        ).toEqual([null, 'other-library']);
    });

    it('refuses a version that is already in the list', () => {
        expect(
            issues([
                chosen('print_hello_world-0.3.0-py3-none-any.whl'),
                chosen('print_hello_world-0.3.0-py3-none-any.whl'),
            ])
        ).toEqual([null, 'duplicate-version']);
    });

    it('refuses a version the library already holds', () => {
        const staged = diagnoseStagedWheels([chosen('print_hello_world-0.3.0-py3-none-any.whl')], {
            libraryName: 'print-hello-world',
            storedVersions: ['0.3.0'],
        });

        expect(staged[0].issue).toBe('duplicate-version');
    });

    it('holds the wheels to the name the library already has', () => {
        const staged = diagnoseStagedWheels([chosen('requests-2.32.3-py3-none-any.whl')], {
            libraryName: 'print-hello-world',
        });

        expect(staged[0].issue).toBe('other-library');
    });

    it.each([
        ['setup.exe', 'unsupported-file'],
        ['print_hello_world.whl', 'unreadable-name'],
        ['print_hello_world-py3-none-any.whl', 'unreadable-name'],
    ])('refuses %s as %s', (filename, issue) => {
        expect(issues([chosen(filename)])).toEqual([issue]);
    });

    it('refuses a file larger than the service stores', () => {
        const name = 'print_hello_world-0.3.0-py3-none-any.whl';

        expect(issues([chosen(name, MAX_WHEEL_FILE_BYTES)])).toEqual([null]);
        expect(issues([chosen(name, MAX_WHEEL_FILE_BYTES + 1)])).toEqual(['too-large']);
    });

    it('lets a refused file name nothing, so the next wheel names the library', () => {
        const staged = diagnoseStagedWheels([chosen('setup.exe'), chosen('print_hello_world-0.3.0-py3-none-any.whl')]);

        expect(detectedLibraryName(staged)).toBe('print-hello-world');
    });

    it('names no library from a source archive alone', () => {
        // The build that unpacks it names the library; it has not run yet.
        expect(detectedLibraryName(diagnoseStagedWheels([chosen('lib_pyproject.tar.gz')]))).toBeNull();
    });

    it('names no library while nothing is readable', () => {
        expect(detectedLibraryName(diagnoseStagedWheels([chosen('setup.exe')]))).toBeNull();
    });
});
