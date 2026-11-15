use strict;
use warnings;

use JSON::PP;
use Test::More;

use FindBin;
use lib "$FindBin::Bin/../lib";
use NicTool::Transport::REST;

{
    package Local::HTTP;

    sub new {
        my ( $class, @responses ) = @_;
        return bless { requests => [], responses => \@responses }, $class;
    }

    sub request {
        my ( $self, $method, $url, $options ) = @_;
        push @{ $self->{requests} }, [ $method, $url, $options ];
        return shift @{ $self->{responses} };
    }
}

my $JSON = JSON::PP->new->canonical;

sub response {
    my ( $data, $status ) = @_;
    return { status => $status // 200, content => $JSON->encode($data) };
}

sub refusal {
    my ( $status, $message ) = @_;
    return response( { statusCode => $status, error => 'Bad Request', message => $message }, $status );
}

sub transport {
    my (@responses) = @_;
    my $rest = NicTool::Transport::REST->new( bless { _rest_jwt_token => 'jwt' }, 'Local::NicTool' );
    $rest->{http} = Local::HTTP->new(@responses);
    return $rest;
}

sub call {
    my ( $rest, %vars ) = @_;
    return $rest->send_request( 'http://api:3000', %vars );
}

sub requests { return @{ $_[0]->{http}{requests} } }

sub body {
    my ( $rest, $n ) = @_;
    return $JSON->decode( ( requests($rest) )[ $n // 0 ][2]{content} );
}

# parameter checks answer like v2's server, before any v3 request
{
    my $rest = transport();
    my $res  = call( $rest, action => 'new_user', nt_group_id => 2, username => 'u',
        email => 'u@example.com', password => 'x' );
    is "$res->{error_code} $res->{error_msg}", '301 password2', 'a missing password2 is 301';

    $res = call( $rest, action => 'new_user', nt_group_id => 'abc', username => 'u',
        email => 'u@example.com', password => 'x', password2 => 'x' );
    is "$res->{error_code} $res->{error_msg}", '302 nt_group_id', 'a bad group id is 302';
    is scalar( requests($rest) ), 0, 'neither reaches v3';
}

# zones take v2's SOA defaults and lose every trailing dot
{
    my $rest = transport( response( { zone => [ { id => 9, gid => 2 } ] } ) );
    my $res  = call( $rest, action => 'new_zone', nt_group_id => 2, zone => 'Dots.example..',
        nameservers => '', refresh => 100 );
    is $res->{nt_zone_id}, 9, 'an empty nameserver list is not an invalid id';
    my $body = body($rest);
    is $body->{zone},     'Dots.example', 'trailing dots are stripped';
    is $body->{refresh},  100,            'a given SOA timer is kept';
    is $body->{retry},    900,            'a missing SOA timer gets the v2 default';
    is $body->{mailaddr}, 'hostmaster.Dots.example.', 'a missing mailaddr gets the v2 default';
}

# new_zone_record with an existing id updates that record
{
    my $rest = transport( response( { zone_record => [ { id => 7, zid => 5, owner => 'a.zone.com.',
        type => 'A', address => '192.0.2.1', ttl => 300 } ] } ) );
    my $res = call( $rest, action => 'new_zone_record', nt_zone_record_id => 7, nt_zone_id => 5,
        name => 'a.zone.com.', type => 'A', address => '192.0.2.1', ttl => 300 );
    is $res->{error_code}, 200, 'the update succeeds';
    is $res->{nt_zone_record_id}, 7, 'the result names the updated record';
    my ($put) = grep { $_->[0] eq 'PUT' } requests($rest);
    like $put->[1], qr{/zone_record/7$}, 'the record is updated in place';
}

# v3 refusals take v2's codes
{
    my $res = call( transport( refusal( 400, '"ttl" must be a number' ) ),
        action => 'new_zone', nt_group_id => 2, zone => 'z.example', ttl => 'abc' );
    is "$res->{error_code} $res->{error_desc}", '300 Sanity error', 'a v3 400 is a v2 sanity error';

    $res = call( transport( response( { error => 'Cannot delete group: active subgroups still exist.' }, 409 ) ),
        action => 'delete_group', nt_group_id => 3 );
    is $res->{error_code}, 600, 'deleting a group with children is a v2 failure';
    is $res->{error_msg}, "You can't delete this group until you delete all of its sub-groups",
        'in v2 words';

    $res = call( transport( response( { error => 'zone z.example already exists' }, 409 ) ),
        action => 'new_zone', nt_group_id => 2, zone => 'z.example' );
    is "$res->{error_code} $res->{error_msg}", '300 Zone is already taken', 'a taken zone name';

    $res = call( transport( response( { error => 'Invalid authentication' }, 401 ) ),
        action => 'login', username => 'u@g', password => 'wrong' );
    is $res->{error_msg}, 'Invalid username and/or password.', 'a failed login reads like v2';
}

# logout clears the client's session
{
    my $res = call( transport( response( {} ) ), action => 'logout' );
    is $res->{nt_user_session}, '', 'logout answers with an empty session';
}

done_testing();
