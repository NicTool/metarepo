#!/bin/sh
# Run v2 server tests over the bridge, from inside nictool-legacy:
#   prove.sh xt/14_permissions.t ...
# The tests run from a scratch copy, so the mounted v2 checkout stays untouched.
set -eu

work=$(mktemp -d /tmp/v2-rest.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
cp -a /usr/local/nictool/server/. "$work/"
cd "$work"

# v3 refuses the weak passwords v2's tests give the users they create
perl -pi -e "s/'testpass2'/'T3st!P\@ss88'/g; s/'testpass3'/'T3st!P\@ss77'/g;
    s/'testpass'/'T3st!P\@ss99'/g; s/'testing123'/'T3st!\@Ng12AB'/g;
    s/'somethingelse'/'S0me!Th1ng#else'/g; s/'something'/'S0me!Th1ng#'/g;
    s/'another'/'An0ther!X#9'/g; s/\@blah\.blah'/\@example.com'/g" xt/*.t t/*.t

PERL5LIB="/opt/nt-bridge/lib:$work/api/lib${PERL5LIB:+:$PERL5LIB}"
PERL5OPT=-MNicTool::RESTBridge
export PERL5LIB PERL5OPT
prove -v "$@"
