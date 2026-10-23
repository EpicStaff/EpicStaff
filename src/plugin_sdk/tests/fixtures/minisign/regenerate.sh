#!/bin/sh
# Regenerate the minisign test vectors with the reference minisign tool, run in a throwaway
# Alpine container so nothing is installed on the host. Needs docker. The keys are test keys
# and protect nothing.
#
#   minisign.key / minisign.pub  unencrypted key pair (minisign -G -W)
#   encrypted.key                password-protected secret key ("test-password")
#   CONTENTS.json                the signed message, in canonical form
#   CONTENTS.json.minisig        pre-hashed signature with the package trusted comment
#   legacy.minisig               legacy (non-prehashed) signature, which EpicStaff refuses
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
CONTENTS='{"files":[{"path":"icon.svg","sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","size":0},{"path":"manifest.json","sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","size":0},{"path":"spa/index.html","sha256":"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855","size":0}],"format":1,"plugin_id":"weather","version":"0.1.0"}'

docker run --rm -i -e CONTENTS="$CONTENTS" -v "$HERE:/vectors" -w /vectors alpine:3.22 sh -eu -c '
apk add --no-cache minisign >/dev/null
minisign -v
rm -f minisign.key minisign.pub encrypted.key CONTENTS.json CONTENTS.json.minisig legacy.minisig
printf "%s" "$CONTENTS" > CONTENTS.json
minisign -G -W -p minisign.pub -s minisign.key >/dev/null
printf "test-password\ntest-password\n" | minisign -G -p /tmp/encrypted.pub -s encrypted.key >/dev/null
digest=$(sha256sum CONTENTS.json | cut -d" " -f1)
comment="plugin=weather version=0.1.0 contents_sha256=$digest"
minisign -S -s minisign.key -m CONTENTS.json -x CONTENTS.json.minisig \
  -c "signature from epicstaff-plugin" -t "$comment"
minisign -S -l -s minisign.key -m CONTENTS.json -x legacy.minisig -t "$comment"
minisign -V -q -p minisign.pub -m CONTENTS.json -x CONTENTS.json.minisig
'
