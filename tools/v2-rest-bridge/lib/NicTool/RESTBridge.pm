package NicTool::RESTBridge;

# Loaded with PERL5OPT=-MNicTool::RESTBridge, so unmodified v2 code speaks
# REST to v3 when NICTOOL_DATA_PROTOCOL=rest.

use strict;
use warnings;

if ( lc( $ENV{NICTOOL_DATA_PROTOCOL} // '' ) eq 'rest' ) {
    require NicTool;
    require NicTool::Transport;
    require NicTool::Transport::REST;

    no warnings 'redefine';

    my $new = \&NicTool::new;
    *NicTool::new = sub {
        my ( $pkg, %conf ) = @_;
        $conf{data_protocol}     = 'rest';
        $conf{server_host}       = $ENV{NICTOOL_SERVER_HOST}     if $ENV{NICTOOL_SERVER_HOST};
        $conf{server_port}       = $ENV{NICTOOL_SERVER_PORT}     if $ENV{NICTOOL_SERVER_PORT};
        $conf{transfer_protocol} = $ENV{NICTOOL_SERVER_PROTOCOL} if $ENV{NICTOOL_SERVER_PROTOCOL};
        return $new->( $pkg, %conf );
    };

    *NicTool::Transport::get_transport_agent = sub {
        my ( $pkg, $protocol, $nt ) = @_;
        die "NicTool::RESTBridge: REST was requested but '$protocol' was chosen\n"
            unless lc( $protocol // '' ) eq 'rest';
        return NicTool::Transport::REST->new($nt);
    };
}

1;
